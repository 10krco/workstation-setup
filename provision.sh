#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  provision.sh local HOST
  provision.sh remote
EOF
}

case "${1:-}" in
  local)
    [[ $# -eq 2 && "$2" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
      usage
      exit 2
    }
    ;;
  remote)
    [[ $# -eq 1 ]] || {
      usage
      exit 2
    }
    ;;
  *)
    usage
    exit 2
    ;;
esac

umask 077
bootstrap_root="$(mktemp -d "${TMPDIR:-/tmp}/nixos-bootstrap.XXXXXX")"
trap 'rm -rf -- "$bootstrap_root"' EXIT INT TERM
inner="$bootstrap_root/launcher"

cat >"$inner" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'provision: %s\n' "$*" >&2
  exit 1
}

bootstrap_root="$(dirname "$0")"
remote_ready=false

cleanup() {
  unset OP_SESSION || true
  if [[ "${1:-}" == remote && "$remote_ready" != true ]]; then
    sudo rm -f /root/.ssh/authorized_keys >/dev/null 2>&1 || true
    sudo systemctl stop sshd >/dev/null 2>&1 || true
  fi
}

local_install() {
  local host=$1
  local session account email
  account="${NIXOS_PROVISIONING_OP_ACCOUNT:-team-10kr.1password.com}"
  if ! op whoami >/dev/null 2>&1; then
    if session="$(op signin --raw 2>/dev/null)" && [[ -n "$session" ]]; then
      export OP_SESSION="$session"
    else
      if ! read -r -p '1Password email: ' email || [[ -z "$email" ]]; then
        die "1Password authentication requires an account email"
      fi
      session="$(
        op account add \
          --address "$account" \
          --email "$email" \
          --shorthand tenkr-provisioning \
          --signin \
          --raw
      )" || die "1Password authentication failed"
      [[ -n "$session" ]] || die "1Password authentication returned an empty session"
      export OP_SESSION="$session"
    fi
  fi
  unset session email

  export GH_CONFIG_DIR="$bootstrap_root/gh"
  install -d -m 0700 "$GH_CONFIG_DIR"
  local vault="${NIXOS_PROVISIONING_VAULT:-Provisioning}"
  if ! op read --no-newline "op://$vault/$host NixOS provisioning/github-token" \
    | gh auth login --hostname github.com --git-protocol https --with-token; then
    die "failed to retrieve the repository token from 1Password"
  fi

  local checkout="$bootstrap_root/nixos-config"
  gh repo clone 10krco/nixos-config "$checkout" -- --branch main --single-branch
  [[ "$(git -C "$checkout" branch --show-current)" == main ]] \
    || die "nixos-config did not check out main"
  [[ -z "$(git -C "$checkout" status --porcelain)" ]] \
    || die "nixos-config checkout is not clean"
  [[ "$(git -C "$checkout" rev-parse HEAD)" == "$(git -C "$checkout" rev-parse refs/remotes/origin/main)" ]] \
    || die "nixos-config checkout does not match current origin/main"
  bash "$checkout/scripts/provision-target" install-local "$host"
}

remote_access() {
  local public_key
  if sudo test -s /root/.ssh/authorized_keys; then
    die "the live ISO already has root SSH authorization; remove it deliberately before continuing"
  fi
  read -r -p 'Paste the ephemeral administrator SSH public key: ' public_key
  [[ "$public_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+([[:space:]].*)?$ ]] \
    || die "expected one Ed25519 public key"
  sudo install -d -m 0700 /root/.ssh
  printf '%s\n' "$public_key" | sudo tee /root/.ssh/authorized_keys >/dev/null
  sudo chmod 0600 /root/.ssh/authorized_keys
  sudo systemctl start sshd
  printf 'Target addresses:\n'
  ip -brief address show scope global
  printf 'Target SSH host-key fingerprint:\n'
  sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
  remote_ready=true
}

trap 'cleanup "${1:-}"' EXIT INT TERM
case "$1" in
  local) local_install "$2" ;;
  remote) remote_access ;;
esac
INNER
chmod 0700 "$inner"

export NIX_CONFIG="${NIX_CONFIG:+$NIX_CONFIG
}experimental-features = nix-command flakes"
export NIXPKGS_ALLOW_UNFREE=1
nix shell \
  --impure \
  nixpkgs#bash \
  nixpkgs#coreutils \
  nixpkgs#gh \
  nixpkgs#git \
  nixpkgs#iproute2 \
  nixpkgs#openssh \
  nixpkgs#_1password-cli \
  --command bash "$inner" "$@"
