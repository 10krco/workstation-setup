"""Tailscale setup operations with explicit verification and bounded waiting."""
import json
import os
from pathlib import Path
import pwd
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
    command(executable, "set", f"--operator={user}", "--ssh=true")
    prefs = json.loads(command(executable, "debug", "prefs"))
    if prefs.get("OperatorUser") != user or prefs.get("RunSSH") is not True:
        raise RuntimeError("Tailscale did not save the required operator and SSH settings.")


def verify(executable="tailscale"):
    status = json.loads(command(executable, "status", "--json"))
    prefs = json.loads(command(executable, "debug", "prefs"))
    user = pwd.getpwuid(os.getuid()).pw_name
    return (status.get("BackendState") == "Running"
            and prefs.get("RunSSH") is True and prefs.get("OperatorUser") == user)


def connect(cancel, show_url, progress, timeout=300):
    if cancel.is_set():
        return False
    # up preserves existing preferences; no reset or forced reauthentication.
    result = subprocess.run(["tailscale", "up", "--timeout=2s"],
                            capture_output=True, timeout=10, check=False)
    deadline = time.monotonic() + timeout
    last_url = None
    while not cancel.is_set():
        status = json.loads(command("tailscale", "status", "--json"))
        if status.get("BackendState") == "Running":
            if not verify():
                raise RuntimeError("Connected, but operator access or Tailscale SSH is not configured. Retry setup.")
            return True
        url = status.get("AuthURL", "")
        if url and url != last_url:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "login.tailscale.com" or parsed.username:
                raise RuntimeError("Tailscale returned an unexpected sign-in address.")
            show_url(url)
            last_url = url
        if result.returncode and not url and status.get("BackendState") not in {"NeedsLogin", "Starting", "NeedsMachineAuth"}:
            raise RuntimeError("Tailscale could not start. Check connectivity and retry.")
        progress("Finish signing in through your browser." if url else "Waiting for Tailscale or administrator approval…")
        if time.monotonic() >= deadline:
            raise RuntimeError("Tailscale setup timed out. You can retry without losing your existing login.")
        cancel.wait(2)
    return False
