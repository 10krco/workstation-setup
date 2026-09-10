# Tailscale access during first-login setup

Tailscale SSH has its own authorization path and does not use OpenSSH's PAM
account gate. First-login setup therefore withholds both Tailscale SSH and
operator access. An operator can enable SSH themselves, so withholding only the
SSH preference would not enforce the enrollment boundary.

The active local managed user asks the root service to prepare networking. The
service removes operator access, disables Tailscale SSH, verifies those settings,
and starts the connection. The GUI reads status and opens Tailscale's sign-in URL.
It does not receive operator privileges. The root service verifies the required
tailnet and the restricted preferences for the GUI's network step.

Only after all required account checks and the final active-session/system checks
succeed does privileged completion enable and verify operator access and SSH.
The completion record is prepared and synced before enabling remote access, then
atomically published. An enablement or publication error revokes remote access
and removes completion. A lost successful reply can be retried using the already
published protected root record.

This assumes a fresh image starts without a preexisting connected Tailscale state.
It is not a migration that instantly revokes existing remote sessions. Abrupt
process termination between enabling remote access and publishing completion
still needs recovery/boot integration testing. All account checks have passed
before that transition, but its interrupted-state behavior is not yet a verified
shipping guarantee.

The real Tailscale VM checks that an unprivileged user can read status but cannot
enable SSH or grant themselves operator access, that explicit root enablement
works, and that restriction revokes those capabilities. No real tailnet account
is used. Unit tests cover required-tailnet checks, premature privilege rejection,
enablement failure, completion-publication failure, and rollback.
