"""Tailscale setup operations with explicit verification and bounded waiting."""
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse


def command(*args, timeout=15):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("Tailscale could not complete the operation. Check connectivity and retry.")
    return result.stdout


def prepare(user, executable, root=Path("/var/lib/10kr-workstation-setup")):
    if (not (root / "managed-users" / user).is_file()
            or not (root / "password-set" / user).is_file()
            or (root / "completed" / user).exists()):
        raise PermissionError("Network setup requires an incomplete managed account with its password set.")
    # An operator can enable SSH again, so defer both capabilities until all
    # enrollment checks have succeeded in the privileged completion service.
    restrict(executable)
    subprocess.run([executable, "up", "--timeout=2s"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=10, check=False)


def restrict(executable):
    command(executable, "set", "--operator=", "--ssh=false")
    prefs = json.loads(command(executable, "debug", "prefs"))
    if prefs.get("OperatorUser") not in (None, "") or prefs.get("RunSSH") is not False:
        raise RuntimeError("Tailscale could not restrict remote access during setup.")


def enable_remote(user, executable):
    command(executable, "set", f"--operator={user}", "--ssh=true")
    prefs = json.loads(command(executable, "debug", "prefs"))
    if prefs.get("OperatorUser") != user or prefs.get("RunSSH") is not True:
        raise RuntimeError("Tailscale could not enable the required operator and SSH settings.")


def verify(executable="tailscale"):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    result = bus.call_sync("com.tenkr.WorkstationSetup", "/com/tenkr/WorkstationSetup",
                           "com.tenkr.WorkstationSetup", "VerifyNetwork", None,
                           GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 35000, None)
    return result.unpack()[0]


def verify_enrollment(executable, expected, operator=None):
    status = json.loads(command(executable, "status", "--json"))
    prefs = json.loads(command(executable, "debug", "prefs"))
    if not (status.get("BackendState") == "Running"
            and prefs.get("RunSSH") is (operator is not None)
            and (prefs.get("OperatorUser") or "") == (operator or "")):
        return False
    return bool(expected) and (status.get("CurrentTailnet") or {}).get("Name") == expected


def connect(cancel, show_url, progress, timeout=300):
    if cancel.is_set():
        return False
    # PrepareNetwork already starts the connection as root. The user only reads
    # status and opens the sign-in URL; operator privileges are still withheld.
    deadline = time.monotonic() + timeout
    last_url = None
    while not cancel.is_set():
        status = json.loads(command("tailscale", "status", "--json"))
        if status.get("BackendState") == "Running":
            if not verify():
                raise RuntimeError("The required work tailnet or enrollment access restrictions could not be verified. Check the selected Tailscale account and retry.")
            return True
        url = status.get("AuthURL", "")
        if url and url != last_url:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "login.tailscale.com" or parsed.username:
                raise RuntimeError("Tailscale returned an unexpected sign-in address.")
            show_url(url)
            last_url = url
        if not url and status.get("BackendState") not in {"NeedsLogin", "Starting", "NeedsMachineAuth"}:
            raise RuntimeError("Tailscale could not start. Check connectivity and retry.")
        progress("Finish signing in through your browser." if url else "Waiting for Tailscale or administrator approval…")
        if time.monotonic() >= deadline:
            raise RuntimeError("Tailscale setup timed out. You can retry without losing your existing login.")
        cancel.wait(2)
    return False
