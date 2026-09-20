# 10kr NixOS workstation provisioning

Boot the official NixOS minimal ISO in UEFI mode, connect it to the network, and run this command from the `nixos` console user:

```sh
curl -fsSL https://raw.githubusercontent.com/10krco/workstation-setup/main/provision.sh | sh
```

The launcher creates a temporary environment containing GitHub CLI, OpenSSH, and tmux. It authenticates the administrator with GitHub, authorizes only that administrator's published GitHub SSH keys, starts an ephemeral SSH server on port 2222, and launches the private fleet provisioner in a tmux session. Password authentication and root SSH login remain disabled.

The launcher refuses to run outside a booted NixOS installation ISO and invokes
the private provisioner at a reviewed, immutable commit.

Before entering any provisioning or recovery secret over SSH, compare the host-key fingerprint displayed by the SSH client with the fingerprint printed on the ISO console.

The private provisioner requires a candidate machine entry in `10krco/nixos-config`. It checks UEFI, TPM 2.0, hardware assignment, and eligible internal disks before accepting the exact confirmation `ERASE <machine-id>`. Secrets are read from `/dev/tty`; provisioning and recovery values are stored in the `Provisioning` 1Password vault.

After installation, review and merge the generated enrollment/promotion pull request before booting the installed system. The PR contains only the installation UUID, machine age recipient, and read-only deploy-key ID. The installed system refuses GitOps promotion if its local installation UUID does not match the canonical configuration.

If enrollment PR creation is interrupted after installation, mount the installed root at `/mnt` and rerun the launcher. Then use the provisioner's `--resume-enrollment <machine-id>` option.

This repository intentionally contains only this document and `provision.sh`. It does not build or publish installation media; use the official NixOS minimal ISO.
