"""Fresh user-session checks for privileged completion; receipts are never proof."""
import json
from pathlib import Path
import re
import sys
import tomllib

import dbus

from . import chrome_setup, connectivity, keyring_setup, ssh_setup
from .chrome_pipe import ChromePipe
from .identity import git_identity


def github():
    home = Path.home()
    _, email = git_identity()
    login = json.loads(ssh_setup.command("gh", "api", "user"))["login"]
    ssh_setup.verify_email(email)
    keys = {}
    for role, filename, endpoint in (
        ("authentication", "tenkr-github-authentication.pub", "user/keys"),
        ("signing", "tenkr-git-signing.pub", "user/ssh_signing_keys"),
    ):
        key = " ".join((home / ".ssh" / filename).read_text().split()[:2])
        if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+", key):
            raise RuntimeError("The workstation public key is invalid.")
        pages = json.loads(ssh_setup.command("gh", "api", "--paginate", "--slurp", endpoint))
        if not any(" ".join(item["key"].split()[:2]) == key for page in pages for item in page):
            raise RuntimeError("The workstation public key is not registered with GitHub.")
        keys[role] = key
    if keys["authentication"] == keys["signing"]:
        raise RuntimeError("Authentication and signing require separate keys.")
    # Verify both keys live in 1Password and are selected by its agent config.
    entries = tomllib.loads((home / ".config/1Password/ssh/agent.toml").read_text())["ssh-keys"]
    found = set()
    if not isinstance(entries, list) or len(entries) > 100:
        raise RuntimeError("Review the 1Password agent configuration.")
    for entry in entries:
        item, vault = entry.get("item", ""), entry.get("vault", "")
        if not isinstance(item, str) or not isinstance(vault, str):
            continue
        if re.fullmatch(r"[a-z0-9]+", item) and re.fullmatch(r"[A-Za-z0-9 _.-]+", vault):
            public = ssh_setup.command("op", "read", f"op://{vault}/{item}/public_key").strip()
            found.add(" ".join(public.split()[:2]))
        if set(keys.values()).issubset(found):
            break
    if not set(keys.values()).issubset(found):
        raise RuntimeError("Both workstation keys must be available through 1Password.")
    ssh_setup.verify_authentication(login, home)
    if Path(ssh_setup.signing_configuration()["gpg.ssh.program"]).name != "op-ssh-sign":
        raise RuntimeError("Git must use the 1Password signing program.")
    ssh_setup.verify_signing(keys["signing"])


def keyring():
    reference = (Path.home() / keyring_setup.REFERENCE).read_text().strip()
    if not reference.startswith("op://") or "\n" in reference:
        raise RuntimeError("The keyring reference is invalid.")
    password = keyring_setup.read_password(reference)
    bus = dbus.SessionBus(private=True)
    try:
        root = bus.get_object(keyring_setup.SERVICE, keyring_setup.ROOT)
        service = dbus.Interface(root, "org.freedesktop.Secret.Service")
        collection = service.ReadAlias("login", timeout=15)
        if str(collection) == "/":
            raise RuntimeError("The login keyring is missing.")
        _, session = service.OpenSession("plain", dbus.String("", variant_level=1), timeout=15)
        try:
            secret = dbus.Struct((dbus.ObjectPath(session), dbus.ByteArray(b""),
                                 dbus.ByteArray(password), dbus.String("text/plain")), signature="oayays")
            # Unlike Unlock on an open collection, this validates the password.
            dbus.Interface(root, keyring_setup.INTERNAL).ChangeWithMasterPassword(
                collection, secret, secret, timeout=20)
        finally:
            dbus.Interface(bus.get_object(keyring_setup.SERVICE, session),
                           "org.freedesktop.Secret.Session").Close(timeout=5)
    finally:
        bus.close()
    ssh_setup.command("systemctl", "--user", "start", "tenkr-onepassword.service",
                      "tenkr-gnome-keyring-unlock.service", discard=True, timeout=320)


def chrome():
    browser = ChromePipe(chrome_setup.profile_path())
    try:
        chrome_setup.verify(browser)
    finally:
        browser.close()


def onepassword():
    if not (Path.home() / ".1password/agent.sock").is_socket():
        raise RuntimeError("The 1Password SSH agent is unavailable.")
    ssh_setup.command("op", "vault", "list", "--format", "json", discard=True)


def verify():
    missing = []
    for key, check in (("connectivity", connectivity.connected), ("onepassword", onepassword),
                       ("github", github), ("keyring", keyring), ("chrome", chrome)):
        try:
            if check() is False:
                missing.append(key)
        except Exception:
            # No command output or exception messages cross the privilege boundary.
            missing.append(key)
    return missing


def main():
    print(json.dumps(verify()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
