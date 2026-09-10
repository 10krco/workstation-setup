import os
import tempfile
import unittest
from unittest.mock import patch

from tenkr_workstation_setup.chrome_pipe import ChromePipe
from tenkr_workstation_setup.chrome_setup import ABOUT_EXPRESSION, validate, verify


class ChromeValidationTest(unittest.TestCase):
    def setUp(self):
        self.about = {"Username": "alice@10kr.co", "Transport State": "Active",
                      "User Actionable Error": "None", "Setup In Progress": False,
                      "Auth Error": "OK since browser startup"}
        self.prefs = {"localSyncEnabled": False, "passphraseRequired": False,
                      "trustedVaultKeysRequired": False}
        for key in ("bookmarks", "preferences", "extensions", "tabs", "passwords"):
            self.prefs[key + "Registered"] = True
            self.prefs[key + "Synced"] = True

    def test_all_registered_types_are_required_even_when_sync_all_is_set(self):
        validate(self.about, self.prefs, "alice@10kr.co")
        self.prefs.update(syncAllDataTypes=True, passwordsSynced=False, passwordsManaged=True)
        with self.assertRaises(RuntimeError):
            validate(self.about, self.prefs, "alice@10kr.co")

    def test_wrong_account_and_paused_or_incomplete_setup_are_rejected(self):
        for key, value in (("Username", "personal@example.com"), ("Transport State", "Paused"),
                           ("Setup In Progress", True), ("User Actionable Error", "NeedsPassphrase"),
                           ("Auth Error", "Invalid credentials")):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate(dict(self.about, **{key: value}), self.prefs, "alice@10kr.co")

    def test_missing_data_and_encryption_prompts_are_not_success(self):
        for key in ("localSyncEnabled", "passphraseRequired", "trustedVaultKeysRequired"):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate(self.about, dict(self.prefs, **{key: True}), "alice@10kr.co")
        with self.assertRaises(RuntimeError):
            validate(self.about, {}, "alice@10kr.co")


@unittest.skipUnless(os.environ.get("TENKR_CHROME_TEST") == "1", "requires installed Google Chrome")
class ChromeRuntimeTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.chrome_setup.git_identity", return_value=("Alice (Engineer)", "alice@10kr.co"))
    def test_real_signed_out_browser_is_incomplete_and_private_pipe_closes(self, _identity):
        with tempfile.TemporaryDirectory() as profile:
            browser = ChromePipe(profile, extra_args=["--headless=new", "--disable-background-networking"])
            try:
                self.assertIn("Chrome/", browser.call("Browser.getVersion")["product"])
                target, session = browser.page("chrome://sync-internals")
                about = browser.evaluate(session, ABOUT_EXPRESSION)
                self.assertEqual(about["Username"], "")
                self.assertEqual(about["Transport State"], "Disabled")
                browser.call("Target.closeTarget", {"targetId": target})
                with self.assertRaises(RuntimeError):
                    verify(browser)
            finally:
                browser.close()
                browser.close()
            self.assertIsNotNone(browser.process.poll())
