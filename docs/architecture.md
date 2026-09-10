# Architecture

This document describes the target experience. The repository is under active
development and is not ready to enable on shipped machines. Password enrollment,
fingerprint enrollment, and the session router are implemented; account and key
creation, network enrollment, remote personalization, and privileged completion
still require implementation and end-to-end verification.

## Scope

The first supported target is the Lenovo ThinkPad T14 Gen 7 AMD used by the
10kR workstation image. The first successful GDM login starts setup in a single
10kR router session. Later logins resume setup until every required probe passes.
During that lifecycle, the router launches the application full-screen under
Cage instead of launching GNOME or Hyprland.

The installer creates the account with a random one-time password and includes
it in the managed user policy. NixOS uses mutable users, so later fleet
deployments do not overwrite the password selected during setup.

## Components

### User application

The GTK/libadwaita application owns presentation, user input, OAuth handoffs,
progress, and recovery. It never runs as root. It communicates directly with
user-scoped services such as 1Password and GitHub CLI, and with system services
that already expose PolicyKit-aware APIs, including fprintd.

### Privileged service

A small system D-Bus service owns the operations that require root:

- replace the one-time password after authenticating the current session and
  confirming the root-owned marker;
- assign the user as the Tailscale operator and enable Tailscale SSH;
- remove the first-login requirement after all required steps verify.

Its D-Bus policy permits calls only from an active local session. Every method
checks the caller UID against the target account and exposes a narrow operation
instead of arbitrary command execution. Secrets are accepted through D-Bus
method payloads, consumed immediately, and never logged or persisted.

### Login-session enforcement

GDM advertises only the 10kR router session. The module deliberately replaces
the display manager's combined session list, so GNOME and Hyprland cannot be
selected directly from the login screen. The router consults completion state
under `/var/lib/10kr-workstation-setup`, which is writable only by root.

For an incomplete managed user, the router starts Cage without virtual-terminal
switching and runs the setup application as its sole full-screen client. If the
application exits or crashes, Cage exits and GDM regains control; no normal
desktop is present underneath it. After the privileged service verifies every
required step, it atomically records completion. The next login routes to the
configured normal desktop.

This is an enrollment gate for the ordinary local login path. NixOS recovery
boot remains available to administrators so a broken enrollment build cannot
make the machine unrecoverable.

### Enrollment engine

Each step implements the same interface:

1. `probe` reports `complete`, `available`, `blocked`, or `failed` with a
   user-facing explanation.
2. `begin` starts an interactive operation.
3. `cancel` stops a pending operation without corrupting prior state.
4. `verify` checks external state before recording completion.

The application derives truth from the underlying service whenever possible.
Local markers cache only completion that cannot be queried safely. Reopening
the app repeats probes and resumes at the first incomplete required step.

## Enrollment steps

### Password

The password step remains required until a root-owned `password-set/USER` record
exists. The application collects the supplied password and a matching new
password in masked fields. The privileged service derives the account from the
D-Bus sender, checks its active local Wayland session through logind, and verifies
the supplied password using a dedicated password-only PAM service. It feeds the
replacement to `chpasswd` through stdin and records success only after that
command succeeds. A completed account cannot use this API to change its password
again. Passwords are excluded from command arguments, output, and state files.

### Fingerprint

The application calls fprintd over D-Bus. It claims the fixed T14 sensor for the
current user, starts right-index enrollment, renders each `EnrollStatus` signal,
and verifies the stored print before completing. Cancellation and timeout stop
the scan and release the device. The module authorizes enrollment and verification
for active local managed users without granting access to another user's prints.
The target-hardware enrollment and missing-hardware optional-step policy still
need acceptance testing and implementation, respectively.

### 1Password and SSH keys

The application starts 1Password and waits for the user to sign in. It verifies
desktop CLI integration and the SSH-agent socket. If 1Password does not expose
a supported settings API for a required toggle, the page opens the relevant
settings view and blocks until its probe succeeds.

The enrollment engine creates two Ed25519 SSH Key items in the user's selected
vault through `op`: one for authentication and one for signing. It writes a
local 1Password agent configuration containing only their item IDs and writes
their public halves to `~/.ssh`. Private keys never leave 1Password.

### GitHub

GitHub CLI opens the browser-based device flow with the scopes needed to manage
authentication and signing keys. The application compares public-key material
before creating either registration, so retries cannot create duplicates. It
then verifies `ssh -T git@github.com` and creates and verifies a signed commit in
a temporary repository.

### GNOME Keyring

When a GNOME login collection exists, the application creates a generated
Password item in 1Password and changes the collection master password once. A
user service retrieves that password after future non-password logins and
unlocks the collection through GNOME Keyring's D-Bus interface. The local state
contains only the `op://` item reference.

### Tailscale

The application starts Tailscale's browser enrollment. The privileged service
then makes the caller the local operator and enables Tailscale SSH. Completion
requires a `Running` backend and an enabled SSH preference.

### Home Manager

The optional page accepts a GitHub flake URI, evaluates its selected output,
shows the source revision, and activates that immutable remote revision. The
application never activates a dirty local checkout. Failure leaves the prior
Home Manager generation active and the step resumable.

## Fleet integration

The repository exports a package and NixOS module. `nixos-config` pins the
public flake revision, enables the module in the workstation role, and supplies
the supported hardware profile, managed users, normal desktop command, and
required-step policy. The root-owned completion record keeps the kiosk in place
across restarts until every required probe passes.
