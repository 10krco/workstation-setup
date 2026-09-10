# 10kR Workstation Setup

`workstation-setup` is the first-login enrollment application for 10kR-managed
NixOS workstations. It owns interactive setup that cannot be completed while a
machine is imaged, including the user's password, fingerprints, 1Password,
GitHub SSH keys and signing, GNOME Keyring, Tailscale, and an optional Home
Manager remote.

The application is designed as a resumable state machine. GDM exposes only its
full-screen router session to managed users until root-owned enrollment state
records completion. Private keys and keyring passwords remain in 1Password.

## Development

```console
nix develop
python -m unittest discover -s tests
tenkr-workstation-setup
```

The flake exports `packages.<system>.default` and `nixosModules.default`.

The NixOS module enables the 1Password CLI and desktop application, including
their security wrappers and Polkit ownership for managed users. The host's
Nixpkgs configuration must permit the unfree `1password` and `1password-cli`
packages. The application retains the system wrapper paths so CLI integration
uses the installed security wrapper rather than an unwrapped store binary.
