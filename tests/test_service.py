import unittest
import dbus
from unittest.mock import Mock, patch

from tenkr_workstation_setup.service import EnrollmentService


class CallerAuthorizationTest(unittest.TestCase):
    def test_completion_requires_a_print_only_when_usable_readers_exist(self):
        service = Mock(bus=Mock())
        manager, device = Mock(), Mock()
        cases = [([], [], False), (["/reader"], [], True),
                 (["/reader"], ["right-index-finger"], False)]
        with patch.dict("os.environ", {"TENKR_TAILSCALE": "/tailscale", "TENKR_TAILNET": "example.ts.net"}), \
             patch("tenkr_workstation_setup.service.verify_enrollment", return_value=True):
            for devices, fingers, missing in cases:
                manager.GetDevices.return_value = devices
                device.ListEnrolledFingers.return_value = fingers
                with patch("tenkr_workstation_setup.service.dbus.Interface", side_effect=[manager, device]):
                    self.assertEqual("fingerprint" in EnrollmentService.system_checks(service, "alice"), missing)
            manager.GetDevices.side_effect = dbus.DBusException("Unavailable", name="org.freedesktop.DBus.Error.ServiceUnknown")
            with patch("tenkr_workstation_setup.service.dbus.Interface", return_value=manager):
                self.assertIn("fingerprint", EnrollmentService.system_checks(service, "alice"))

    def authorize(self, uid=1000, active=True, remote=False, session_uid=1000, kind="wayland"):
        service = Mock(bus=Mock())
        daemon = Mock()
        daemon.GetConnectionUnixUser.return_value = uid
        daemon.GetConnectionUnixProcessID.return_value = 42
        properties = Mock()
        properties.GetAll.return_value = {
            "User": (session_uid, "/user"), "Active": active, "Remote": remote, "Type": kind,
        }
        with patch("tenkr_workstation_setup.service.dbus.Interface",
                   side_effect=[daemon, Mock(), properties]), patch(
                       "tenkr_workstation_setup.service.pwd.getpwuid",
                       return_value=Mock(pw_name="alice")):
            return EnrollmentService.caller(service, ":1.42")

    def test_accepts_only_active_local_wayland_owner(self):
        self.assertEqual(self.authorize(), "alice")
        for values in ({"uid": 0}, {"active": False}, {"remote": True},
                       {"session_uid": 1001}, {"kind": "tty"}):
            with self.subTest(values=values), self.assertRaises(PermissionError):
                self.authorize(**values)
