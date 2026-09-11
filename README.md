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

Virtual-machine acceptance checks are kept out of pull-request CI. The
graphical Wi-Fi test uses a real virtual WPA access point; run it locally when
changing guided-session Wi-Fi behavior:

```console
nix build -L .#wifi-vm
```

The NixOS module enables the 1Password CLI and desktop application, including
their security wrappers and Polkit ownership for managed users. The host's
Nixpkgs configuration must permit the unfree `1password`, `1password-cli`, and `google-chrome`
packages. The application retains the system wrapper paths so CLI integration
uses the installed security wrapper rather than an unwrapped store binary.

The module supplies Chrome, a GTK portal backend, and a graphical Polkit agent
inside a dedicated Sway session with no desktop launcher or terminal bindings.
The compositor's display environment is published before
starting setup so applications activated through D-Bus can display their windows.
The authentication agent and compositor exit with setup. While a third-party app
is open, a reserved panel on the right provides numbered instructions and a
return button, including when the app requests fullscreen.

1Password integrations must be enabled in the app. Its Linux preferences include
authentication tags for the SSH-agent and CLI switches; setup does not rewrite
these internal settings. The checklist requires a live SSH-agent response and a
successful desktop CLI request, discarding all CLI output. Enabling a preference
or merely creating an agent socket does not mark the step complete.

The default module also installs the daily 1Password/keyring user services needed
by the application-secrets step. For workstations that only need that integration,
import `nixosModules.keyring` and enable `services.tenkr-keyring.enable`; configure
`programs._1password-gui.polkitPolicyOwners` for their users. The services start
only for users with an enrolled secret-reference file. Passwords pass directly
from the system CLI wrapper to GNOME Keyring through a pipe.
