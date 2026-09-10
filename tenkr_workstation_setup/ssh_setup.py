"""Idempotent public-key registration; private key material is never requested."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from .identity import git_identity


def write_config(path, content):
    if path.is_symlink():
        raise RuntimeError(f"{path.name} is managed through a symbolic link. Update its source configuration before retrying.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def command(*args, discard=False):
    if args[:2] == ("gh", "api"):
        args = (*args[:2], "--hostname", "github.com", *args[2:])
    result = subprocess.run(args, stdout=subprocess.DEVNULL if discard else subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed. Verify account access and retry.")
    return result.stdout


def ensure_item(vault, title):
    def find():
        items = json.loads(command("op", "item", "list", "--vault", vault,
                                  "--categories", "SSH Key", "--format", "json"))
        matches = [item["id"] for item in items if item["title"] == title]
        if len(matches) > 1:
            raise RuntimeError("Multiple matching SSH keys exist. Resolve the duplicate titles in 1Password first.")
        return matches[0] if matches else None
    item = find()
    if item is None:
        # Suppress the create response entirely; it is not needed to discover the item.
        command("op", "item", "create", "--category", "SSH Key", "--vault", vault,
                "--title", title, "--ssh-generate-key", "ed25519", discard=True)
        item = find()
    if item is None or not re.fullmatch(r"[a-z0-9]+", item):
        raise RuntimeError("The generated SSH key could not be located in 1Password.")
    public = command("op", "read", f"op://{vault}/{item}/public_key").strip()
    parts = public.split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519" or not re.fullmatch(r"[A-Za-z0-9+/=]+", parts[1]):
        raise RuntimeError("1Password did not return an Ed25519 public key.")
    return item, " ".join(parts[:2])


def register(key, role, title):
    endpoint = "user/keys" if role == "authentication" else "user/ssh_signing_keys"
    pages = json.loads(command("gh", "api", "--paginate", "--slurp", endpoint))
    if any(" ".join(item["key"].split()[:2]) == key for page in pages for item in page):
        return
    command("gh", "api", "--method", "POST", endpoint, "-f", f"title={title}", "-f", f"key={key}")
    pages = json.loads(command("gh", "api", "--paginate", "--slurp", endpoint))
    if not any(" ".join(item["key"].split()[:2]) == key for page in pages for item in page):
        raise RuntimeError("GitHub did not retain the public-key registration.")


def signing_configuration():
    name, email = git_identity()
    settings = {}
    for setting, expected in (("user.name", name), ("user.email", email),
                              ("gpg.format", "ssh"), ("commit.gpgsign", "true"),
                              ("tag.gpgsign", "true")):
        settings[setting] = command("git", "config", "--global", "--get", setting).strip()
        if settings[setting] != expected:
            raise RuntimeError("Git identity or signing settings do not match the workstation policy.")
    for setting in ("user.signingkey", "gpg.ssh.program"):
        settings[setting] = command("git", "config", "--global", "--get", setting).strip()
    return settings


def verify_email(email):
    pages = json.loads(command("gh", "api", "--paginate", "--slurp", "user/emails"))
    if not any(item.get("email", "").casefold() == email.casefold() and item.get("verified") is True
               for page in pages for item in page):
        raise RuntimeError(f"Add and verify {email} at https://github.com/settings/emails, then retry setup.")


def verify_authentication(login, home):
    """Authenticate to GitHub using published host keys and the user's SSH configuration."""
    effective = command("ssh", "-G", "git@github.com")
    options = {}
    for line in effective.splitlines():
        key, _, value = line.partition(" ")
        options.setdefault(key, []).append(value)
    agent = str(home / ".1password/agent.sock")
    identity = str(home / ".ssh/tenkr-github-authentication.pub")
    expand = lambda value: str(Path(value).expanduser())
    if (options.get("hostname") != ["github.com"] or options.get("identitiesonly") != ["yes"]
            or [expand(value) for value in options.get("identityagent", [])] != [agent]
            or [expand(value) for value in options.get("identityfile", [])] != [identity]):
        raise RuntimeError("SSH configuration does not select the workstation 1Password agent and authentication key.")
    metadata = json.loads(command("gh", "api", "meta"))
    host_keys = metadata.get("ssh_keys", [])
    if not host_keys or any(not re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+", key)
                            for key in host_keys):
        raise RuntimeError("GitHub did not return recognized SSH host keys.")
    with tempfile.TemporaryDirectory(prefix="tenkr-ssh-check-") as directory:
        known_hosts = Path(directory) / "known_hosts"
        known_hosts.write_text("".join(f"github.com {key}\n" for key in host_keys))
        result = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                                 "-o", "StrictHostKeyChecking=yes", "-o", "GlobalKnownHostsFile=/dev/null",
                                 "-o", f"UserKnownHostsFile={known_hosts}", "git@github.com"],
                                capture_output=True, text=True, timeout=120, check=False)
        greeting = f"Hi {login}! You've successfully authenticated, but GitHub does not provide shell access."
        if result.returncode != 1 or greeting not in (result.stdout + result.stderr).splitlines():
            raise RuntimeError("GitHub SSH authentication did not confirm your account. Unlock 1Password and retry.")


