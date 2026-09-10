# Final verification

Finish setup calls the system D-Bus `Complete` method from the active local
Wayland session. The service accepts no progress assertions from the GUI. It
checks the configured managed-user list, the root-owned password-change record,
fprintd's enrolled fingers for that account, and the running Tailscale network,
operator, and SSH preferences. `tailnetName` must identify the intended network;
the GUI uses the same generated policy when checking its Tailscale step.

A transient systemd service then runs the installed verifier as that user, with
a deliberately constructed environment. It checks internet connectivity and
1Password access, reads both public keys from 1Password and GitHub, verifies SSH
authentication and a real signed commit, proves the keyring password works, runs
the daily unlock service, and queries Chrome's live account/sync state. It never
uses a GUI completion receipt as proof. The verifier does not export private SSH
keys. It emits only failed step identifiers; command output and exception details
do not cross back to the root service.

The transient unit has a 15-minute runtime limit and a cgroup containing its
descendants, including Chrome. It runs outside the root service's home-directory
restriction, under the user's UID, and cannot write the root completion state.
The root service rechecks the caller's active local session and system state
after interactive verification, then atomically publishes the completion marker.
Failures leave the user in setup. After successful completion, the router starts
the configured normal desktop when the setup compositor exits.

The account checks verify current enrollment, not continuing compliance after
onboarding. A user can later change or revoke their own account configuration.
This also does not attempt to sandbox arbitrary user code in a Home Manager
flake or prevent a user with administrator credentials from altering the OS.

Tests cover failed verification, forged cache state, changed system state,
session loss, atomic publication, and retry. The completion VM exercises a real
transient systemd worker under the user account and verifies it cannot write
root state or inherit an ambient 1Password token. The isolated real keyring test
rejects an incorrect password even when the collection is already unlocked.
GUI tests verify that only a successful service reply closes setup.

Shipping still requires the full acceptance checklist: actual first-login Cage
window/Polkit behavior, Tailscale SSH and privilege-escalation policy during
enrollment, live account authorization, and the complete target-T14 workflow.
