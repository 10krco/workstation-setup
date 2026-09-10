import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tenkr_workstation_setup.password_backend import set_password


class PasswordEnrollmentTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "managed-users").mkdir()
        (self.root / "managed-users" / "alice").touch()
        self.authenticate = Mock(return_value=True)
        self.marker = self.root / "password-set" / "alice"

    def change(self, user="alice", replacement="a new long password"):
        set_password(user, "supplied", replacement, self.root, self.authenticate, "/test/chpasswd")

    @patch("tenkr_workstation_setup.password_backend.subprocess.run")
    def test_success_records_no_secret_and_prevents_second_change(self, run):
        run.return_value = subprocess.CompletedProcess([], 0)
        self.change()
        self.assertEqual(self.marker.read_text(), "1\n")
        self.authenticate.assert_called_once_with("alice", "supplied")
        self.assertEqual(run.call_args.args[0], ["/test/chpasswd"])
        self.assertEqual(run.call_args.kwargs["input"], "alice:a new long password\n")
        with self.assertRaises(PermissionError):
            self.change()
        self.assertEqual(run.call_count, 1)

    @patch("tenkr_workstation_setup.password_backend.subprocess.run")
    def test_failed_authentication_never_changes_password(self, run):
        self.authenticate.return_value = False
        with self.assertRaises(PermissionError):
            self.change()
        run.assert_not_called()
        self.assertFalse(self.marker.exists())

    @patch("tenkr_workstation_setup.password_backend.subprocess.run")
    def test_unmanaged_account_is_rejected(self, run):
        with self.assertRaises(PermissionError):
            self.change(user="bob")
        self.authenticate.assert_not_called()
        run.assert_not_called()

    @patch("tenkr_workstation_setup.password_backend.subprocess.run")
    def test_line_injection_is_rejected(self, run):
        with self.assertRaises(ValueError):
            self.change(replacement="long password\nroot:injected")
        run.assert_not_called()

    @patch("tenkr_workstation_setup.password_backend.subprocess.run")
    def test_system_failure_does_not_record_success(self, run):
        run.return_value = subprocess.CompletedProcess([], 1)
        with self.assertRaises(RuntimeError):
            self.change()
        self.assertFalse(self.marker.exists())
