import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.ssh_setup import ensure_item, register, verify_signing
from tenkr_workstation_setup.ssh_setup import verify_authentication, verify_email
from tenkr_workstation_setup.ssh_setup import command as real_command, configure, write_config
from tenkr_workstation_setup.ssh_setup import managed_ssh_config
from tenkr_workstation_setup.ssh_setup import signing_configuration


class SshSetupTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.ssh_setup.git_identity", return_value=("Alice (Engineer)", "alice@10kr.co"))
    @patch("tenkr_workstation_setup.ssh_setup.shutil.which", return_value=None)
    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_missing_signer_fails_and_probe_timeout_is_forwarded(self, command, _which, _identity):
        values = {"user.name": "Alice (Engineer)", "user.email": "alice@10kr.co", "gpg.format": "ssh",
                  "commit.gpgsign": "true", "tag.gpgsign": "true", "user.signingkey": "/key.pub",
                  "gpg.ssh.program": "/removed/op-ssh-sign"}
        command.side_effect = lambda *args, **kwargs: values[args[-1]]
        with self.assertRaises(RuntimeError):
            signing_configuration(timeout=1)
        self.assertTrue(all(call.kwargs["timeout"] == 1 for call in command.call_args_list))

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_work_email_must_be_verified_on_github(self, command):
        for records in ([], [{"email": "alice@10kr.co", "verified": False}],
                        [{"email": "other@10kr.co", "verified": True}]):
            command.return_value = json.dumps([records])
            with self.assertRaises(RuntimeError):
                verify_email("alice@10kr.co")
        command.return_value = json.dumps([[{"email": "alice@10kr.co", "verified": True}]])
        verify_email("alice@10kr.co")

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_existing_item_is_reused_and_only_public_field_requested(self, command):
        command.side_effect = [json.dumps([{"id": "abc123", "title": "key"}]), "ssh-ed25519 AAAA comment"]
        self.assertEqual(ensure_item("Personal", "key"), ("abc123", "ssh-ed25519 AAAA"))
        self.assertEqual(command.call_args.args, ("op", "read", "op://Personal/abc123/public_key"))
        self.assertFalse(any("create" in call.args for call in command.call_args_list))

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_new_item_response_is_discarded(self, command):
        command.side_effect = ["[]", None, json.dumps([{"id": "abc123", "title": "key"}]), "ssh-ed25519 AAAA"]
        ensure_item("Personal", "key")
        self.assertTrue(command.call_args_list[1].kwargs["discard"])

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_ambiguous_titles_do_not_create_another_item(self, command):
        command.return_value = json.dumps([{"id": "a", "title": "key"}, {"id": "b", "title": "key"}])
        with self.assertRaises(RuntimeError):
            ensure_item("Personal", "key")
        self.assertEqual(command.call_count, 1)

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_existing_github_key_is_not_uploaded_again(self, command):
        command.return_value = json.dumps([[{"key": "ssh-ed25519 AAAA comment"}]])
        register("ssh-ed25519 AAAA", "signing", "title")
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[-1], "user/ssh_signing_keys")

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_uploaded_key_is_read_back(self, command):
        command.side_effect = ["[[]]", "{}", json.dumps([[{"key": "ssh-ed25519 AAAA"}]])]
        register("ssh-ed25519 AAAA", "authentication", "title")
        self.assertEqual(command.call_count, 3)


class AuthenticationTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.ssh_setup.ssh_identity_locations", return_value="/tmp/alice/.ssh/config:9: IdentityFile unrelated.pub")
    @patch("tenkr_workstation_setup.ssh_setup.subprocess.run")
    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_exact_account_and_strict_host_verification_required(self, command, run, locations):
        home = Path("/tmp/alice")
        effective = ("hostname github.com\nidentitiesonly yes\n"
                     "identityagent /tmp/alice/.1password/agent.sock\n"
                     "identityfile /tmp/alice/.ssh/tenkr-github-authentication.pub\n")
        def commands(*args):
            return effective if args[0] == "ssh" else json.dumps({"ssh_keys": ["ssh-ed25519 AAAA"]})
        command.side_effect = commands
        def authenticate(args, **kwargs):
            self.assertIn("StrictHostKeyChecking=yes", args)
            path = next(arg.split("=", 1)[1] for arg in args if arg.startswith("UserKnownHostsFile="))
            self.assertEqual(Path(path).read_text(), "github.com ssh-ed25519 AAAA\n")
            return subprocess.CompletedProcess(args, 1, "", "Hi alice! You've successfully authenticated, but GitHub does not provide shell access.\n")
        run.side_effect = authenticate
        verify_authentication("alice", home)
        with self.assertRaises(RuntimeError):
            verify_authentication("other-account", home)
        effective += "identityfile /tmp/alice/.ssh/unrelated.pub\n"
        run.reset_mock()
        with self.assertRaises(RuntimeError):
            verify_authentication("alice", home)
        run.assert_not_called()
        locations.assert_called_once_with(home)


class SigningIntegrationTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.ssh_setup.git_identity", return_value=("Alice Example (Engineer)", "alice@10kr.co"))
    def test_real_signature_verified_and_wrong_key_rejected(self, _identity):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            # Isolate every Git configuration source from the actual workstation.
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith("GIT_")}
            environment.update(HOME=directory, XDG_CONFIG_HOME=directory,
                               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(home / "gitconfig"))
            with patch.dict(os.environ, environment, clear=True):
                for filename in ("signer", "other"):
                    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                                    "-f", str(home / filename)], check=True, capture_output=True)
                for setting, value in (("user.name", "Alice Example (Engineer)"),
                                       ("user.email", "alice@10kr.co"), ("gpg.format", "ssh"),
                                       ("gpg.ssh.program", "ssh-keygen"),
                                       ("user.signingkey", str(home / "signer")),
                                       ("commit.gpgsign", "true"), ("tag.gpgsign", "true")):
                    subprocess.run(["git", "config", "--global", setting, value], check=True)
                verify_signing((home / "signer.pub").read_text().strip())
                with self.assertRaises(RuntimeError):
                    verify_signing((home / "other.pub").read_text().strip())
                subprocess.run(["git", "config", "--global", "user.name", "Wrong identity"], check=True)
                with self.assertRaises(RuntimeError):
                    verify_signing((home / "signer.pub").read_text().strip())


class ConfigurationRetryTest(unittest.TestCase):
    def test_unbounded_legacy_block_preserves_personal_configuration_by_refusing(self):
        personal = "# 10kR 1Password SSH agent\nHost *\n  IdentityFile ~/.ssh/id_ed25519\n"
        for suffix in ("", "\nHost work\n  HostName work.example\n"):
            with self.assertRaises(RuntimeError):
                managed_ssh_config(personal + suffix)

    @patch("tenkr_workstation_setup.ssh_setup.subprocess.run", return_value=Mock(returncode=1))
    def test_failure_identifies_operation_without_cli_output(self, run):
        from tenkr_workstation_setup.ssh_setup import command
        run.return_value.stderr = "secret must not be shown"
        with self.assertRaisesRegex(RuntimeError, "op read failed") as error:
            command("op", "read", "op://vault/item/password")
        self.assertNotIn("secret", str(error.exception))

    def test_incomplete_managed_block_is_repaired_without_losing_personal_hosts(self):
        personal = "Host internal\n  HostName internal.example\n"
        old = "# 10kR 1Password SSH agent\nHost github.com\n\n" + personal
        fixed = managed_ssh_config(old)
        self.assertIn("IdentitiesOnly yes", fixed)
        self.assertTrue(fixed.endswith(personal))
        self.assertEqual(managed_ssh_config(fixed), fixed)
    @patch("tenkr_workstation_setup.ssh_setup.git_identity", return_value=("Alice Example (Engineer)", "alice@10kr.co"))
    @patch("tenkr_workstation_setup.ssh_setup.shutil.which", return_value="/example/op-ssh-sign")
    @patch("tenkr_workstation_setup.ssh_setup.verify_signing")
    @patch("tenkr_workstation_setup.ssh_setup.verify_authentication")
    @patch("tenkr_workstation_setup.ssh_setup.register")
    @patch("tenkr_workstation_setup.ssh_setup.ensure_item")
    def test_retry_preserves_existing_config_and_records_only_verified_success(self, item, register, authenticate, sign, _which, _identity):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            environment.update(HOME=directory, XDG_CONFIG_HOME=directory,
                               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(home / "gitconfig"))
            (home / ".ssh").mkdir()
            (home / ".ssh/config").write_text("Host internal\n  HostName internal.example\n")
            agent = home / ".config/1Password/ssh/agent.toml"
            agent.parent.mkdir(parents=True)
            agent.write_text('[[ssh-keys]]\nitem = "existing"\nvault = "Personal"\n')
            item.side_effect = lambda vault, title: ("auth", "ssh-ed25519 AAAA") if title.endswith("authentication") else ("sign", "ssh-ed25519 BBBB")
            authenticate.side_effect = [RuntimeError("Agent locked"), None, None]
            def commands(*args, **kwargs):
                if args[:2] == ("gh", "api"):
                    return json.dumps({"login": "alice"}) if args[-1] == "user" else json.dumps([[{"email": "alice@10kr.co", "verified": True}]])
                return real_command(*args, **kwargs)
            with patch.dict(os.environ, environment, clear=True), patch("tenkr_workstation_setup.ssh_setup.command", side_effect=commands):
                receipt = home / ".config/10kr/workstation-setup/signing-verification.json"
                with self.assertRaises(RuntimeError):
                    configure("Personal", home)
                self.assertFalse(receipt.exists())
                sign.assert_not_called()
                configure("Personal", home)
                self.assertTrue(receipt.exists())
                configure("Personal", home)
                self.assertEqual((home / ".ssh/config").read_text().count("# 10kR 1Password SSH agent"), 1)
                self.assertIn("Host internal", (home / ".ssh/config").read_text())
                self.assertEqual(len(tomllib.loads(agent.read_text())["ssh-keys"]), 3)
                self.assertEqual(real_command("git", "config", "--global", "user.email").strip(), "alice@10kr.co")
                self.assertEqual(agent.stat().st_mode & 0o777, 0o600)

    def test_managed_symlink_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.write_text("original")
            link = Path(directory) / "config"
            link.symlink_to(source)
            with self.assertRaises(RuntimeError):
                write_config(link, "new")
            self.assertTrue(link.is_symlink())
            self.assertEqual(source.read_text(), "original")
