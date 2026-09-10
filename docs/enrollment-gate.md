# Enrollment login boundary

The configured `managedUsers` list is embedded in the immutable session router
and PAM account helper. Missing membership cache files cannot send a managed
user to the normal desktop. Both paths require a regular, root-owned completion
file at `/var/lib/10kr-workstation-setup/completed/USERNAME`; the file and all
parent directories must be protected against group/other writes and symlinks.
User-owned GUI progress files are not authoritative.

The PAM check runs before sufficient account rules in `login`, `sshd`, `sudo`,
`sudo-i`, `su`, and `su-l`. It checks both the target account and PAM's requesting
account, preventing an incomplete user from escaping through sudo to root.
The helper uses the final occurrences of the PAM item variables because
[`pam_exec` appends trusted items after its inherited PAM environment](https://github.com/linux-pam/linux-pam/blob/master/modules/pam_exec/pam_exec.c).
Tests inject conflicting environment values to verify they cannot replace the
actual target or requesting account.
GDM remains available to start the setup session and the setup password service
remains available to replace the initial password. Root cannot be a managed user.

Recovery requires a separately provisioned administrator account or root access
through the organization's recovery process. These unmanaged accounts retain
console access. An administrator can repair the enrollment configuration or
state; removing a completion marker sends a managed user back to setup on its
next login. This does not terminate an already running session. Do not instruct
users to create completion markers as a substitute for enrollment verification.

The VM check exercises real PAM account calls, real passwordless sudo denial and
subsequent success, missing and forged markers, unprotected parent directories,
unmanaged recovery access, and persistence across reboot. Module evaluation also
checks that the PAM hooks are present alongside the restricted GDM session list.

This boundary is one part of the shipping checklist. The privileged completion
verifier is connected to the GUI (see `completion-verification.md`). Polkit authorization, Tailscale
SSH (which does not use the OpenSSH PAM stack), and arbitrary user code run by
optional Home Manager activation need their own integration review and tests.
Do not enable enrollment on shipped images until the full acceptance checklist
passes. This is not an application sandbox or protection against someone who
already has administrator credentials or control of the operating system.
