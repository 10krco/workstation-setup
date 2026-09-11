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
from .github_auth import auth_environment


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


def command(*args, discard=False, timeout=120):
    if args[:2] == ("gh", "api"):
        args = (*args[:2], "--hostname", "github.com", *args[2:])
    result = subprocess.run(args, stdout=subprocess.DEVNULL if discard else subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=timeout, check=False,
                            env=auth_environment() if args[0] == "gh" else None)
    if result.returncode:
        operation = next((value for value in args[1:] if value in {
            "api", "read", "item", "vault", "config", "init", "commit", "verify-commit"
        }), "operation")
        raise RuntimeError(f"{args[0]} {operation} failed. Verify account access and retry.")
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


def signing_configuration(timeout=120):
    name, email = git_identity()
    settings = {}
    for setting, expected in (("user.name", name), ("user.email", email),
                              ("gpg.format", "ssh"), ("commit.gpgsign", "true"),
                              ("tag.gpgsign", "true")):
        settings[setting] = command("git", "config", "--global", "--get", setting, timeout=timeout).strip()
        if settings[setting] != expected:
            raise RuntimeError("Git identity or signing settings do not match the workstation policy.")
    for setting in ("user.signingkey", "gpg.ssh.program"):
        settings[setting] = command("git", "config", "--global", "--get", setting, timeout=timeout).strip()
    if shutil.which(settings["gpg.ssh.program"]) is None:
        raise RuntimeError("The configured Git signing program is unavailable. Retry GitHub setup to repair it.")
    return settings


def verify_email(email):
    pages = json.loads(command("gh", "api", "--paginate", "--slurp", "user/emails"))
    if not any(item.get("email", "").casefold() == email.casefold() and item.get("verified") is True
               for page in pages for item in page):
        raise RuntimeError(f"Add and verify {email} at https://github.com/settings/emails, then retry setup.")


def ssh_identity_locations(home):
    paths = {str(home / ".ssh/config")}
    try:
        result = subprocess.run(["ssh", "-vvG", "git@github.com"], capture_output=True,
                                text=True, timeout=5, check=False)
        paths.update(re.findall(r"Reading configuration data (.+)", result.stderr))
    except (OSError, subprocess.TimeoutExpired):
        pass
    locations = []
    for value in sorted(paths):
        path = Path(value)
        try:
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if re.match(r"\s*IdentityFile(?:\s|=)", line, re.IGNORECASE):
                    locations.append(f"{path}:{number}: {line.strip()}")
        except (OSError, UnicodeError):
            pass
    return "\n".join(locations) or str(home / ".ssh/config")


def managed_ssh_config(existing):
    header = "# 10kR 1Password SSH agent\n"
    end = "# End 10kR 1Password SSH agent\n"
    managed_block = (header + "Host github.com\n  IdentityFile ~/.ssh/tenkr-github-authentication.pub\n"
                     "  IdentitiesOnly yes\nHost *\n  IdentityAgent ~/.1password/agent.sock\n" + end)
    if header in existing:
        first = existing.index(header)
        if end in existing[first + len(header):]:
            # Remove every complete stale copy, then place one current block at
            # the first copy's position without moving unrelated configuration.
            while header in existing:
                start = existing.index(header)
                finish = existing.find(end, start + len(header))
                if finish < 0:
                    raise RuntimeError("The existing managed SSH block has no boundary. Repair its markers in ~/.ssh/config and retry.")
                existing = existing[:start] + existing[finish + len(end):]
            return existing[:first] + managed_block + existing[first:]
        if first == 0:
            legacy_block, separator, rest = existing[len(header):].partition("\n\n")
            expected = ["Host github.com", "IdentityFile ~/.ssh/tenkr-github-authentication.pub",
                        "IdentitiesOnly yes", "Host *", "IdentityAgent ~/.1password/agent.sock"]
            lines = [line.strip() for line in legacy_block.splitlines() if line.strip()]
            if lines != expected[:len(lines)]:
                raise RuntimeError("The existing managed SSH block has no boundary. Add a blank line before personal settings in ~/.ssh/config and retry.")
            existing = rest
        else:
            raise RuntimeError("The existing managed SSH block has no boundary. Repair its markers in ~/.ssh/config and retry.")
    return managed_block + "\n" + existing


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
    if [expand(value) for value in options.get("identityfile", [])] != [identity]:
        raise RuntimeError("Conflicting IdentityFile settings apply to GitHub. Inspect these directives, preserve keys for other hosts, and retry:\n"
                           + ssh_identity_locations(home))
    if (options.get("hostname") != ["github.com"] or options.get("identitiesonly") != ["yes"]
            or [expand(value) for value in options.get("identityagent", [])] != [agent]
            or [expand(value) for value in options.get("identityfile", [])] != [identity]):
        raise RuntimeError("SSH configuration does not select the workstation 1Password agent and authentication key.")
    metadata = json.loads(command("gh", "api", "meta"))
    host_keys = [key for key in metadata.get("ssh_keys", []) if isinstance(key, str)
                 and re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+", key)]
    if not host_keys:
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
    account = json.loads(command("gh", "api", "user"))
    login = account.get("login") if isinstance(account, dict) else None
    if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", login):
        raise RuntimeError("GitHub did not return the signed-in account name. Sign in again and retry.")
    verify_email(email)
    keys = {}
    for role in ("authentication", "signing"):
        title = f"10kR GitHub {login} {role}"
        item, key = ensure_item(vault, title)
        keys[role] = (item, key)
    if keys["authentication"][1] == keys["signing"][1]:
        raise RuntimeError("Authentication and signing must use different keys.")
    for role, (_, key) in keys.items():
        register(key, role, f"10kR GitHub {login} {role}")
    ssh = home / ".ssh"
    ssh.mkdir(mode=0o700, exist_ok=True)
    for role, (_, key) in keys.items():
        filename = "tenkr-github-authentication.pub" if role == "authentication" else "tenkr-git-signing.pub"
        write_config(ssh / filename, key + "\n")
    config = ssh / "config"
    old_config = config.read_text() if config.exists() else ""
    updated_config = managed_ssh_config(old_config)
    if updated_config != old_config:
        write_config(config, updated_config)
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
