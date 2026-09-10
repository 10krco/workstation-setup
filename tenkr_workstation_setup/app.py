from __future__ import annotations

import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .state import EnrollmentState, STEPS, Step


class SetupWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="10kR Workstation Setup")
        self.set_default_size(760, 680)
        self.state = EnrollmentState()
        self.rows: dict[str, Adw.ActionRow] = {}

        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Set up your 10kR workstation", subtitle="Progress is saved automatically")
        header.set_title_widget(title)

        self.group = Adw.PreferencesGroup(
            title="First-login checklist",
            description="Complete the required steps before using the workstation.",
        )
        for step in STEPS:
            row = Adw.ActionRow(title=step.title, subtitle=step.description)
            button = Gtk.Button(label="Set up", valign=Gtk.Align.CENTER)
            button.add_css_class("suggested-action")
            button.connect("clicked", self._run_step, step)
            row.add_suffix(button)
            row.set_activatable_widget(button)
            self.group.add(row)
            self.rows[step.key] = row

        self.finish_button = Gtk.Button(label="Finish setup", halign=Gtk.Align.END)
        self.finish_button.add_css_class("suggested-action")
        self.finish_button.connect("clicked", self._finish)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(header)
        page = Adw.PreferencesPage()
        page.add(self.group)
        finish_group = Adw.PreferencesGroup()
        finish_group.add(self.finish_button)
        page.add(finish_group)
        content.append(page)
        self.set_content(content)
        self._refresh()

    def _refresh(self) -> None:
        for step in STEPS:
            complete = self.state.is_complete(step)
            self.rows[step.key].set_icon_name(
                "emblem-ok-symbolic" if complete else "preferences-system-symbolic"
            )
        self.finish_button.set_sensitive(
            all(self.state.is_complete(step) for step in STEPS if step.required)
        )

    def _run_step(self, _button: Gtk.Button, step: Step) -> None:
        actions = {
            "password": ["gnome-control-center", "user-accounts"],
            "fingerprint": ["fprintd-enroll"],
            "onepassword": ["1password"],
        }
        command = actions.get(step.key)
        if command:
            try:
                subprocess.Popen(command, start_new_session=True)
            except OSError as error:
                self._message("Could not open setup", str(error))
                return
            self._confirm_completion(step)
            return

        descriptions = {
            "github": "GitHub and SSH-key enrollment will be connected to this page next.",
            "keyring": "GNOME Keyring enrollment will be connected to this page next.",
            "tailscale": "Tailscale enrollment will be connected to this page next.",
            "home-manager": "Home Manager remote selection will be connected to this page next.",
        }
        self._message(step.title, descriptions[step.key])

    def _confirm_completion(self, step: Step) -> None:
        dialog = Adw.AlertDialog(
            heading=step.title,
            body="Return here after completing the opened setup screen.",
        )
        dialog.add_response("later", "Not yet")
        dialog.add_response("complete", "Done")
        dialog.set_response_appearance("complete", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._completion_response, step)
        dialog.present(self)

    def _completion_response(self, _dialog: Adw.AlertDialog, response: str, step: Step) -> None:
        if response == "complete":
            self.state.mark_complete(step)
            self._refresh()

    def _message(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("close", "Close")
        dialog.present(self)

    def _finish(self, _button: Gtk.Button) -> None:
        try:
            self.state.finish()
        except ValueError as error:
            self._message("Setup is not finished", str(error))
            return
        self.close()


class SetupApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.tenkr.WorkstationSetup", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        window = self.props.active_window or SetupWindow(self)
        window.present()


def main() -> int:
    app = SetupApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
