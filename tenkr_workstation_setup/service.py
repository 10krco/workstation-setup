"""Narrow system D-Bus API for first-login password enrollment."""
import os
import pwd
import json
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import pam

from .password_backend import set_password
from .network import prepare
from .network import verify_enrollment, enable_remote, restrict
from .completion import complete, worker, published, recover

BUS_NAME = "com.tenkr.WorkstationSetup"
OBJECT_PATH = "/com/tenkr/WorkstationSetup"


class EnrollmentService(dbus.service.Object):
    def __init__(self, bus):
        self.bus = bus
        self.name = dbus.service.BusName(BUS_NAME, bus=bus)
        super().__init__(self.name, OBJECT_PATH)

    def recover_pending(self):
        for user in json.loads(os.environ["TENKR_MANAGED_USERS"]):
            try:
                recover(user, self.system_checks,
                        lambda: enable_remote(user, os.environ["TENKR_TAILSCALE"]),
                        lambda: restrict(os.environ["TENKR_TAILSCALE"]))
            except Exception:
                # Leave the durable journal for a later retry. No secrets or
                # raw subprocess output go to the service journal.
                print("Pending enrollment recovery needs a retry.", flush=True)

    def caller(self, sender):
        daemon = dbus.Interface(self.bus.get_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
        uid = int(daemon.GetConnectionUnixUser(sender))
        pid = int(daemon.GetConnectionUnixProcessID(sender))
        manager = dbus.Interface(self.bus.get_object(
            "org.freedesktop.login1", "/org/freedesktop/login1"), "org.freedesktop.login1.Manager")
        session = manager.GetSessionByPID(dbus.UInt32(pid))
        properties = dbus.Interface(self.bus.get_object(
            "org.freedesktop.login1", session), "org.freedesktop.DBus.Properties")
        values = properties.GetAll("org.freedesktop.login1.Session")
        if (uid == 0 or int(values["User"][0]) != uid or not values["Active"]
                or values["Remote"] or str(values["Type"]) != "wayland"):
            raise PermissionError("Password setup requires your active local desktop session.")
        return pwd.getpwuid(uid).pw_name

    def system_checks(self, user):
        missing = []
        try:
            manager = dbus.Interface(self.bus.get_object(
                "net.reactivated.Fprint", "/net/reactivated/Fprint/Manager"),
                "net.reactivated.Fprint.Manager")
            device = manager.GetDefaultDevice(timeout=15)
            fingers = dbus.Interface(self.bus.get_object("net.reactivated.Fprint", device),
                                     "net.reactivated.Fprint.Device").ListEnrolledFingers(user, timeout=15)
            if not fingers:
                missing.append("fingerprint")
        except dbus.DBusException:
            missing.append("fingerprint")
        try:
            executable = os.environ["TENKR_TAILSCALE"]
            expected = os.environ["TENKR_TAILNET"]
            if not verify_enrollment(executable, expected):
                missing.append("tailscale")
        except (OSError, ValueError, KeyError, RuntimeError):
            missing.append("tailscale")
        return missing

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="as", sender_keyword="sender")
    def Complete(self, sender=None):
        try:
            user = self.caller(sender)
            if user not in json.loads(os.environ["TENKR_MANAGED_USERS"]):
                raise PermissionError("This account is not configured for enrollment.")
            # Retrying after a lost success reply must not undo completed setup.
            if published(user):
                return []
            daemon = dbus.Interface(self.bus.get_object(
                "org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
            pid = int(daemon.GetConnectionUnixProcessID(sender))
            environment = dict(entry.split(b"=", 1) for entry in
                               Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in entry)
            display = environment.get(b"WAYLAND_DISPLAY", b"").decode()
            return complete(user, lambda: worker(user, display, os.environ["TENKR_VERIFIER"],
                                                 os.environ["TENKR_SYSTEMD_RUN"], os.environ["TENKR_SYSTEMCTL"]),
                            self.system_checks, lambda: self.caller(sender) == user,
                            activate_network=lambda: enable_remote(user, os.environ["TENKR_TAILSCALE"]),
                            rollback_network=lambda: restrict(os.environ["TENKR_TAILSCALE"]))
        except (PermissionError, RuntimeError) as error:
            raise dbus.exceptions.DBusException(str(error), name=BUS_NAME + ".Error") from None
        except Exception:
            raise dbus.exceptions.DBusException("Final verification failed. Retry setup.",
                                                name=BUS_NAME + ".Error") from None

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="", sender_keyword="sender")
    def PrepareNetwork(self, sender=None):
        try:
            user = self.caller(sender)
            if user not in json.loads(os.environ["TENKR_MANAGED_USERS"]):
                raise PermissionError("This account is not configured for enrollment.")
            prepare(user, os.environ["TENKR_TAILSCALE"])
        except (PermissionError, RuntimeError) as error:
            raise dbus.exceptions.DBusException(str(error), name=BUS_NAME + ".Error") from None
        except Exception:
            raise dbus.exceptions.DBusException("Network setup failed. Please retry.",
                                                name=BUS_NAME + ".Error") from None

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="b", sender_keyword="sender")
    def VerifyNetwork(self, sender=None):
        try:
            user = self.caller(sender)
            if user not in json.loads(os.environ["TENKR_MANAGED_USERS"]):
                return False
            return verify_enrollment(os.environ["TENKR_TAILSCALE"], os.environ["TENKR_TAILNET"],
                                     operator=user if published(user) else None)
        except Exception:
            return False

    @dbus.service.method(BUS_NAME, in_signature="ss", out_signature="", sender_keyword="sender")
    def SetPassword(self, current, replacement, sender=None):
        try:
            user = self.caller(sender)
            set_password(
                user, str(current), str(replacement), "/var/lib/10kr-workstation-setup",
                lambda name, password: pam.pam().authenticate(
                    name, password, service="tenkr-workstation-setup"),
                os.environ["TENKR_CHPASSWD"],
            )
        except (PermissionError, ValueError, RuntimeError) as error:
            raise dbus.exceptions.DBusException(
                str(error), name=BUS_NAME + ".Error") from None
        except Exception:
            raise dbus.exceptions.DBusException(
                "Password setup failed. Please try again.", name=BUS_NAME + ".Error") from None


def main():
    DBusGMainLoop(set_as_default=True)
    service = EnrollmentService(dbus.SystemBus())
    service.recover_pending()
    GLib.MainLoop().run()
