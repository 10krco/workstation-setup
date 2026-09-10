"""Privileged completion policy and atomic state publication."""
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tempfile
import uuid

ROOT = Path("/var/lib/10kr-workstation-setup")
USER_CHECKS = {"connectivity", "onepassword", "github", "keyring", "chrome"}


def worker(user, display, executable, systemd_run, systemctl):
    account = pwd.getpwnam(user)
    runtime = f"/run/user/{account.pw_uid}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", display):
        raise RuntimeError("The graphical session is unavailable. Log in again and retry.")
    unit = "tenkr-enrollment-verify-" + uuid.uuid4().hex
    environment = {
        "HOME": account.pw_dir, "USER": user, "LOGNAME": user,
        "PATH": "/run/wrappers/bin:/run/current-system/sw/bin",
        "XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
        "WAYLAND_DISPLAY": display, "XDG_SESSION_TYPE": "wayland",
        "SSH_AUTH_SOCK": account.pw_dir + "/.1password/agent.sock",
    }
    # A separate systemd cgroup bounds all descendants, including Chrome, which
    # creates its own process group. No user-controlled program runs as root.
    args = [systemd_run, "--quiet", "--wait", "--pipe", "--collect", "--service-type=exec",
            f"--unit={unit}", f"--property=User={user}", f"--property=Group={account.pw_gid}",
            "--property=RuntimeMaxSec=900", "--property=TimeoutStopSec=10",
            "--property=KillMode=control-group", "--property=UMask=0077", "--property=LimitCORE=0",
            f"--property=WorkingDirectory={account.pw_dir}"]
    args += [f"--setenv={key}={value}" for key, value in environment.items()]
    try:
        result = subprocess.run([*args, executable], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=930, check=False,
                                env={"PATH": "/run/current-system/sw/bin"})
        if result.returncode or len(result.stdout) > 1024:
            raise RuntimeError("Final verification failed or timed out. Unlock 1Password and retry.")
        missing = json.loads(result.stdout)
        if not isinstance(missing, list) or any(not isinstance(key, str) or key not in USER_CHECKS for key in missing):
            raise ValueError("invalid verification result")
        return missing
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Final verification could not finish. Retry setup.") from None
    finally:
        subprocess.run([systemctl, "stop", unit + ".service"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30, check=False)


def complete(user, verify_user, verify_system, still_authorized, root=ROOT):
    root = Path(root)
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user) or user == "root":
        raise PermissionError("This account cannot enroll.")
    if not (root / "managed-users" / user).is_file():
        raise PermissionError("This account is not managed for enrollment.")
    if not (root / "password-set" / user).is_file():
        return ["password"]
    missing = verify_system(user)
    if missing:
        return missing
    missing = verify_user()
    if missing:
        return missing
    # Session authorization and root-controlled checks must still hold after
    # interactive checks, which may have taken several minutes.
    if not still_authorized():
        raise PermissionError("Your local setup session is no longer active.")
    missing = verify_system(user)
    if missing:
        return missing
    marker = root / "completed" / user
    marker.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=marker.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o644)
            stream.write(b"1\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
        directory = os.open(marker.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return []
