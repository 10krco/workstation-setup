from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.probes import ProbeResult, github, keyring


class ProbeTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.probes._run", return_value=Mock(returncode=0))
    @patch("tenkr_workstation_setup.ssh_setup.signing_configuration", return_value={"user.name": "Alice (Engineer)"})
    def test_github_requires_successful_signing_with_current_settings(self, config, _run):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)):
            home = Path(directory)
            (home / ".ssh").mkdir()
            for filename in ("tenkr-github-authentication.pub", "tenkr-git-signing.pub"):
                (home / ".ssh" / filename).write_text("ssh-ed25519 AAAA\n")
            self.assertFalse(github().complete)
            receipt = home / ".config/10kr/workstation-setup/signing-verification.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"key": "ssh-ed25519 AAAA", "settings": config.return_value}))
            self.assertTrue(github().complete)
            config.return_value = {"user.name": "Changed identity"}
            self.assertFalse(github().complete)

    @patch("tenkr_workstation_setup.probes._run", return_value=Mock(stdout="LoadState=loaded\nResult=success\n"))
    def test_keyring_requires_a_verified_reference_and_unlock_service(self, run) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)):
            self.assertEqual(
                keyring(),
                ProbeResult(False, "The login keyring has not been enrolled with 1Password."),
            )

            reference = Path(directory) / ".config" / "10kr" / "gnome-keyring-1password-secret-reference"
            reference.parent.mkdir(parents=True)
            reference.write_text("op://Personal/example/password\n")
            self.assertFalse(keyring().complete)
            receipt = Path(directory) / ".config/10kr/workstation-setup/keyring-verification.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"reference": "op://Personal/example/password"}))
            self.assertTrue(keyring().complete)
            run.return_value.stdout = "LoadState=not-found\n"
            self.assertFalse(keyring().complete)

    def test_keyring_treats_an_unreadable_reference_as_incomplete(self) -> None:
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", side_effect=OSError("unreadable")
        ):
            self.assertFalse(keyring().complete)


if __name__ == "__main__":
    unittest.main()
