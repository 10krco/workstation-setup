# Encrypted keyring enrollment

The GUI creates or reuses a workstation-specific Password item in the selected
1Password vault. Password generation happens inside 1Password; creation output
is discarded. The password is read into process memory and sent to GNOME Keyring
over the private user session bus. It is never placed in command arguments,
configuration files, or progress records. The setup application disables core
dumps because its password forms and enrollment workers handle credentials.

If a login keyring exists, the user can provide its current password to migrate
it while preserving application secrets. A retry first checks whether migration
already succeeded. A fresh keyring is created with the `login` identifier because
GNOME fixes that alias rather than allowing it to be assigned through SetAlias.
An existing default collection is preserved.

After migration, the GUI saves only the 1Password secret reference and starts the
workstation's `tenkr-onepassword` and `tenkr-gnome-keyring-unlock` user services.
Those services are supplied by the 10kR workstation role in nixos-config. The
progress check requires successful enrollment and an available unlock service;
the reference alone is insufficient. Final privileged completion verification
remains separate pending work.

Run `nix develop --command python tests/run_keyring_runtime.py` for the isolated
runtime test. It uses a disposable home, private session bus, and its own GNOME
Keyring daemon. It verifies creation, retry, rejection of an incorrect current
password, preservation of a saved secret during password migration, and unlocking
with the replacement password after restarting the daemon. It uses test passwords
and does not access a real 1Password account or the host user's keyring.

The complete 1Password approval flow and automatic unlock following a real
non-password login still require target-device acceptance testing.
