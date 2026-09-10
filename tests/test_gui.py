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
        with patch("tenkr_workstation_setup.app.threading.Thread.start"), patch(
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
            window.close()

    def test_only_privileged_success_closes_setup(self):
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ["GTK_A11Y"] = "none"
        os.environ["GIO_USE_VFS"] = "local"
        from tenkr_workstation_setup.app import SetupApplication, SetupWindow
        app = SetupApplication()
        app.set_application_id("com.tenkr.WorkstationSetup.CompletionTest")
        app.register(None)
        with patch("tenkr_workstation_setup.app.threading.Thread.start"):
            window = SetupWindow(app)
            with patch.object(window, "close") as close, patch.object(window, "_message"), \
                 patch.object(window, "_refresh"):
                window._completion_result(["github"], None)
                close.assert_not_called()
                window._completion_result([], "Service unavailable")
                close.assert_not_called()
                window._completion_result([], None)
                close.assert_called_once()
            window.close()
