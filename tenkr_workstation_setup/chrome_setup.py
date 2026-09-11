"""Inspect Chrome's live work account and sync settings without accessing tokens."""
import json
from pathlib import Path
import shutil
from .identity import git_identity
from .ssh_setup import write_config


ABOUT_EXPRESSION = """(async () => {
  const cr = await import('chrome://resources/js/cr.js');
  return await new Promise(resolve => {
    const listener = cr.addWebUiListener('onAboutInfoUpdated', info => {
      cr.removeWebUiListener(listener);
      const names = ['Username', 'Transport State', 'User Actionable Error',
                     'Setup In Progress', 'Auth Error'];
      resolve(Object.fromEntries(info.details.flatMap(section => section.data)
        .filter(stat => names.includes(stat.stat_name))
        .map(stat => [stat.stat_name, stat.stat_value])));
    });
    chrome.send('requestDataAndRegisterForUpdates');
  });
})()"""

PREFS_EXPRESSION = """(async () => {
  const cr = await import('chrome://resources/js/cr.js');
  return await new Promise(resolve => {
    const listener = cr.addWebUiListener('sync-prefs-changed', prefs => {
      cr.removeWebUiListener(listener);
      resolve(Object.fromEntries(Object.entries(prefs).filter(([key]) =>
        /(?:Registered|Synced|Managed)$/.test(key) ||
        ['syncAllDataTypes', 'passphraseRequired', 'trustedVaultKeysRequired',
         'localSyncEnabled'].includes(key))));
    });
    chrome.send('SyncPrefsDispatch');
  });
})()"""


def validate_account(about, email):
    if about.get("Username", "").casefold() != email.casefold():
        raise RuntimeError(f"Sign in to the Chrome work profile using {email}.")
    if (about.get("Transport State") != "Active" or about.get("Setup In Progress") is not False
            or about.get("User Actionable Error") != "None"
            or not about.get("Auth Error", "").startswith("OK since ")):
        raise RuntimeError("Finish Chrome sign-in and sync setup, then retry verification.")


def validate(about, prefs, email):
    validate_account(about, email)
    if prefs.get("localSyncEnabled") is not False:
        raise RuntimeError("Chrome must sync to your work account rather than a local backend.")
    if any(prefs.get(key) is not False for key in ("passphraseRequired", "trustedVaultKeysRequired")):
        raise RuntimeError("Complete Chrome's sync encryption recovery prompt, then retry.")
    registered = {key[:-10] for key, value in prefs.items() if key.endswith("Registered") and value is True}
    required = {"bookmarks", "preferences", "extensions", "tabs", "history", "autofill", "passwords"}
    if not required.issubset(registered):
        raise RuntimeError("Chrome has not registered the required profile sync settings yet.")
    if any(prefs.get(key + "Synced") is not True for key in registered):
        raise RuntimeError("Enable all available Chrome sync categories. Your Workspace administrator may need to allow disabled categories.")


def verify(browser):
    _, email = git_identity()
    targets = []
    try:
        target, session = browser.page("chrome://sync-internals")
        targets.append(target)
        about = browser.evaluate(session, ABOUT_EXPRESSION)
        if not isinstance(about, dict) or about.get("Username", "").casefold() != email.casefold():
            raise RuntimeError(f"Sign in to the Chrome work profile using {email}.")
        validate_account(about, email)
        target, session = browser.page("chrome://settings")
        targets.append(target)
        prefs = browser.evaluate(session, PREFS_EXPRESSION)
        if not isinstance(prefs, dict):
            raise RuntimeError("Chrome could not report the profile's sync settings.")
        validate(about, prefs, email)
        return email
    finally:
        for target in targets:
            try:
                browser.call("Target.closeTarget", {"targetId": target})
            except (OSError, RuntimeError):
                pass


def profile_path():
    return Path.home() / ".config/10kr/chrome-work"


def record(browser):
    email = verify(browser)
    executable = shutil.which("google-chrome")
    if executable is None:
        raise RuntimeError("Google Chrome is not installed.")
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    desktop = ("[Desktop Entry]\nType=Application\nName=10kR Work Browser\n"
               "Comment=Google Chrome with your work profile\nIcon=google-chrome\n"
               f"Exec={quote(executable)} {quote('--user-data-dir=' + str(profile_path()))} %U\n"
               "Terminal=false\nCategories=Network;WebBrowser;\n")
    write_config(Path.home() / ".local/share/applications/10kr-work-browser.desktop", desktop)
    write_config(Path.home() / ".config/10kr/workstation-setup/chrome-verification.json",
                 json.dumps({"email": email, "profile": str(profile_path()),
                             "version": browser.call("Browser.getVersion")["product"]}))
