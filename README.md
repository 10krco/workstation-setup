# 10kR Workstation Setup

`workstation-setup` is the first-login enrollment application for 10kR-managed
NixOS workstations. It owns interactive setup that cannot be completed while a
machine is imaged, including the user's password, fingerprints, 1Password,
GitHub SSH keys and signing, GNOME Keyring, Tailscale, and an optional Home
Manager remote.

The application is designed as a resumable state machine. It records only
non-secret completion state under `~/.config/10kr/workstation-setup`; private
keys and keyring passwords remain in 1Password.

## Development

```console
nix develop
python -m unittest discover -s tests
tenkr-workstation-setup
```

The flake exports `packages.<system>.default` and `nixosModules.default`.
