from __future__ import annotations

import subprocess
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .probes import probe
from .state import EnrollmentState, STEPS, Step
from .fingerprint import Reader, enroll
from .personalization import resolve as resolve_home, activate as activate_home
from .network import connect as connect_network
from .github_auth import login as github_login
from .ssh_setup import configure as configure_ssh
from .identity import git_identity
from .chrome_pipe import ChromePipe
from .chrome_setup import profile_path, record as record_chrome


class SetupWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="10kR Workstation Setup")
        self.set_default_size(760, 680)
        self.fullscreen()
        self.state = EnrollmentState()
        self.rows: dict[str, Adw.ActionRow] = {}
        self._probe_generation = 0
        self._fingerprint_cancel = None
        self._home_busy = False
        self._network_cancel = None
        self._github_busy = False
        self._chrome_busy = False
        self._chrome = None

        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Set up your 10kR workstation", subtitle="Progress is saved automatically")
        header.set_title_widget(title)

        self.group = Adw.PreferencesGroup(
            title="First-login checklist",
            description="Complete the required steps before using the workstation.",
        )
        for step in STEPS:
            row = Adw.ActionRow(title=step.title, subtitle=step.description)
            button = Gtk.Button(
                label="Open" if step.key in {"password", "fingerprint", "onepassword"} else "Details",
                valign=Gtk.Align.CENTER,
            )
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

    def _refresh(self, finish_after_refresh: bool = False) -> None:
        self._probe_generation += 1
        generation = self._probe_generation
        self.finish_button.set_sensitive(False)
        thread = threading.Thread(
            target=self._collect_probes,
            args=(generation, finish_after_refresh),
            daemon=True,
        )
        thread.start()

    def _collect_probes(self, generation: int, finish_after_refresh: bool) -> None:
        results = {step.key: probe(step) for step in STEPS}
        GLib.idle_add(self._apply_probes, generation, results, finish_after_refresh)

    def _apply_probes(self, generation: int, results: dict, finish_after_refresh: bool) -> bool:
        if generation != self._probe_generation:
            return GLib.SOURCE_REMOVE

        for step in STEPS:
            result = results[step.key]
            complete = result.complete
            if complete:
                self.state.mark_complete(step)
            self.rows[step.key].set_subtitle(result.detail)
            self.rows[step.key].set_icon_name(
                "emblem-ok-symbolic" if complete else "preferences-system-symbolic"
            )
        required_complete = all(results[step.key].complete for step in STEPS if step.required)
        self.finish_button.set_sensitive(required_complete)

        if finish_after_refresh:
            if not required_complete:
                missing = [step.title for step in STEPS if step.required and not results[step.key].complete]
                self._message("Setup is not finished", f"Required setup remains: {', '.join(missing)}")
            else:
                self.state.finish()
                self.close()

        return GLib.SOURCE_REMOVE

    def _run_step(self, _button: Gtk.Button, step: Step) -> None:
        if step.key == "password":
            self._password_dialog()
            return
        if step.key == "fingerprint":
            self._fingerprint_dialog()
            return
        if step.key == "home-manager":
            self._home_dialog()
            return
        if step.key == "tailscale":
            self._network_dialog()
            return
        if step.key == "github":
            self._github_dialog()
            return
        if step.key == "chrome":
            self._chrome_dialog()
            return
        if step.key == "connectivity":
            self._connectivity_dialog()
            return
        actions = {
            "onepassword": ["1password"],
        }
        command = actions.get(step.key)
        if command:
            try:
                subprocess.Popen(command, start_new_session=True)
            except OSError as error:
                self._message("Could not open setup", str(error))
                return
            GLib.timeout_add_seconds(2, self._refresh_after_action)
            return

        descriptions = {
            "github": "GitHub and SSH-key enrollment will be connected to this page next.",
            "keyring": "GNOME Keyring enrollment will be connected to this page next.",
            "tailscale": "Tailscale enrollment will be connected to this page next.",
            "home-manager": "Home Manager remote selection will be connected to this page next.",
        }
        self._message(step.title, descriptions[step.key])

    def _connectivity_dialog(self):
        dialog = Adw.AlertDialog(heading="Connect to the internet",
            body="Connect an Ethernet cable or open Wi-Fi settings to select your network. Return here after connecting and check the connection.")
        dialog.add_response("close", "Close")
        dialog.add_response("wifi", "Open Wi-Fi settings")
        dialog.add_response("check", "Check connection")
        def response(_dialog, choice):
            if choice == "wifi":
                try:
                    subprocess.Popen(["gnome-control-center", "wifi"],
                        env=dict(os.environ, XDG_CURRENT_DESKTOP="GNOME"),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True)
                except OSError:
                    self._message("Network settings unavailable", "GNOME network settings could not start. Connect Ethernet or retry.")
            elif choice == "check":
                self._refresh()
        dialog.connect("response", response)
        dialog.present(self)

    def _chrome_dialog(self):
        if self._chrome_busy:
            return
        try:
            _, email = git_identity()
        except RuntimeError as error:
            self._message("Work identity is missing", str(error))
            return
        dialog = Adw.AlertDialog(heading="Connect your work browser",
            body=f"Open the work browser and sign in to Chrome using {email}. Enable sync for all available categories, then return here and verify. Google may ask you to approve your organization’s profile policies.")
        dialog.add_response("close", "Close")
        dialog.add_response("open", "Open work browser")
        dialog.add_response("verify", "Verify account and sync")

        def response(_dialog, choice):
            if choice not in {"open", "verify"}:
                return
            self._chrome_busy = True
            def work():
                try:
                    if self._chrome is None or self._chrome.process.poll() is not None:
                        if self._chrome is not None:
                            self._chrome.close()
                        self._chrome = ChromePipe(profile_path())
                        self._chrome.call("Browser.getVersion")
                    if choice == "verify":
                        record_chrome(self._chrome)
                        self._chrome.close()
                        self._chrome = None
                        message = "Your work account and sync settings are verified. Open 10kR Work Browser from the application launcher after setup."
                    else:
                        message = f"Sign in to Chrome with {email}, enable all sync categories, then return and choose Verify account and sync."
                except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
                    message = str(error)
                GLib.idle_add(done, message)
            def done(message):
                self._chrome_busy = False
                self._message("Work browser", message)
                self._refresh()
                return GLib.SOURCE_REMOVE
            threading.Thread(target=work, daemon=True).start()
        dialog.connect("response", response)
        dialog.present(self)

    def _github_dialog(self):
        if self._github_busy:
            return
        try:
            git_name, git_email = git_identity()
        except RuntimeError as error:
            self._message("Work identity is missing", str(error))
            return
        dialog = Adw.AlertDialog(heading="Connect GitHub and SSH",
                                 body=f"Git identity: {git_name}\n{git_email}\n\nFirst sign in to 1Password and enable its CLI integration and SSH agent. Choose the vault for your keys.")
        group = Adw.PreferencesGroup()
        group.add(Gtk.LinkButton(uri="https://github.com/settings/emails", label="Verify your work email on GitHub"))
        fields = [Adw.EntryRow(title="1Password vault")]
        for field in fields:
            group.add(field)
        dialog.set_extra_child(group)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("start", "Connect and configure")

        def response(_dialog, choice):
            if choice != "start":
                return
            vault = fields[0].get_text().strip()
            if not vault:
                self._message("Details needed", "Enter a 1Password vault.")
                return
            self._github_setup(vault)

        dialog.connect("response", response)
        dialog.present(self)

    def _github_setup(self, vault):
        self._github_busy = True
        cancel = threading.Event()
        status = Adw.AlertDialog(heading="Connect GitHub", body="Checking GitHub access…")
        link = Gtk.LinkButton(uri="https://github.com/login/device", label="Open GitHub sign-in")
        status.set_extra_child(link)
        status.add_response("close", "Cancel")
        status.connect("response", lambda *_: cancel.set())
        status.present(self)

        def code(value):
            if not cancel.is_set():
                status.set_body(f"Enter this code at GitHub and authorize workstation setup:\n\n{value}")
                Gio.AppInfo.launch_default_for_uri_async("https://github.com/login/device", None, None, None)
            return GLib.SOURCE_REMOVE

        def configuring():
            status.set_body("Configuring 1Password keys, GitHub registrations, and Git signing. Closing this dialog does not cancel these operations.")
            status.set_response_label("close", "Close")
            return GLib.SOURCE_REMOVE

        def done(message):
            self._github_busy = False
            if not cancel.is_set():
                status.set_body(message)
                status.set_response_label("close", "Close")
            self._refresh()
            return GLib.SOURCE_REMOVE

        def work():
            try:
                if not github_login(cancel, lambda value: GLib.idle_add(code, value)) or cancel.is_set():
                    GLib.idle_add(done, "Sign-in canceled.")
                    return
                GLib.idle_add(configuring)
                configure_ssh(vault)
                message = "GitHub keys and Git signing are configured."
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                message = str(error)
            GLib.idle_add(done, message)

        threading.Thread(target=work, daemon=True).start()

    def _network_dialog(self):
        if self._network_cancel is not None:
            return
        cancel = threading.Event()
        self._network_cancel = cancel
        dialog = Adw.AlertDialog(heading="Join your workstation network", body="Preparing Tailscale…")
        link = Gtk.LinkButton(uri="https://login.tailscale.com", label="Open Tailscale sign-in")
        link.set_sensitive(False)
        dialog.set_extra_child(link)
        dialog.add_response("close", "Cancel")
        dialog.connect("response", lambda *_: cancel.set())
        dialog.present(self)

        def progress(message):
            if not cancel.is_set():
                dialog.set_body(message)
            return GLib.SOURCE_REMOVE

        def browser(url):
            if not cancel.is_set():
                link.set_uri(url)
                link.set_sensitive(True)
                Gio.AppInfo.launch_default_for_uri_async(url, None, None, None)
            return GLib.SOURCE_REMOVE

        def finished(message):
            progress(message)
            dialog.set_response_label("close", "Close")
            self._network_cancel = None
            self._refresh()
            return GLib.SOURCE_REMOVE

        def work():
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                bus.call_sync("com.tenkr.WorkstationSetup", "/com/tenkr/WorkstationSetup",
                              "com.tenkr.WorkstationSetup", "PrepareNetwork", None, None,
                              Gio.DBusCallFlags.NONE, 45000, None)
                complete = connect_network(cancel, lambda url: GLib.idle_add(browser, url),
                                           lambda message: GLib.idle_add(progress, message))
                message = "Tailscale is connected and SSH is enabled." if complete else "Setup canceled."
            except (GLib.Error, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                message = str(error)
            GLib.idle_add(finished, message)

        threading.Thread(target=work, daemon=True).start()

    def _home_dialog(self) -> None:
        if self._home_busy:
            self._message("Home Manager is busy", "Wait for the current configuration operation to finish.")
            return
        dialog = Adw.AlertDialog(heading="Personalize your environment",
                                 body="Optional: use your Home Manager configuration from GitHub. Only select a repository you trust.")
        entry = Adw.EntryRow(title="github:OWNER/REPOSITORY#OUTPUT")
        group = Adw.PreferencesGroup()
        group.add(entry)
        dialog.set_extra_child(group)
        dialog.add_response("skip", "Skip")
        dialog.add_response("preview", "Review configuration")

        def response(_dialog, choice):
            if choice == "preview":
                value = entry.get_text()
                self._home_operation(lambda: resolve_home(value), self._home_preview,
                                     "Preparing your configuration. This may take a few minutes.")

        dialog.connect("response", response)
        dialog.present(self)

    def _home_operation(self, operation, success, message):
        if self._home_busy:
            return
        self._home_busy = True
        status = Adw.AlertDialog(heading="Home Manager", body=message)
        status.add_response("close", "Close")
        status.present(self)

        def finish(result, error):
            self._home_busy = False
            status.close()
            if error:
                self._message("Configuration not applied", error)
            else:
                success(result)
            return GLib.SOURCE_REMOVE

        def work():
            try:
                result = operation()
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                GLib.idle_add(finish, None, str(error))
            else:
                GLib.idle_add(finish, result, None)

        threading.Thread(target=work, daemon=True).start()

    def _home_preview(self, remote):
        dialog = Adw.AlertDialog(heading="Apply this configuration?",
                                 body=f"The configuration built successfully.\n\nSource: {remote.source}\nOutput: {remote.output}\n\nApplying it may change your shell, applications, and desktop settings.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("activate", "Apply configuration")

        def response(_dialog, choice):
            if choice == "activate":
                self._home_operation(lambda: activate_home(remote), lambda _: self._refresh(),
                                     "Applying the reviewed GitHub revision…")

        dialog.connect("response", response)
        dialog.present(self)

    def _fingerprint_dialog(self) -> None:
        if self._fingerprint_cancel is not None:
            return
        cancel = threading.Event()
        self._fingerprint_cancel = cancel
        dialog = Adw.AlertDialog(heading="Enroll your right index finger", body="Connecting to the reader…")
        dialog.add_response("close", "Cancel")
        dialog.connect("response", lambda *_: cancel.set())
        dialog.present(self)

        def update(message):
            if not cancel.is_set():
                dialog.set_body(message)
            return GLib.SOURCE_REMOVE

        def done(message):
            update(message)
            dialog.set_response_label("close", "Close")
            self._fingerprint_cancel = None
            self._refresh()
            return GLib.SOURCE_REMOVE

        def run():
            try:
                success = enroll(Reader(), cancel, lambda message: GLib.idle_add(update, message))
                message = "Your fingerprint is enrolled." if success else "Enrollment canceled."
            except (GLib.Error, RuntimeError) as error:
                message = str(error)
            GLib.idle_add(done, message)

        threading.Thread(target=run, daemon=True).start()

    def _password_dialog(self) -> None:
        dialog = Adw.AlertDialog(heading="Choose your password",
                                 body="Enter your supplied password and choose a new password of at least 12 characters.")
        group = Adw.PreferencesGroup()
        current = Adw.PasswordEntryRow(title="Supplied password")
        replacement = Adw.PasswordEntryRow(title="New password")
        confirmation = Adw.PasswordEntryRow(title="Confirm new password")
        for row in (current, replacement, confirmation):
            group.add(row)
        dialog.set_extra_child(group)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Set password")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, choice):
            old, new, confirm = current.get_text(), replacement.get_text(), confirmation.get_text()
            for row in (current, replacement, confirmation):
                row.set_text("")
            if choice != "save":
                return
            if new != confirm or len(new) < 12:
                self._message("Password not changed", "The passwords must match and contain at least 12 characters.")
                return
            threading.Thread(target=self._set_password, args=(old, new), daemon=True).start()

        dialog.connect("response", response)
        dialog.present(self)

    def _set_password(self, current: str, replacement: str) -> None:
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            bus.call_sync("com.tenkr.WorkstationSetup", "/com/tenkr/WorkstationSetup",
                          "com.tenkr.WorkstationSetup", "SetPassword",
                          GLib.Variant("(ss)", (current, replacement)), None,
                          Gio.DBusCallFlags.NONE, 45000, None)
        except GLib.Error as error:
            GLib.idle_add(self._message, "Password not changed", str(error))
        finally:
            GLib.idle_add(self._refresh)

    def _refresh_after_action(self) -> bool:
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _message(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("close", "Close")
        dialog.present(self)

    def _finish(self, _button: Gtk.Button) -> None:
        self._refresh(finish_after_refresh=True)


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
