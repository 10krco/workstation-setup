import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.service import EnrollmentService


class CallerAuthorizationTest(unittest.TestCase):
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
