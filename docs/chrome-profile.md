# Work profile enrollment

The Chrome step uses the work email from `/etc/10kr/workstation-users.json`.
It opens a dedicated persistent user-data directory at
`~/.config/10kr/chrome-work`, so Google sign-in and the organization’s profile
consent happen in Chrome itself. The user enables all available sync categories
and returns to setup for verification. The resulting launcher is named
**10kR Work Browser**. Other existing Chrome profiles are not modified.

During enrollment, Chrome communicates with the setup process through inherited
file descriptors using `--remote-debugging-pipe`. There is no debugging TCP
listener. Verification reads only account and sync status fields from Chrome’s
internal pages; it does not request cookies, tokens, passwords, or sync contents.
The browser closes after successful verification, and the ordinary launcher does
not enable debugging. A still-open work browser from an interrupted setup must
be closed before retrying enrollment.

Verification requires the exact work account, active sync transport, no pending
setup or authentication error, no unresolved encryption recovery, and all
registered sync categories selected. Workspace policies must permit those
categories. Opening a Google website or a browser window does not satisfy the
check. Chrome's diagnostic interfaces are not stable public APIs: unknown or
missing data leaves enrollment incomplete.

The implementation was checked against Chrome 152.0.7977.82 and the corresponding
Chromium sources:

- [Live sync status fields](https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.82/components/sync/service/sync_internals_util.cc)
- [Sync status events](https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.82/components/sync/service/resources/about.ts)
- [Chrome settings sync preferences](https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.82/chrome/browser/ui/webui/settings/people_handler.cc)

The local runtime check starts a disposable signed-out Chrome profile, reads its
live status, rejects completion, and closes its process. It does not exercise a
real Workspace sign-in or consent. Those, plus window switching inside the kiosk,
remain required target-device acceptance tests. The current user-owned receipt is
a progress cache; the pending privileged completion gate must independently
verify browser state and cannot trust this receipt as authority.
