#!/bin/sh
set -eu

if [ ! -r /dev/tty ] || [ ! -w /dev/tty ]; then
  echo "A controlling terminal is required." >&2
  exit 1
fi
if [ "$(id -u)" -eq 0 ]; then
  echo "Run this launcher as the NixOS ISO's nixos user, not root." >&2
  exit 1
fi
if ! grep -qx 'VARIANT_ID=installer' /etc/os-release \
  || ! command -v findmnt >/dev/null 2>&1 \
  || ! findmnt -rn -M /iso >/dev/null 2>&1 \
  || [ ! -r /iso/nix-store.squashfs ]; then
  echo "This launcher must run from a booted official NixOS installation ISO." >&2
  exit 1
fi
command -v nix >/dev/null 2>&1 || {
  echo "This launcher must run on the official NixOS minimal ISO." >&2
  exit 1
}
command -v sudo >/dev/null 2>&1 || {
  echo "sudo is required on the installation environment." >&2
  exit 1
}

# The single-quoted program must reach the inner Bash unchanged.
# shellcheck disable=SC2016
exec nix shell --extra-experimental-features 'nix-command flakes' \
  nixpkgs#bash nixpkgs#coreutils nixpkgs#gh nixpkgs#git \
  nixpkgs#iptables nixpkgs#openssh nixpkgs#tmux --command bash -euo pipefail -c '
runtime_parent=${XDG_RUNTIME_DIR:?The live user runtime directory is unavailable}
[[ -d "$runtime_parent" && -O "$runtime_parent" ]] || exit 1
runtime=$(mktemp -d "$runtime_parent/10kr-bootstrap.XXXXXXXX")
sshd_pid=
firewall_open=false
cleanup() {
  set +e
  tmux kill-session -t provision 2>/dev/null
  if [[ -n "$sshd_pid" ]]; then sudo kill "$sshd_pid" 2>/dev/null; fi
  if [[ "$firewall_open" == true ]]; then
    sudo iptables -D INPUT -p tcp --dport 2222 -j ACCEPT 2>/dev/null
  fi
  rm -rf -- "$runtime"
}
trap cleanup EXIT HUP INT TERM
chmod 0700 "$runtime"
export GH_CONFIG_DIR="$runtime/gh"
export GIT_CONFIG_GLOBAL="$runtime/gitconfig"
mkdir -m 0700 "$GH_CONFIG_DIR"

if ! gh auth status >/dev/null 2>&1; then
  gh auth login --hostname github.com --git-protocol https --web </dev/tty >/dev/tty
fi
gh auth setup-git
administrator=$(gh api user --jq .login)
gh api "users/$administrator/keys" --paginate --jq ".[].key" >"$runtime/authorized_keys"
[[ -s "$runtime/authorized_keys" ]] || {
  echo "The authenticated GitHub account has no published SSH keys." >&2
  exit 1
}
chmod 0600 "$runtime/authorized_keys"

ssh-keygen -q -t ed25519 -N "" -f "$runtime/ssh_host_ed25519_key"
chmod 0600 "$runtime/ssh_host_ed25519_key"
current_user=$(id -un)
cat >"$runtime/sshd_config" <<EOF
Port 2222
ListenAddress 0.0.0.0
HostKey $runtime/ssh_host_ed25519_key
PidFile $runtime/sshd.pid
AuthorizedKeysFile $runtime/authorized_keys
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin no
AllowUsers $current_user
UsePAM no
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
PermitTunnel no
GatewayPorts no
PermitUserEnvironment no
StrictModes yes
SetEnv PATH=$PATH
Subsystem sftp internal-sftp
EOF
sudo "$(command -v sshd)" -f "$runtime/sshd_config" -E "$runtime/sshd.log"
sshd_pid=$(cat "$runtime/sshd.pid")
sudo iptables -I INPUT -p tcp --dport 2222 -j ACCEPT
firewall_open=true

GH_TOKEN=$(gh auth token)
export GH_TOKEN
export NIX_CONFIG="access-tokens = github.com=$GH_TOKEN"
nix_bin=$(command -v nix)
printf -v provision_command "sudo --preserve-env=GH_TOKEN,NIX_CONFIG,TERM %q run github:10krco/nixos-config/6a56cd3d94b073b6eb3f665ef62f29bf77cb602f#provision" "$nix_bin"
tmux new-session -d -s provision "$provision_command"

echo "Ephemeral key-only SSH is listening on port 2222." >/dev/tty
echo "SSH host key fingerprint: $(ssh-keygen -lf "$runtime/ssh_host_ed25519_key.pub")" >/dev/tty
echo "Connect as $current_user and run: tmux attach -t provision" >/dev/tty
tmux attach-session -t provision </dev/tty >/dev/tty
'
