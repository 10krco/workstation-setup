# Interrupted completion

After live account verification and the final session/system checks, the root
service commits a protected `verified/USERNAME` record. The file and its parent
directories are synced before Tailscale privileges change. GUI receipts cannot
create this record or substitute for its verification.

The final transition enables and verifies Tailscale operator/SSH access, then
publishes `completed/USERNAME`. A normal error revokes remote privileges and
leaves the verified record available for retry. After backend restart, recovery
first restricts remote access for a pending verified user, rechecks root-owned
password enrollment and current system requirements, then finishes the transition.
It does not repeat 1Password/Chrome account authorization that already committed
successfully. These records describe enrollment, not ongoing account compliance.

Completed users retain desktop access. Startup reasserts their authorized
Tailscale preferences because a power failure can persist the completion record
before tailscaled's own state reaches disk. Unverified users are never promoted
by recovery. Verification workers bind to the backend service and stop with it,
preventing orphaned browser or CLI authorization attempts after backend failure.

The VM kills completion immediately after enabling Tailscale, abruptly powers
off, verifies journal persistence, rejects a forged journal and failing system
checks, recovers, then abruptly powers off again and restores the completed
preferences. A separate VM verifies that stopping the backend stops its active
verification worker. No real user accounts or external credentials are used.

Fresh-image provisioning, full graphical session transitions, and the complete
target-T14 flow remain covered by the shipping acceptance checklist.
