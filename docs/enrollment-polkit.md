# Privileged desktop actions during enrollment

An early Polkit rule checks the same protected completion state as the session
router and PAM gate. Until completion, managed users cannot authorize arbitrary
desktop administration, including through their membership in `wheel`.

Local active sessions can still request the network, fingerprint, and basic
power-management operations needed during setup. These requests continue to the
ordinary policy; the enrollment rule does not itself approve them. The existing
workstation rules permit the required network and fingerprint operations.
1Password unlock, CLI authorization, and SSH-agent authorization also continue to
1Password's policy, which retains its authentication requirements.

Unmanaged recovery accounts and completed users retain normal Polkit policy.
Missing or unreadable enrollment state fails closed. The rule precedes regular
NixOS authorization rules and reloads when its generated content changes.
The module also rejects root-equivalent Nix daemon trust for non-root users.

The VM exercises actual Polkit requests from an incomplete `wheel` user,
unmanaged recovery access, a later permissive rule, forged GUI state, valid
completion, removal of completion, and preservation of authentication for an
allowed 1Password action. Inactive network requests are denied. Active local
Wi-Fi/fingerprint dialogs and actual 1Password authentication still require the
full graphical acceptance test.

Tailscale SSH has a separate authorization path and is not protected by this
Polkit rule or OpenSSH's PAM stack. Its enrollment-time restrictions remain part
of the shipping checklist.
