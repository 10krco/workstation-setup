import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "provision.sh"


FAKE_COMMAND = r'''#!PYTHON
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

command = Path(sys.argv[0]).name
args = sys.argv[1:]
state = Path(os.environ["FAKE_STATE"])
with (state / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"command": command, "args": args}) + "\n")

if command == "nix":
    if os.environ.get("NIXPKGS_ALLOW_UNFREE") != "1" or "--impure" not in args:
        raise SystemExit("1Password CLI requires explicit unfree evaluation")
    for package in ("nixpkgs#age", "nixpkgs#jq", "nixpkgs#sops", "nixpkgs#util-linux"):
        if package not in args:
            raise SystemExit(f"missing target dependency: {package}")
    index = args.index("--command")
    raise SystemExit(subprocess.run(args[index + 1 :]).returncode)
elif command == "op":
    if args[:1] == ["whoami"]:
        if os.environ.get("FAKE_OP_AUTH_FAILURE") == "1":
            raise SystemExit(1)
        print("test@example.com")
    elif args[:1] == ["read"]:
        print("github_pat_secret", end="")
    elif args[:2] == ["signin", "--raw"]:
        if os.environ.get("FAKE_OP_AUTH_FAILURE") == "1":
            raise SystemExit(1)
        print("session-token")
    else:
        raise SystemExit(f"unexpected op arguments: {args}")
elif command == "gh":
    if args[:2] == ["auth", "login"]:
        token = sys.stdin.read()
        if token != "github_pat_secret":
            raise SystemExit("wrong token")
    elif args[:2] == ["repo", "clone"]:
        destination = Path(args[3])
        (destination / "scripts").mkdir(parents=True)
        target = destination / "scripts" / "provision-target"
        target.write_text("#!/usr/bin/env bash\nprintf '%s\\n%s\\n' \"$*\" \"$PWD\" >\"$FAKE_STATE/handoff\"\n")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    else:
        raise SystemExit(f"unexpected gh arguments: {args}")
elif command == "git":
    if args[-2:] == ["branch", "--show-current"]:
        print("main")
    elif args[-2:] == ["status", "--porcelain"]:
        pass
    elif "rev-parse" in args:
        print("main-revision")
    else:
        raise SystemExit(f"unexpected git arguments: {args}")
elif command == "sudo":
    if args[:2] == ["test", "-s"]:
        raise SystemExit(0 if os.environ.get("FAKE_EXISTING_AUTHORIZED_KEYS") == "1" else 1)
    elif args[:2] == ["test", "-d"]:
        pass
    elif args[:2] == ["test", "-f"]:
        if os.environ.get("FAKE_ISO_MARKER_MISSING") == "1":
            raise SystemExit(1)
    elif "tee" in args:
        sys.stdin.read()
    elif "ssh-keygen" in args:
        print("256 SHA256:targetfingerprint root@test (ED25519)")
elif command == "ip":
    print("eth0 UP 192.0.2.25/24")
elif command == "findmnt":
    pass
elif command == "ssh-keygen":
    if os.environ.get("FAKE_INVALID_PUBLIC_KEY") == "1":
        raise SystemExit(1)
    print("256 SHA256:adminfingerprint admin (ED25519)")
else:
    raise SystemExit(f"unexpected fake command: {command}")
'''


class ProvisionLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.state.mkdir()
        (self.state / "calls.jsonl").touch()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "fake-command"
        fake.write_text(FAKE_COMMAND.replace("PYTHON", sys.executable, 1))
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        for command in ("findmnt", "gh", "git", "ip", "nix", "op", "ssh-keygen", "sudo"):
            (self.bin / command).symlink_to(fake)
        self.env = os.environ.copy()
        self.env.update(
            {
                "FAKE_STATE": str(self.state),
                "PATH": f"{self.bin}:{self.env['PATH']}",
                "TMPDIR": str(self.root),
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def calls(self):
        return [json.loads(line) for line in (self.state / "calls.jsonl").read_text().splitlines()]

    def run_launcher(self, *args, input_text=""):
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=REPOSITORY,
            env=self.env,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_local_clones_current_main_and_hands_off_without_revision_argument(self):
        result = self.run_launcher("local", "test-host")

        self.assertEqual(result.returncode, 0, result.stderr)
        handoff = (self.state / "handoff").read_text().splitlines()
        self.assertEqual(handoff[0], "install-local test-host")
        self.assertTrue(handoff[1].endswith("/nixos-config"))
        gh_clone = next(call for call in self.calls() if call["command"] == "gh" and call["args"][:2] == ["repo", "clone"])
        self.assertIn("--branch", gh_clone["args"])
        self.assertIn("main", gh_clone["args"])
        serialized = json.dumps(self.calls())
        self.assertNotIn("github_pat_secret", serialized)
        self.assertFalse(any(path.name.startswith("nixos-bootstrap.") for path in self.root.iterdir()))

    def test_local_authentication_failure_never_clones(self):
        self.env["FAKE_OP_AUTH_FAILURE"] = "1"

        result = self.run_launcher("local", "test-host")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1password", result.stderr.lower())
        self.assertFalse(any(call["command"] == "gh" for call in self.calls()))
        self.assertFalse(any(path.name.startswith("nixos-bootstrap.") for path in self.root.iterdir()))

    def test_remote_installs_ephemeral_key_and_prints_connection_evidence(self):
        public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGwXlUIgMZDNewfvIyX5Gd1B1dIuLT7lH6N+2+FrSaSU admin-install"

        result = self.run_launcher("remote", input_text=public_key + "\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("192.0.2.25", result.stdout)
        self.assertIn("SHA256:targetfingerprint", result.stdout)
        sudo_calls = [call["args"] for call in self.calls() if call["command"] == "sudo"]
        self.assertTrue(any(args == ["test", "-d", "/sys/firmware/efi"] for args in sudo_calls))
        self.assertTrue(any("/root/.ssh/authorized_keys" in args for args in sudo_calls))
        self.assertTrue(any("sshd" in args and "start" in args for args in sudo_calls))
        self.assertFalse(any(args[:2] == ["rm", "-f"] for args in sudo_calls))
        self.assertFalse(any("sshd" in args and "stop" in args for args in sudo_calls))

    def test_remote_rejects_missing_iso_marker_before_root_mutation(self):
        self.env["FAKE_ISO_MARKER_MISSING"] = "1"

        result = self.run_launcher("remote")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("iso", result.stderr.lower())
        sudo_calls = [call["args"] for call in self.calls() if call["command"] == "sudo"]
        self.assertFalse(any("tee" in args or "sshd" in args for args in sudo_calls))

    def test_remote_rejects_malformed_ed25519_key_before_root_mutation(self):
        self.env["FAKE_INVALID_PUBLIC_KEY"] = "1"

        result = self.run_launcher("remote", input_text="ssh-ed25519 AAAATEST admin-install\n")

        self.assertNotEqual(result.returncode, 0)
        sudo_calls = [call["args"] for call in self.calls() if call["command"] == "sudo"]
        self.assertFalse(any("tee" in args or "sshd" in args for args in sudo_calls))

    def test_remote_arms_cleanup_before_external_mutations(self):
        script = SCRIPT.read_text()

        self.assertLess(
            script.index("installed_authorization=true"),
            script.index("sudo tee /root/.ssh/authorized_keys"),
        )
        self.assertLess(
            script.index("started_sshd=true"),
            script.index("sudo systemctl start sshd"),
        )

    def test_remote_refusal_preserves_existing_authorized_keys(self):
        self.env["FAKE_EXISTING_AUTHORIZED_KEYS"] = "1"

        result = self.run_launcher("remote")

        self.assertNotEqual(result.returncode, 0)
        sudo_calls = [call["args"] for call in self.calls() if call["command"] == "sudo"]
        self.assertFalse(any(args[:2] == ["rm", "-f"] for args in sudo_calls))
        self.assertFalse(any("sshd" in args and "stop" in args for args in sudo_calls))

    def test_launcher_rejects_revision_or_extra_arguments(self):
        result = self.run_launcher("local", "test-host", "deadbeef")

        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr.lower())
        self.assertEqual(self.calls(), [])

    def test_launcher_rejects_invalid_hostname_boundaries_and_length(self):
        for hostname in ("host-", "a" * 64):
            with self.subTest(hostname=hostname):
                result = self.run_launcher("local", hostname)
                self.assertEqual(result.returncode, 2)

    def test_readme_downloads_launcher_before_execution(self):
        readme = (REPOSITORY / "README.md").read_text()
        self.assertNotIn("bash <(curl", readme)
        self.assertGreaterEqual(readme.count("curl -fsSL"), 2)
        self.assertGreaterEqual(readme.count('-o "$script"'), 2)


if __name__ == "__main__":
    unittest.main()
