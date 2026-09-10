from __future__ import annotations

from dataclasses import dataclass
import json
import os
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
    marker = Path("/var/lib/10kr-workstation-setup/password-required") / os.environ.get("USER", "")
    if marker.exists():
        return ProbeResult(False, "The supplied one-time password still needs to be replaced.")
    return ProbeResult(True, "Your personal login password is set.")


def fingerprint() -> ProbeResult:
    result = _run("fprintd-list", os.environ.get("USER", ""))
    if result is None:
        return ProbeResult(False, "The fingerprint service is not available.")
    output = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode == 0 and "finger" in output:
        return ProbeResult(True, "At least one fingerprint is enrolled.")
    return ProbeResult(False, "No fingerprint is enrolled for this account.")


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
    return ProbeResult(True, "GitHub CLI and separate authentication and signing keys are configured.")


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
    result = _run("tailscale", "status", "--json")
    if result is None or result.returncode != 0:
        return ProbeResult(False, "This workstation has not joined Tailscale.")
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ProbeResult(False, "Tailscale returned an unreadable status.")
    if status.get("BackendState") == "Running":
        return ProbeResult(True, "Tailscale is connected.")
    return ProbeResult(False, f"Tailscale is {status.get('BackendState', 'not connected')}.")


def home_manager() -> ProbeResult:
    profile = Path.home() / ".local" / "state" / "nix" / "profiles" / "home-manager"
    if profile.exists():
        return ProbeResult(True, "A Home Manager generation is active.")
    return ProbeResult(False, "No Home Manager configuration is active. This step is optional.")


PROBES = {
    "password": password,
    "fingerprint": fingerprint,
    "onepassword": onepassword,
    "github": github,
    "keyring": keyring,
    "tailscale": tailscale,
    "home-manager": home_manager,
}


def probe(step: Step) -> ProbeResult:
    return PROBES[step.key]()
