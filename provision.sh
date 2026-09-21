#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  provision.sh local HOST
  provision.sh remote
EOF
}

if (( $# == 0 )); then
  read -r -p 'Provisioning mode [local/remote] (local): ' mode
  mode="${mode:-local}"
  if [[ "$mode" == local ]]; then
    read -r -p 'Hostname: ' host
    set -- local "$host"
  else
    set -- "$mode"
  fi
  unset mode host
fi

case "${1:-}" in
  local)
    [[ $# -eq 2 && "$2" =~ ^([a-z0-9]|[a-z0-9][a-z0-9-]{0,61}[a-z0-9])$ ]] || {
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
trap 'rm -rf -- "$bootstrap_root"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
inner="$bootstrap_root/launcher"

cat >"$inner" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'provision: %s\n' "$*" >&2
  exit 1
}

bootstrap_root="$(dirname "$0")"
installed_authorization=false
started_sshd=false
remote_ready=false

cleanup() {
  unset OP_SESSION || true
  if [[ "${1:-}" == remote && "$remote_ready" != true && "$installed_authorization" == true ]]; then
    sudo rm -f /root/.ssh/authorized_keys || true
  fi
  if [[ "${1:-}" == remote && "$remote_ready" != true && "$started_sshd" == true ]]; then
    sudo systemctl stop sshd || true
  fi
}

local_install() {
  local host=$1
  local session account email accounts
  account="${NIXOS_PROVISIONING_OP_ACCOUNT:-team-10kr.1password.com}"
  if ! op whoami; then
    accounts="$(op account list --format json)" \
      || die "could not inspect configured 1Password accounts"
    if (( $(jq -r 'length' <<<"$accounts") == 0 )); then
      if ! read -r -p '1Password email: ' email || [[ -z "$email" ]]; then
        die "1Password authentication requires an account email"
      fi
      op account add \
        --address "$account" \
        --email "$email" \
        --shorthand tenkr-provisioning \
        || die "failed to add the 1Password account"
      session="$(op signin --account tenkr-provisioning --raw)" \
        || die "1Password authentication failed after adding the account"
    else
      session="$(op signin --raw)" || die "1Password authentication failed"
    fi
    [[ -n "$session" ]] || die "1Password authentication returned an empty session"
    export OP_SESSION="$session"
  fi
  op whoami >/dev/null 2>&1 || die "1Password authentication could not be verified"
  unset session email accounts

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
  (cd "$checkout" && bash scripts/provision-target install-local "$host")
}

remote_access() {
  local public_key
  sudo test -d /sys/firmware/efi || die "target was not booted in UEFI mode"
  findmnt /iso || die "remote access must run from the official NixOS ISO"
  sudo test -f /iso/nix-store.squashfs \
    || die "remote access must run from the official NixOS ISO"
  if sudo test -s /root/.ssh/authorized_keys; then
    die "the live ISO already has root SSH authorization; remove it deliberately before continuing"
  fi
  read -r -p 'Paste the ephemeral administrator SSH public key: ' public_key
  [[ "$public_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+([[:space:]].*)?$ ]] \
    || die "expected one Ed25519 public key"
  local public_key_file="$bootstrap_root/public-key"
  printf '%s\n' "$public_key" >"$public_key_file"
  ssh-keygen -l -f "$public_key_file" \
    || die "expected one valid Ed25519 public key"
  sudo install -d -m 0700 /root/.ssh
  installed_authorization=true
  printf '%s\n' "$public_key" | sudo tee /root/.ssh/authorized_keys
  sudo chmod 0600 /root/.ssh/authorized_keys
  started_sshd=true
  sudo systemctl start sshd
  printf 'Target addresses:\n'
  ip -brief address show scope global
  printf 'Target SSH host-key fingerprint:\n'
  sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
  remote_ready=true
}

operation=$1
trap 'cleanup "$operation"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
case "$operation" in
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
  nixpkgs#age \
  nixpkgs#coreutils \
  nixpkgs#gh \
  nixpkgs#git \
  nixpkgs#iproute2 \
  nixpkgs#jq \
  nixpkgs#openssh \
  nixpkgs#sops \
  nixpkgs#util-linux \
  nixpkgs#_1password-cli \
  --command bash "$inner" "$@"
