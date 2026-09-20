# NixOS provisioning bootstrap

This public launcher performs the small handoff needed before the private
`10krco/nixos-config` provisioning scripts are available. All installation,
disk-safety, credential, and finalization behavior remains in that private
repository.

## Install the first machine locally

Boot the official NixOS minimal ISO in UEFI mode, connect networking, and run:

```console
curl -fsSL https://raw.githubusercontent.com/10krco/workstation-setup/main/bootstrap.sh | sh
```

The launcher opens a temporary Nix shell, authenticates the 1Password CLI,
retrieves that host's repository-read token, clones the current reviewed
`nixos-config/main`, verifies the checkout, and hands control to
`scripts/provision-target install-local`. Choose `local` and enter the hostname
when prompted. It accepts no revision argument.

## Prepare a later machine for nixos-anywhere

Start `scripts/provision-admin install-remote HOSTNAME` on the administrator
machine. When it prints an ephemeral SSH public key, run this on the target ISO:

```console
curl -fsSL https://raw.githubusercontent.com/10krco/workstation-setup/main/bootstrap.sh | sh
```

Choose `remote`, then paste the public key. The launcher starts temporary ISO
SSH access and prints the target addresses and host-key fingerprint. Enter those
values only into the waiting administrator command and compare the fingerprint
at the target console.

The launcher does not format disks, install NixOS, persist credentials, select a
configuration revision, or reboot a machine.
