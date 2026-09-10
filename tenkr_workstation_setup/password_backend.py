"""Password enrollment policy; no secrets are written to enrollment state."""
from pathlib import Path
import os
import subprocess
import tempfile


def set_password(user, current, replacement, root, authenticate, chpasswd):
    root = Path(root)
    if not (root / "managed-users" / user).is_file():
        raise PermissionError("This account is not enrolled for workstation setup.")
    marker = root / "password-set" / user
    if marker.exists() or (root / "completed" / user).exists():
        raise PermissionError("The initial password has already been changed.")
    if any(char in replacement for char in "\x00\n\r") or len(replacement) < 12:
        raise ValueError("Choose a password of at least 12 characters without line breaks.")
    if replacement == current:
        raise ValueError("Choose a different password from the supplied password.")
    if not authenticate(user, current):
        raise PermissionError("The current password was not accepted.")
    result = subprocess.run(
        [chpasswd], input=f"{user}:{replacement}\n", text=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=30,
    )
    if result.returncode:
        raise RuntimeError("The system could not change the password. Please try again.")
    marker.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=marker.parent, delete=False) as temporary:
        os.fchmod(temporary.fileno(), 0o644)
        temporary.write(b"1\n")
        temporary.flush()
        os.fsync(temporary.fileno())
        name = temporary.name
    os.replace(name, marker)
    directory_fd = os.open(marker.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
