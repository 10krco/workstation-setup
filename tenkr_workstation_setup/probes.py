from __future__ import annotations

from dataclasses import dataclass
import json
import os
import pwd
from pathlib import Path
import subprocess

from .state import Step


@dataclass(frozen=True)
class ProbeResult:
    complete: bool
    detail: str


def _run(*command: str, timeout: int = 5) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def password() -> ProbeResult:
    marker = Path("/var/lib/10kr-workstation-setup/password-set") / pwd.getpwuid(os.getuid()).pw_name
    if marker.is_file():
        return ProbeResult(True, "Your personal login password is set.")
    return ProbeResult(False, "The supplied one-time password still needs to be replaced.")


def fingerprint() -> ProbeResult:
    from gi.repository import GLib
    from .fingerprint import enrolled_fingers
    try:
        if enrolled_fingers():
            return ProbeResult(True, "At least one fingerprint is enrolled.")
        return ProbeResult(False, "No fingerprint is enrolled for this account.")
    except GLib.Error:
        return ProbeResult(False, "The fingerprint reader is unavailable or access was denied. Retry enrollment.")


def onepassword() -> ProbeResult:
    agent = Path.home() / ".1password" / "agent.sock"
    if not agent.is_socket():
        return ProbeResult(False, "Sign in to 1Password and enable its SSH agent.")
    result = _run("op", "vault", "list", "--format", "json", timeout=15)
    if result is None or result.returncode != 0:
        return ProbeResult(False, "Enable desktop CLI integration and unlock 1Password.")
    return ProbeResult(True, "1Password CLI integration and the SSH agent are available.")


def github() -> ProbeResult:
    auth = _run("gh", "auth", "status", "--hostname", "github.com")
    if auth is None or auth.returncode != 0:
        return ProbeResult(False, "GitHub CLI is not signed in.")
    authentication_key = Path.home() / ".ssh" / "tenkr-github-authentication.pub"
    signing_key = Path.home() / ".ssh" / "tenkr-git-signing.pub"
    if not authentication_key.is_file() or not signing_key.is_file():
        return ProbeResult(False, "Authentication and signing keys have not been configured.")
    from .ssh_setup import signing_configuration
    try:
        receipt = json.loads((Path.home() / ".config/10kr/workstation-setup/signing-verification.json").read_text())
        if receipt != {"key": signing_key.read_text().strip(), "settings": signing_configuration(timeout=1)}:
            raise ValueError("Signing settings changed")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return ProbeResult(False, "Git signing needs verification. Run GitHub setup to retry.")
    return ProbeResult(True, "GitHub keys are configured and a signed test commit verified successfully.")


def keyring() -> ProbeResult:
    reference = Path.home() / ".config" / "10kr" / "gnome-keyring-1password-secret-reference"
    try:
        valid_reference = reference.is_file() and reference.read_text().strip().startswith("op://")
    except (OSError, UnicodeError):
        valid_reference = False
    if valid_reference:
        return ProbeResult(True, "The encrypted login keyring is backed by a 1Password item.")
    return ProbeResult(False, "The login keyring has not been enrolled with 1Password.")


def tailscale() -> ProbeResult:
    from .network import verify
    try:
        if verify():
            return ProbeResult(True, "Tailscale is connected with operator access and SSH enabled.")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        pass
    return ProbeResult(False, "Tailscale network, operator access, and SSH setup need verification.")


def home_manager() -> ProbeResult:
    profile = Path.home() / ".local" / "state" / "nix" / "profiles" / "home-manager"
    if profile.exists():
        return ProbeResult(True, "A Home Manager generation is active.")
    return ProbeResult(False, "No Home Manager configuration is active. This step is optional.")


def chrome() -> ProbeResult:
    from .identity import git_identity
    from .chrome_setup import profile_path
    try:
        _, email = git_identity()
        receipt = json.loads((Path.home() / ".config/10kr/workstation-setup/chrome-verification.json").read_text())
        if (receipt["email"] == email and receipt["profile"] == str(profile_path())
                and (profile_path() / "Default/Preferences").is_file()
                and (Path.home() / ".local/share/applications/10kr-work-browser.desktop").is_file()):
            return ProbeResult(True, "Your work browser's account and sync settings were verified.")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        pass
    return ProbeResult(False, "Sign in to the work browser and verify its sync settings.")


PROBES = {
    "password": password,
    "fingerprint": fingerprint,
    "onepassword": onepassword,
    "github": github,
    "keyring": keyring,
    "chrome": chrome,
    "tailscale": tailscale,
    "home-manager": home_manager,
}


def probe(step: Step) -> ProbeResult:
    return PROBES[step.key]()
