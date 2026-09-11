import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from tenkr_workstation_setup.connectivity import connected


class ConnectivityTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.connectivity.urllib.request.urlopen")
    @patch("tenkr_workstation_setup.connectivity.dbus.Interface")
    @patch("tenkr_workstation_setup.connectivity.dbus.SystemBus")
    def test_disconnected_device_does_not_try_network_request(self, bus, interface, urlopen):
        interface.return_value.Get.return_value = 20
        self.assertFalse(connected())
        urlopen.assert_not_called()
        bus.return_value.close.assert_called_once()

    @patch("tenkr_workstation_setup.connectivity.urllib.request.urlopen")
    @patch("tenkr_workstation_setup.connectivity.dbus.Interface")
    @patch("tenkr_workstation_setup.connectivity.dbus.SystemBus")
    def test_tls_connection_rejects_portal_and_accepts_rate_limit(self, bus, interface, urlopen):
        interface.return_value.Get.return_value = 70
        response = MagicMock(url="https://api.github.com", status=200)
        urlopen.return_value.__enter__.return_value = response
        self.assertTrue(connected())
        response.url = "https://portal.example/"
        self.assertFalse(connected())
        urlopen.side_effect = urllib.error.URLError("certificate verification failed")
        self.assertFalse(connected())
        urlopen.side_effect = urllib.error.HTTPError("https://api.github.com", 429, "Rate limited", {}, None)
        self.assertTrue(connected())
