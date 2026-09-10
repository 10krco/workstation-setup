"""Narrow system D-Bus API for first-login password enrollment."""
import os
import pwd

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import pam

from .password_backend import set_password
from .network import prepare

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
