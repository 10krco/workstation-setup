import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.network import connect, prepare, verify_enrollment, enable_remote


class NetworkTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.network.command")
    def test_wrong_tailnet_is_rejected(self, command):
        for name, expected in (("personal.example", False), ("work.example", True)):
            command.side_effect = [json.dumps({"BackendState": "Running", "CurrentTailnet": {"Name": name}}),
                                   json.dumps({"OperatorUser": "", "RunSSH": False})]
            self.assertEqual(verify_enrollment("tailscale", "work.example"), expected)

    @patch("tenkr_workstation_setup.network.command")
    def test_unconfigured_user_cannot_acquire_operator_access(self, command):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PermissionError):
                prepare("alice", "tailscale", Path(directory))
        command.assert_not_called()

    @patch("tenkr_workstation_setup.network.subprocess.run", return_value=Mock(returncode=1))
    @patch("tenkr_workstation_setup.network.command")
    def test_preparation_withholds_operator_and_ssh(self, command, run):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ("managed-users", "password-set"):
                (root / kind).mkdir()
                (root / kind / "alice").touch()
            command.side_effect = ["", json.dumps({"OperatorUser": "", "RunSSH": False})]
            prepare("alice", "tailscale", root)
            self.assertEqual(command.call_args_list[0].args,
                             ("tailscale", "set", "--operator=", "--ssh=false"))
            self.assertEqual(run.call_args.args[0], ["tailscale", "up", "--timeout=2s"])

    @patch("tenkr_workstation_setup.network.command")
    def test_running_network_alone_is_insufficient(self, command):
        command.side_effect = [json.dumps({"BackendState": "Running"}),
                               json.dumps({"RunSSH": False})]
        self.assertFalse(verify_enrollment("tailscale", "work.example"))

    @patch("tenkr_workstation_setup.network.command")
    def test_remote_enablement_is_verified(self, command):
        command.side_effect = ["", json.dumps({"OperatorUser": "alice", "RunSSH": True})]
        enable_remote("alice", "tailscale")
        self.assertEqual(command.call_args_list[0].args,
                         ("tailscale", "set", "--operator=alice", "--ssh=true"))
        command.side_effect = ["", json.dumps({"OperatorUser": "", "RunSSH": False})]
        with self.assertRaises(RuntimeError):
            enable_remote("alice", "tailscale")

    @patch("tenkr_workstation_setup.network.command")
    def test_remote_privileges_are_only_expected_after_completion(self, command):
        status = json.dumps({"BackendState": "Running", "CurrentTailnet": {"Name": "work.example"}})
        prefs = json.dumps({"OperatorUser": "alice", "RunSSH": True})
        command.side_effect = [status, prefs]
        self.assertFalse(verify_enrollment("tailscale", "work.example"))
        command.side_effect = [status, prefs]
        self.assertTrue(verify_enrollment("tailscale", "work.example", operator="alice"))

    @patch("tenkr_workstation_setup.network.subprocess.run", return_value=Mock(returncode=1))
    @patch("tenkr_workstation_setup.network.command")
    def test_untrusted_auth_url_is_never_opened(self, command, _run):
        command.return_value = json.dumps({"BackendState": "NeedsLogin", "AuthURL": "https://example.com/login"})
        browser = Mock()
        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            connect(threading.Event(), browser, Mock())
        browser.assert_not_called()

    @patch("tenkr_workstation_setup.network.subprocess.run", return_value=Mock(returncode=1))
    @patch("tenkr_workstation_setup.network.command")
    def test_browser_handoff_and_cancellation(self, command, _run):
        command.return_value = json.dumps({"BackendState": "NeedsLogin", "AuthURL": "https://login.tailscale.com/a/test"})
        cancel = threading.Event()
        browser = Mock(side_effect=lambda _: cancel.set())
        self.assertFalse(connect(cancel, browser, Mock()))
        browser.assert_called_once_with("https://login.tailscale.com/a/test")
