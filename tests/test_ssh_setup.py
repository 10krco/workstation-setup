import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tenkr_workstation_setup.ssh_setup import ensure_item, register, verify_signing


class SshSetupTest(unittest.TestCase):
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
