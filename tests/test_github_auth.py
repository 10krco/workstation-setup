import threading
import os
import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.github_auth import authorized, device_code, login


class GithubAuthTest(unittest.TestCase):
    def test_only_device_code_is_extracted_from_cli_output(self):
        self.assertEqual(device_code("! First copy your one-time code: ABCD-1234\n"), "ABCD-1234")
        self.assertIsNone(device_code("unexpected response with private account data"))

    @patch("tenkr_workstation_setup.github_auth.subprocess.run")
    def test_read_endpoint_failure_is_rejected_after_scope_check(self, run):
        run.side_effect = [Mock(returncode=0, stdout="X-OAuth-Scopes: admin:public_key, admin:ssh_signing_key\n"), Mock(returncode=0), Mock(returncode=1)]
        self.assertFalse(authorized())
        self.assertEqual(run.call_count, 3)

    @patch("tenkr_workstation_setup.github_auth.subprocess.run")
    def test_read_only_scopes_do_not_skip_login_and_tokens_are_removed(self, run):
        run.return_value = Mock(returncode=0, stdout="X-OAuth-Scopes: read:public_key, read:ssh_signing_key\n")
        names = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
        with patch.dict(os.environ, {name: "test-token" for name in names}):
            self.assertFalse(authorized())
        for name in names:
            self.assertNotIn(name, run.call_args.kwargs["env"])

    @patch("tenkr_workstation_setup.github_auth.authorized")
    def test_canceled_flow_does_not_start_authentication(self, authorized):
        cancel = threading.Event()
        cancel.set()
        self.assertFalse(login(cancel, Mock()))
        authorized.assert_not_called()

    @patch("tenkr_workstation_setup.github_auth.subprocess.Popen")
    @patch("tenkr_workstation_setup.github_auth.authorized", return_value=True)
    def test_existing_authorization_does_not_require_new_login(self, _authorized, popen):
        self.assertTrue(login(threading.Event(), Mock()))
        popen.assert_not_called()
