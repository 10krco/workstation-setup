"""Check that enrollment can reach the public GitHub service over verified TLS."""
import urllib.error
import urllib.request

import dbus


def connected():
    bus = dbus.SystemBus(private=True)
    try:
        properties = dbus.Interface(bus.get_object("org.freedesktop.NetworkManager",
            "/org/freedesktop/NetworkManager"), "org.freedesktop.DBus.Properties")
        state = int(properties.Get("org.freedesktop.NetworkManager", "State", timeout=5))
        if state < 60:
            return False
    finally:
        bus.close()
    try:
        request = urllib.request.Request("https://api.github.com", method="HEAD")
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.url == "https://api.github.com" and response.status == 200
    except urllib.error.HTTPError as error:
        # A rate limit or authorization response still proves a TLS connection.
        return error.url == "https://api.github.com" and error.code in (401, 403, 429)
    except (OSError, urllib.error.URLError):
        return False
