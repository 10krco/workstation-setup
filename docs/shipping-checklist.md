# Shipping acceptance criteria

The first supported image targets the 10kR ThinkPad T14 Gen 7 AMD. This list is
the acceptance boundary for shipping, not a statement that the current scaffold
is complete. Record evidence for each item before enabling the module in the
fleet's fresh-install configuration.

- [ ] Image provisioning creates the intended account with a supplied temporary
      password, enables enrollment for that account, and preserves later password
      changes across fleet deployments.
- [ ] First login starts only the full-screen setup session. Closing the app,
      crashing it, logging out, or rebooting resumes incomplete enrollment.
- [ ] Switching sessions or logging in through a console cannot skip required
      enrollment. The administrator recovery procedure is documented and tested.
- [ ] A user with no network can connect to Wi-Fi through the GUI and retry.
- [ ] The user sets a new password in the GUI; the old password stops working.
      The replacement survives reboot. Failed operations remain retryable.
- [ ] Fingerprint enrollment uses the T14 reader, provides scan feedback, supports
      retry, and verifies the enrolled print. Missing hardware follows an explicit
      optional-step policy rather than reporting success.
- [ ] The user signs into 1Password and enables CLI integration and its SSH agent.
      The application verifies both and explains any settings that need interaction.
- [ ] Enrollment creates or reuses separate authentication and commit-signing SSH
      keys in the selected 1Password vault without exporting private keys.
- [ ] SSH uses the 1Password agent after future logins. Git has the user's identity,
      SSH signing configuration, and signing key, with signing enabled by default.
- [ ] The user's GitHub account contains both public keys in their appropriate
      authentication/signing registrations. Retry does not create duplicates.
      Actual SSH authentication and a signed test commit verify the setup.
- [ ] An encrypted GNOME keyring is created or migrated, its password is stored in
      1Password, and a later non-password login unlocks it after 1Password unlocks.
- [ ] The workstation joins the intended Tailscale network through the GUI; local
      operator access and Tailscale SSH are verified. Retries are safe.
- [ ] The user can optionally select a Home Manager GitHub flake and output, review
      the immutable source revision, activate it, or skip personalization. Failure
      preserves the prior generation. No dirty local source is activated.
- [ ] Completion independently verifies required settings and writes authoritative
      state through the privileged service. Editing user-owned cache files cannot
      unlock the desktop. The next login starts the intended normal desktop.
- [ ] Browser and 1Password interactions work inside the setup session, including
      focus, returning to setup, portal use, and graphical authentication prompts.
- [ ] Secrets are absent from command arguments, logs, committed files, screenshots,
      and enrollment records. Privileged operations reject other accounts and
      remote/inactive callers.
- [ ] VM tests cover a fresh account, interruptions, errors, completion, subsequent
      login, and fleet reactivation; the full flow is exercised on the target T14.
- [ ] The tested public app revision is merged and pinned through a reviewed
      `nixos-config` PR; fleet GitOps deploys the system configuration.

## Evidence so far

The password backend has unit coverage for incorrect credentials, unconfigured
accounts, invalid input, command failure, repeat changes, and caller-session
authorization. Its VM check exercises real PAM and password persistence. These
checks do not yet prove the complete graphical enrollment flow or its login gate.
