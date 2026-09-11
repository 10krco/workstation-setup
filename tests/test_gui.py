"""Run with TENKR_GUI_TEST=1 under an isolated Xvfb display."""
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("TENKR_GUI_TEST") == "1", "requires isolated display")
class GuiTest(unittest.TestCase):
    def test_absent_reader_is_optional_without_claiming_enrollment_and_guidance_returns(self):
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ["GTK_A11Y"] = "none"
        from tenkr_workstation_setup.app import SetupApplication, SetupWindow
        from tenkr_workstation_setup.probes import ProbeResult
        from tenkr_workstation_setup.state import STEPS
        app = SetupApplication()
        app.set_application_id("com.tenkr.WorkstationSetup.GuidanceTest")
        app.register(None)
        with patch("tenkr_workstation_setup.app.threading.Thread.start"):
            window = SetupWindow(app)
            results = {step.key: ProbeResult(True, "Complete") for step in STEPS}
            results["fingerprint"] = ProbeResult(False, "No reader", required=False)
            with patch.object(window.state, "mark_complete") as mark:
                window._apply_probes(window._probe_generation, results, False)
                self.assertTrue(window.finish_button.get_sensitive())
                self.assertFalse(window.rows["fingerprint"].get_activatable_widget().get_sensitive())
                self.assertNotIn("fingerprint", [call.args[0].key for call in mark.call_args_list])
            results["onepassword"] = ProbeResult(False, "Integration disabled")
            window._apply_probes(window._probe_generation, results, False)
            self.assertFalse(window.finish_button.get_sensitive())
            window._show_guide("Connect", [("Step <one>", "Literal <instructions> & status")])
            self.assertIsNotNone(window._guide)
            with patch.object(window, "_refresh") as refresh:
                window._return_from_app()
                refresh.assert_called_once()
            self.assertIsNone(window._guide)
            window.close()

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
                                window._chrome_dialog, window._connectivity_dialog, window._keyring_dialog,
                                window._onepassword_dialog):
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
            window._github_busy = False
            with patch("tenkr_workstation_setup.app.github_login", return_value=True), patch(
                "tenkr_workstation_setup.app.configure_ssh", side_effect=KeyError("login")
            ), patch("tenkr_workstation_setup.app.threading.Thread") as thread:
                window._github_setup("Test")
                thread.call_args.kwargs["target"]()
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            self.assertFalse(window._github_busy)
            self.assertIn("stopped unexpectedly", window.get_visible_dialog().get_body())
            window.get_visible_dialog().force_close()
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
