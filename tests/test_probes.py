from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.probes import ProbeResult, fingerprint, github, keyring


class OnePasswordIntegrationTest(unittest.TestCase):
    def test_completion_requires_agent_response_and_cli_success_without_output(self):
        import subprocess
        from tenkr_workstation_setup.probes import onepassword
        with patch("pathlib.Path.is_socket", return_value=True), \
             patch("tenkr_workstation_setup.probes._agent_responds", return_value=False) as agent, \
             patch("tenkr_workstation_setup.probes.subprocess.run") as run:
            self.assertFalse(onepassword().complete)
            run.assert_not_called()
            agent.return_value = True
            run.return_value.returncode = 1
            self.assertFalse(onepassword().complete)
            run.return_value.returncode = 0
            self.assertTrue(onepassword().complete)
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_agent_handshake_rejects_stale_socket_and_protocol_failure(self):
        import struct
        from tenkr_workstation_setup.probes import _agent_responds
        with patch("tenkr_workstation_setup.probes.socket.socket") as factory:
            connection = factory.return_value.__enter__.return_value
            connection.recv.side_effect = [b"\0\0", b"\0\x05\x0c\0\0\0\0"]
            self.assertTrue(_agent_responds(Path("/agent.sock")))
            connection.recv.side_effect = [struct.pack(">IBI", 5, 5, 0)]
            self.assertFalse(_agent_responds(Path("/agent.sock")))
            connection.connect.side_effect = ConnectionRefusedError()
            self.assertFalse(_agent_responds(Path("/agent.sock")))


class ProbeTest(unittest.TestCase):
    def test_fingerprint_is_optional_only_when_device_enumeration_succeeds_empty(self):
        from gi.repository import GLib
        with patch("tenkr_workstation_setup.fingerprint.available_devices", return_value=[]) as devices:
            result = fingerprint()
            self.assertIs(result.required, False)
            self.assertFalse(result.complete)
            devices.side_effect = GLib.Error("Device enumeration failed")
            result = fingerprint()
            self.assertIsNone(result.required)
            self.assertFalse(result.complete)

    def test_usable_fingerprint_reader_still_requires_enrollment(self):
        with patch("tenkr_workstation_setup.fingerprint.available_devices", return_value=["/reader"]), \
             patch("tenkr_workstation_setup.fingerprint.enrolled_fingers", return_value=[]) as fingers:
            self.assertFalse(fingerprint().complete)
            self.assertIsNone(fingerprint().required)
            fingers.return_value = ["right-index-finger"]
            self.assertTrue(fingerprint().complete)

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
