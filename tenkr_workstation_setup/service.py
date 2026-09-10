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
from .network import command as network_command
from .completion import complete, worker

BUS_NAME = "com.tenkr.WorkstationSetup"
OBJECT_PATH = "/com/tenkr/WorkstationSetup"


class EnrollmentService(dbus.service.Object):
    def __init__(self, bus):
        self.bus = bus
        self.name = dbus.service.BusName(BUS_NAME, bus=bus)
        super().__init__(self.name, OBJECT_PATH)

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
            status = json.loads(network_command(executable, "status", "--json"))
            prefs = json.loads(network_command(executable, "debug", "prefs"))
            expected = os.environ["TENKR_TAILNET"]
            if (not expected or status.get("BackendState") != "Running"
                    or status.get("CurrentTailnet", {}).get("Name") != expected
                    or prefs.get("OperatorUser") != user or prefs.get("RunSSH") is not True):
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
            daemon = dbus.Interface(self.bus.get_object(
                "org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
            pid = int(daemon.GetConnectionUnixProcessID(sender))
            environment = dict(entry.split(b"=", 1) for entry in
                               Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in entry)
            display = environment.get(b"WAYLAND_DISPLAY", b"").decode()
            return complete(user, lambda: worker(user, display, os.environ["TENKR_VERIFIER"],
                                                 os.environ["TENKR_SYSTEMD_RUN"], os.environ["TENKR_SYSTEMCTL"]),
                            self.system_checks, lambda: self.caller(sender) == user)
        except (PermissionError, RuntimeError) as error:
            raise dbus.exceptions.DBusException(str(error), name=BUS_NAME + ".Error") from None
        except Exception:
            raise dbus.exceptions.DBusException("Final verification failed. Retry setup.",
                                                name=BUS_NAME + ".Error") from None

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="", sender_keyword="sender")
    def PrepareNetwork(self, sender=None):
        try:
            prepare(self.caller(sender), os.environ["TENKR_TAILSCALE"])
        except (PermissionError, RuntimeError) as error:
            raise dbus.exceptions.DBusException(str(error), name=BUS_NAME + ".Error") from None
        except Exception:
            raise dbus.exceptions.DBusException("Network setup failed. Please retry.",
                                                name=BUS_NAME + ".Error") from None

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
    GLib.MainLoop().run()