def verify_signing(public_key):
    """Exercise the configured Git signer without creating a commit in a user's repo."""
    signing_configuration()
    with tempfile.TemporaryDirectory(prefix="tenkr-signing-check-") as directory:
        root = Path(directory)
        allowed = root / "allowed_signers"
        # A fixed principal avoids interpreting an email address as allowed-signers syntax.
        allowed.write_text(f"tenkr-onboarding {public_key}\n")
        repo = root / "repository"
        command("git", "init", "--quiet", "--template=", str(repo))
        command("git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
                "commit", "--allow-empty", "--no-verify", "-m", "Verify workstation signing")
        # Verify with OpenSSH independently of the configured signing application.
        command("git", "-C", str(repo), "-c", "gpg.ssh.program=ssh-keygen",
                "-c", f"gpg.ssh.allowedSignersFile={allowed}", "verify-commit", "HEAD")


def configure(vault, home=None):
    name, email = git_identity()
    if not re.fullmatch(r"[A-Za-z0-9 _.-]+", vault) or not name.strip() or "@" not in email:
        raise ValueError("Provide a vault name or ID, your name, and your Git email address.")
    signer = shutil.which("op-ssh-sign")
    if signer is None:
        raise RuntimeError("The 1Password SSH signing program is not installed.")
    home = Path.home() if home is None else Path(home)
    receipt = home / ".config/10kr/workstation-setup/signing-verification.json"
    receipt.unlink(missing_ok=True)
    login = json.loads(command("gh", "api", "user"))["login"]
    verify_email(email)
    keys = {}
    for role in ("authentication", "signing"):
        title = f"10kR GitHub {login} {role}"
        item, key = ensure_item(vault, title)
        register(key, role, title)
        keys[role] = (item, key)
    if keys["authentication"][1] == keys["signing"][1]:
        raise RuntimeError("Authentication and signing must use different keys.")
    ssh = home / ".ssh"
    ssh.mkdir(mode=0o700, exist_ok=True)
    for role, (_, key) in keys.items():
        filename = "tenkr-github-authentication.pub" if role == "authentication" else "tenkr-git-signing.pub"
        write_config(ssh / filename, key + "\n")
    config = ssh / "config"
    old_config = config.read_text() if config.exists() else ""
    header = "# 10kR 1Password SSH agent\n"
    if not old_config.startswith(header):
        write_config(config, header + "Host github.com\n  IdentityFile ~/.ssh/tenkr-github-authentication.pub\n"
                          "  IdentitiesOnly yes\nHost *\n  IdentityAgent ~/.1password/agent.sock\n\n" + old_config)
    agent = home / ".config/1Password/ssh/agent.toml"
    agent.parent.mkdir(parents=True, exist_ok=True)
    existing = agent.read_text() if agent.exists() else ""
    parsed = tomllib.loads(existing)
    entries = parsed.get("ssh-keys", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise RuntimeError("The 1Password agent configuration has an invalid SSH key list.")
    selected = {(entry.get("item"), entry.get("vault")) for entry in entries}
    additions = "".join(f'\n[[ssh-keys]]\nitem = {json.dumps(item)}\nvault = {json.dumps(vault)}\n'
                        for item, _ in keys.values() if (item, vault) not in selected)
    if additions:
        write_config(agent, existing + additions)
    for setting, value in (("user.name", name), ("user.email", email), ("gpg.format", "ssh"),
                           ("gpg.ssh.program", signer),
                           ("user.signingkey", str(ssh / "tenkr-git-signing.pub")),
                           ("commit.gpgsign", "true"), ("tag.gpgsign", "true")):
        command("git", "config", "--global", setting, value)
    verify_authentication(login, home)
    verify_signing(keys["signing"][1])
    receipt.parent.mkdir(parents=True, exist_ok=True)
    write_config(receipt, json.dumps({"key": keys["signing"][1], "settings": signing_configuration()}))
    return keys
