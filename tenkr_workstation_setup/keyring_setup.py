"""Create or migrate an encrypted login keyring using a 1Password-held password."""
import json
import os
from pathlib import Path
import pwd
import re
import socket
import subprocess

import dbus

from .ssh_setup import command, write_config


REFERENCE = Path(".config/10kr/gnome-keyring-1password-secret-reference")
SERVICE = "org.freedesktop.secrets"
ROOT = "/org/freedesktop/secrets"
INTERNAL = "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"


def ensure_reference(vault, home=None):
    home = Path.home() if home is None else Path(home)
    existing = home / REFERENCE
    if existing.is_file():
        reference = existing.read_text().strip()
        if not reference.startswith("op://") or any(char in reference for char in "\n\r\x00"):
            raise RuntimeError("The stored keyring secret reference is invalid.")
        return reference
    if not re.fullmatch(r"[A-Za-z0-9 _.-]+", vault):
        raise ValueError("Enter a 1Password vault name or ID.")
    title = f"{pwd.getpwuid(os.getuid()).pw_name}@{socket.gethostname()} GNOME Login Keyring"
    def find():
        items = json.loads(command("op", "item", "list", "--vault", vault,
                                   "--categories", "Password", "--format", "json"))
        matches = [item["id"] for item in items if item["title"] == title]
        if len(matches) > 1:
            raise RuntimeError("Multiple keyring password items have this workstation's title. Resolve the duplicates in 1Password.")
        return matches[0] if matches else None
    item = find()
    if item is None:
        command("op", "item", "create", "--vault", vault, "--category", "Password",
                "--title", title, "--generate-password=letters,digits,64", discard=True)
        item = find()
    if item is None or not re.fullmatch(r"[a-z0-9]+", item):
        raise RuntimeError("The keyring password item could not be located in 1Password.")
    return f"op://{vault}/{item}/password"


def read_password(reference):
    result = subprocess.run(["op", "read", "--no-newline", reference],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    if result.returncode or not result.stdout:
        raise RuntimeError("Unlock 1Password and allow access to the keyring password, then retry.")
    return result.stdout


def migrate(bus, replacement, current=b""):
    if not replacement:
        raise ValueError("The keyring password must not be empty.")
    root = bus.get_object(SERVICE, ROOT)
    service = dbus.Interface(root, "org.freedesktop.Secret.Service")
    internal = dbus.Interface(root, INTERNAL)
    collection = service.ReadAlias("login", timeout=15)
    _, session = service.OpenSession("plain", dbus.String("", variant_level=1), timeout=15)
    def secret(value):
        return dbus.Struct((dbus.ObjectPath(session), dbus.ByteArray(b""),
                            dbus.ByteArray(value), dbus.String("text/plain")), signature="oayays")
    try:
        if str(collection) == "/":
            collection = internal.CreateWithMasterPassword(
                # GNOME derives the collection identifier from this label. Its
                # login alias is fixed to identifier 'login' and cannot be set.
                dbus.Dictionary({"org.freedesktop.Secret.Collection.Label": dbus.String("login")}, signature="sv"),
                secret(replacement), timeout=20)
        else:
            try:
                # Unlock may succeed without checking a password for an already
                # open collection. A same-password change verifies it on retry.
                internal.ChangeWithMasterPassword(collection, secret(replacement), secret(replacement),
                    timeout=20)
            except dbus.DBusException:
                internal.ChangeWithMasterPassword(collection, secret(current), secret(replacement),
                    timeout=20)
        internal.UnlockWithMasterPassword(collection, secret(replacement),
            timeout=20)
        properties = dbus.Interface(bus.get_object(SERVICE, collection), "org.freedesktop.DBus.Properties")
        if properties.Get("org.freedesktop.Secret.Collection", "Locked", timeout=15):
            raise RuntimeError("The keyring remained locked after enrollment.")
        if str(service.ReadAlias("login", timeout=15)) != str(collection):
            raise RuntimeError("GNOME did not recognize the new login keyring. Retry enrollment before continuing.")
        if str(service.ReadAlias("default", timeout=15)) == "/":
            service.SetAlias("default", collection, timeout=15)
        return str(collection)
    finally:
        try:
            dbus.Interface(bus.get_object(SERVICE, session), "org.freedesktop.Secret.Session").Close(timeout=5)
        except dbus.DBusException:
            pass


def enroll(vault, current):
    verification = Path.home() / ".config/10kr/workstation-setup/keyring-verification.json"
    verification.unlink(missing_ok=True)
    reference = ensure_reference(vault)
    replacement = read_password(reference)
    bus = dbus.SessionBus(private=True)
    try:
        migrate(bus, replacement, current.encode())
    except dbus.DBusException:
        raise RuntimeError("The keyring could not be enrolled. Check its current password and retry; existing secrets have not been deleted.") from None
    finally:
        bus.close()
    write_config(Path.home() / REFERENCE, reference + "\n")
    result = subprocess.run(["systemctl", "--user", "start", "tenkr-onepassword.service",
                             "tenkr-gnome-keyring-unlock.service"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=320)
    if result.returncode:
        raise RuntimeError("The encrypted keyring is enrolled, but its login unlock service could not start. Retry after the workstation service is available.")
    write_config(verification, json.dumps({"reference": reference}))
