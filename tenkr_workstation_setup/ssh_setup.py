"""Idempotent public-key registration; private key material is never requested."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib


def command(*args, discard=False):
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


def configure(vault, name, email, home=None):
    if not re.fullmatch(r"[A-Za-z0-9 _.-]+", vault) or not name.strip() or "@" not in email:
        raise ValueError("Provide a vault name or ID, your name, and your Git email address.")
    signer = shutil.which("op-ssh-sign")
    if signer is None:
        raise RuntimeError("The 1Password SSH signing program is not installed.")
    home = Path.home() if home is None else Path(home)
    login = json.loads(command("gh", "api", "user"))["login"]
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
        (ssh / filename).write_text(key + "\n")
    config = ssh / "config"
    old_config = config.read_text() if config.exists() else ""
    header = "# 10kR 1Password SSH agent\n"
    if not old_config.startswith(header):
        config.write_text(header + "Host github.com\n  IdentityFile ~/.ssh/tenkr-github-authentication.pub\n"
                          "  IdentitiesOnly yes\nHost *\n  IdentityAgent ~/.1password/agent.sock\n\n" + old_config)
    agent = home / ".config/1Password/ssh/agent.toml"
    agent.parent.mkdir(parents=True, exist_ok=True)
    existing = agent.read_text() if agent.exists() else ""
    parsed = tomllib.loads(existing)
    selected = {entry.get("item") for entry in parsed.get("ssh-keys", [])}
    additions = "".join(f'\n[[ssh-keys]]\nitem = {json.dumps(item)}\nvault = {json.dumps(vault)}\n'
                        for item, _ in keys.values() if item not in selected)
    agent.write_text(existing + additions)
    for setting, value in (("user.name", name), ("user.email", email), ("gpg.format", "ssh"),
                           ("gpg.ssh.program", signer),
                           ("user.signingkey", str(ssh / "tenkr-git-signing.pub")),
                           ("commit.gpgsign", "true"), ("tag.gpgsign", "true")):
        command("git", "config", "--global", setting, value)
    return keys
