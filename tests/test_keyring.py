import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import dbus
from tenkr_workstation_setup.keyring_setup import ensure_reference, migrate, SERVICE, ROOT, INTERNAL


class KeyringReferenceTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.keyring_setup.command")
    def test_creation_output_is_discarded_and_retry_reuses_item(self, command):
        with tempfile.TemporaryDirectory() as home:
            def calls(*args, **kwargs):
                if "create" in args:
                    self.assertTrue(kwargs["discard"])
                    title = args[args.index("--title") + 1]
                    command.listing = [{"id": "item123", "title": title}]
                    return None
                return json.dumps(command.listing)
            command.listing = []
            command.side_effect = calls
            first = ensure_reference("Personal", home)
            second = ensure_reference("Personal", home)
            self.assertEqual(first, "op://Personal/item123/password")
            self.assertEqual(first, second)
            self.assertEqual(sum("create" in call.args for call in command.call_args_list), 1)


@unittest.skipUnless(os.environ.get("TENKR_KEYRING_TEST") == "1", "requires isolated keyring session")
class KeyringRuntimeTest(unittest.TestCase):
    def test_creation_retry_wrong_password_and_migration(self):
        control = Path(os.environ["XDG_RUNTIME_DIR"]) / "keyring"
        process = subprocess.Popen(["gnome-keyring-daemon", "--foreground", "--components=secrets",
                                    f"--control-directory={control}"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        bus = None
        try:
            bus = dbus.SessionBus(private=True)
            for _ in range(100):
                if bus.name_has_owner(SERVICE):
                    break
                time.sleep(0.05)
            else:
                self.fail("Disposable keyring daemon did not become ready")
            first = migrate(bus, b"first-test-password")
            service = dbus.Interface(bus.get_object(SERVICE, ROOT), "org.freedesktop.Secret.Service")
            _, secret_session = service.OpenSession("plain", dbus.String("", variant_level=1), timeout=10)
            secret = dbus.Struct((dbus.ObjectPath(secret_session), dbus.ByteArray(b""),
                                  dbus.ByteArray(b"saved-test-secret"), dbus.String("text/plain")), signature="oayays")
            item, _ = dbus.Interface(bus.get_object(SERVICE, first), "org.freedesktop.Secret.Collection").CreateItem(
                dbus.Dictionary({"org.freedesktop.Secret.Item.Label": "Saved test item"}, signature="sv"),
                secret, False, timeout=10)
            self.assertEqual(migrate(bus, b"first-test-password"), first)
            with self.assertRaises(dbus.DBusException):
                migrate(bus, b"replacement-test-password", b"incorrect-current-password")
            self.assertEqual(migrate(bus, b"replacement-test-password", b"first-test-password"), first)
            retained = dbus.Interface(bus.get_object(SERVICE, item), "org.freedesktop.Secret.Item").GetSecret(secret_session, timeout=10)
            self.assertEqual(bytes(retained[2]), b"saved-test-secret")
            root = bus.get_object(SERVICE, ROOT)
            service = dbus.Interface(root, "org.freedesktop.Secret.Service")
            service.Lock([dbus.ObjectPath(first)], timeout=10)
            props = dbus.Interface(bus.get_object(SERVICE, first), "org.freedesktop.DBus.Properties")
            self.assertTrue(props.Get("org.freedesktop.Secret.Collection", "Locked", timeout=10))
            self.assertEqual(migrate(bus, b"replacement-test-password"), first)
            self.assertFalse(props.Get("org.freedesktop.Secret.Collection", "Locked", timeout=10))
            self.assertEqual(str(service.ReadAlias("login", timeout=10)), first)
            self.assertEqual(str(service.ReadAlias("default", timeout=10)), first)
            old_owner = bus.get_name_owner(SERVICE)
            process.terminate()
            process.wait(timeout=10)
            process = subprocess.Popen(["gnome-keyring-daemon", "--foreground", "--components=secrets",
                                        f"--control-directory={control}"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                if bus.name_has_owner(SERVICE) and bus.get_name_owner(SERVICE) != old_owner:
                    break
                time.sleep(0.05)
            else:
                self.fail("Keyring daemon did not restart")
            props = dbus.Interface(bus.get_object(SERVICE, first), "org.freedesktop.DBus.Properties")
            self.assertTrue(props.Get("org.freedesktop.Secret.Collection", "Locked", timeout=10))
            self.assertEqual(migrate(bus, b"replacement-test-password"), first)
        finally:
            if bus is not None:
                bus.close()
            process.terminate()
            process.wait(timeout=10)
