from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    description: str
    required: bool = True


STEPS = (
    Step("password", "Choose your password", "Replace the one-time password supplied with the workstation."),
    Step("fingerprint", "Enroll a fingerprint", "Use the fingerprint reader for login, unlock, and approvals."),
    Step("onepassword", "Connect 1Password", "Sign in and enable CLI and SSH agent integration."),
    Step("github", "Connect GitHub", "Authenticate GitHub and register separate authentication and signing keys."),
    Step("keyring", "Protect application secrets", "Store the encrypted GNOME Keyring password in 1Password."),
    Step("chrome", "Connect your work browser", "Sign in to Chrome with your work email and enable profile sync."),
    Step("tailscale", "Join the 10kR network", "Enroll this workstation in Tailscale and enable Tailscale SSH."),
    Step("home-manager", "Personalize your environment", "Optionally activate a Home Manager configuration from GitHub.", False),
)


class EnrollmentState:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".config" / "10kr" / "workstation-setup"

    def is_complete(self, step: Step) -> bool:
        return (self.root / f"{step.key}.complete").is_file()

    def mark_complete(self, step: Step) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker = self.root / f"{step.key}.complete"
        marker.touch(mode=0o600, exist_ok=True)

    def finish(self) -> None:
        missing = [step.title for step in STEPS if step.required and not self.is_complete(step)]
        if missing:
            raise ValueError(f"Required setup remains: {', '.join(missing)}")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.root / "complete").touch(mode=0o600, exist_ok=True)
