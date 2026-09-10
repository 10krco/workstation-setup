"""Run with TENKR_GUI_TEST=1 under an isolated Xvfb display."""
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("TENKR_GUI_TEST") == "1", "requires isolated display")
class GuiTest(unittest.TestCase):
    def test_window_and_setup_dialogs_construct_without_external_actions(self):
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ["GTK_A11Y"] = "none"
        os.environ["GIO_USE_VFS"] = "local"
        from tenkr_workstation_setup.app import SetupApplication, SetupWindow
        from gi.repository import GLib
        app = SetupApplication()
        app.register(None)
        # These are presentation tests; real credentials and hardware are never touched.
        with patch("tenkr_workstation_setup.app.threading.Thread.start") as start, patch(
            "tenkr_workstation_setup.app.git_identity", return_value=("Alice Example (Engineer)", "alice@10kr.co")
        ):
            window = SetupWindow(app)
            window.present()
            for open_dialog in (window._password_dialog, window._home_dialog,
                                window._fingerprint_dialog, window._network_dialog, window._github_dialog,
                                window._chrome_dialog, window._connectivity_dialog, window._keyring_dialog):
                open_dialog()
                dialog = window.get_visible_dialog()
                self.assertIsNotNone(dialog)
                dialog.force_close()
                while GLib.MainContext.default().pending():
                    GLib.MainContext.default().iteration(False)
            start.reset_mock()
            window._github_setup("Test")
            status = window.get_visible_dialog()
            self.assertIsNotNone(status)
            window._github_setup("Another vault")
            start.assert_called_once()
            self.assertIs(window.get_visible_dialog(), status)
            status.force_close()
            window.close()
