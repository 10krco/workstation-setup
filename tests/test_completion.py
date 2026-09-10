import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.completion import complete
from tenkr_workstation_setup import verification


class CompletionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for directory in ("managed-users", "password-set"):
            (self.root / directory).mkdir()
            (self.root / directory / "alice").touch()
        self.user = Mock(return_value=[])
        self.system = Mock(return_value=[])
        self.active = Mock(return_value=True)
        self.activate = Mock()
        self.rollback = Mock()

    def finish(self):
        return complete("alice", self.user, self.system, self.active, self.root,
                        self.activate, self.rollback)

    def test_live_failures_and_inactive_session_never_publish_completion(self):
        self.user.return_value = ["github"]
        self.assertEqual(self.finish(), ["github"])
        self.user.return_value = []
        self.system.side_effect = [[], ["fingerprint"]]
        self.assertEqual(self.finish(), ["fingerprint"])
        self.system.side_effect = None
        self.active.return_value = False
        with self.assertRaises(PermissionError):
            self.finish()
        self.assertFalse((self.root / "completed/alice").exists())
        self.activate.assert_not_called()

    def test_failed_remote_enablement_rolls_back_and_does_not_publish(self):
        self.activate.side_effect = RuntimeError("failed enabling SSH")
        with self.assertRaises(RuntimeError):
            self.finish()
        self.rollback.assert_called_once()
        self.assertFalse((self.root / "completed/alice").exists())

    def test_marker_failure_revokes_remote_access(self):
        with patch("tenkr_workstation_setup.completion.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.finish()
        self.activate.assert_called_once()
        self.rollback.assert_called_once()
        self.assertFalse((self.root / "completed/alice").exists())

    def test_password_is_required_before_interactive_verification(self):
        (self.root / "password-set/alice").unlink()
        self.assertEqual(self.finish(), ["password"])
        self.user.assert_not_called()

    def test_all_checks_publish_atomically_and_repeat(self):
        self.assertEqual(self.finish(), [])
        marker = self.root / "completed/alice"
        self.assertEqual(marker.read_text(), "1\n")
        self.assertEqual(marker.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.finish(), [])
        self.assertEqual(list(marker.parent.iterdir()), [marker])

    def test_receipts_cannot_replace_fresh_checks(self):
        (self.root / "complete").touch()
        self.user.return_value = ["chrome", "keyring"]
        self.assertEqual(self.finish(), ["chrome", "keyring"])
        self.assertFalse((self.root / "completed/alice").exists())


class FreshVerificationTest(unittest.TestCase):
    def test_errors_are_reported_without_credentials_or_command_output(self):
        with patch.object(verification.connectivity, "connected", return_value=True), \
             patch.object(verification, "onepassword"), \
             patch.object(verification, "github", side_effect=RuntimeError("secret output")), \
             patch.object(verification, "keyring"), patch.object(verification, "chrome"):
            self.assertEqual(verification.verify(), ["github"])

    def test_signed_out_chrome_is_rejected_and_browser_is_closed(self):
        browser = Mock()
        with patch.object(verification, "ChromePipe", return_value=browser), \
             patch.object(verification.chrome_setup, "verify", side_effect=RuntimeError("signed out")):
            with self.assertRaises(RuntimeError):
                verification.chrome()
        browser.close.assert_called_once()
