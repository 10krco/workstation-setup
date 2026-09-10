"""Read the fleet-provided identity for the current operating-system account."""
import json
import os
from pathlib import Path
import pwd


def git_identity(path=Path("/etc/10kr/workstation-users.json")):
    try:
        username = pwd.getpwuid(os.getuid()).pw_name
        identity = json.loads(path.read_text())[username]
        full_name, title, email = (identity.get(key) for key in ("fullName", "title", "workEmail"))
        if not all(isinstance(value, str) and value.strip() for value in (full_name, title, email)):
            raise ValueError("incomplete identity")
        if any(char in value for value in (full_name, title, email) for char in "\n\r\x00"):
            raise ValueError("invalid identity")
        return f"{full_name} ({title})", email
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError("Your fleet user definition needs a full name, title, and work email before Git setup can continue.") from None
