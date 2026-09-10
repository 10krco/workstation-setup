"""Resolve and activate a user-selected immutable GitHub Home Manager flake."""
from dataclasses import dataclass
import json
import os
import re
import signal
import subprocess


@dataclass(frozen=True)
class Remote:
    source: str
    output: str
    revision: str

    @property
    def flake(self):
        return f"{self.source}#{self.output}"


def run(*args, timeout=600):
    with subprocess.Popen(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise RuntimeError("The operation timed out. Check the configuration and retry.") from None
    if process.returncode:
        # Do not dump command output into dialogs: it can contain private source data.
        raise RuntimeError(f"{args[0]} could not complete this operation. Check network access and repository permissions, then retry.")
    return output


def resolve(value):
    match = re.fullmatch(r"github:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:/([A-Za-z0-9_./-]+))?#([A-Za-z0-9_@.+-]+)", value.strip())
    if not match:
        raise ValueError("Use github:OWNER/REPOSITORY#OUTPUT, optionally with a branch or revision before #.")
    owner, repo, ref, output = match.groups()
    source = f"github:{owner}/{repo}" + (f"/{ref}" if ref else "")
    metadata = json.loads(run("nix", "flake", "metadata", "--json", "--no-update-lock-file", source))
    locked = metadata.get("locked", {})
    revision = locked.get("rev", "")
    if locked.get("type") != "github" or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("The repository did not resolve to an immutable GitHub revision.")
    remote = Remote(f"github:{owner}/{repo}/{revision}", output, revision)
    # Evaluation/build can fail before any activation changes the user's profile.
    run("nix", "build", "--no-link", "--no-update-lock-file",
        f'{remote.source}#homeConfigurations."{output}".activationPackage', timeout=1800)
    return remote


def activate(remote):
    run("home-manager", "switch", "--no-update-lock-file", "--flake", remote.flake, timeout=1800)
