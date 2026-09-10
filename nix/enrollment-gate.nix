{ pkgs, managedUsers }:
pkgs.writeScript "tenkr-enrollment-account-gate" ''
  #!${pkgs.python3}/bin/python3 -I
  import json
  from pathlib import Path
  import stat
  import sys

  managed = json.loads(${builtins.toJSON (builtins.toJSON managedUsers)})
  # The router supplies its user explicitly. PAM supplies both the target and
  # requesting account, so sudo/su cannot escape enrollment by targeting root.
  users = sys.argv[1:]
  if not users:
      # pam_exec appends trusted PAM items after the PAM environment. Preserve
      # the LAST occurrence: Python's os.environ keeps the first duplicate.
      environment = dict(entry.split(b"=", 1) for entry in
                         Path("/proc/self/environ").read_bytes().split(b"\0") if b"=" in entry)
      # GDM includes login's account stack. It must authenticate incomplete
      # users so the only advertised graphical session can run the router.
      # Read the authoritative PAM_SERVICE item, never an inherited override.
      if environment.get(b"PAM_SERVICE") in (b"gdm-password", b"gdm-fingerprint"):
          sys.exit(0)
      users = [environment.get(key, b"").decode("utf-8", "surrogateescape")
               for key in (b"PAM_USER", b"PAM_RUSER")]
  for user in users:
      if user not in managed:
          continue
      marker = Path("/var/lib/10kr-workstation-setup/completed") / user
      try:
          metadata = marker.lstat()
          valid = (stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
                   and not metadata.st_mode & 0o022)
          for parent in marker.parents:
              metadata = parent.lstat()
              valid = valid and (stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                                 and not metadata.st_mode & 0o022)
      except OSError:
          valid = False
      if not valid:
          print("Complete workstation setup through the graphical login first.")
          sys.exit(1)
''
