{
  pkgs,
  lib,
  opExecutable ? "/run/wrappers/bin/op",
}:
let
  python = pkgs.python3.withPackages (p: [ p.dbus-python ]);
  unlockCollection = pkgs.writeText "tenkr-unlock-login-keyring.py" ''
    import dbus
    import sys

    def unlock():
        password = sys.stdin.buffer.read()
        if not password:
            raise SystemExit("1Password returned an empty keyring password")
        bus = dbus.SessionBus()
        root = bus.get_object("org.freedesktop.secrets", "/org/freedesktop/secrets")
        service = dbus.Interface(root, "org.freedesktop.Secret.Service")
        collection = service.ReadAlias("login", timeout=15)
        if str(collection) == "/":
            raise SystemExit("No login keyring collection was found")
        _, session = service.OpenSession("plain", "", timeout=15)
        try:
            secret = dbus.Struct((dbus.ObjectPath(session), dbus.ByteArray(b""),
                                  dbus.ByteArray(password), dbus.String("text/plain")),
                                 signature="oayays")
            dbus.Interface(root, "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface").UnlockWithMasterPassword(
                collection, secret, timeout=15)
        finally:
            dbus.Interface(bus.get_object("org.freedesktop.secrets", session),
                           "org.freedesktop.Secret.Session").Close(timeout=15)

    try:
        unlock()
    except Exception:
        # D-Bus/CLI diagnostics are not a safe channel for secret material.
        raise SystemExit("Could not unlock the login keyring") from None
  '';
  attempt = pkgs.writeShellApplication {
    name = "tenkr-keyring-unlock-attempt";
    text = ''
      # The NixOS wrapper preserves the group used for authenticated desktop IPC.
      # Secret values travel through the pipe, never arguments or log output.
      ulimit -c 0
      ${lib.escapeShellArg opExecutable} read --no-newline "$1" 2>/dev/null \
        | ${python}/bin/python ${unlockCollection}
    '';
  };
in
pkgs.writeShellApplication {
  name = "tenkr-gnome-keyring-unlock";
  runtimeInputs = [
    pkgs.coreutils
    pkgs.systemd
  ];
  text = ''
    ulimit -c 0
    reference_file="$HOME/.config/10kr/gnome-keyring-1password-secret-reference"
    reference="$(<"$reference_file")"
    if [[ "$reference" != op://* ]]; then
      echo "Invalid 1Password keyring secret reference." >&2
      exit 1
    fi
    if ! read -r _ collection < <(
      busctl --user call org.freedesktop.secrets /org/freedesktop/secrets \
        org.freedesktop.Secret.Service ReadAlias s login
    ); then
      echo "Failed to resolve the GNOME login keyring collection." >&2
      exit 1
    fi
    collection="''${collection#\"}"
    collection="''${collection%\"}"
    if [[ "$collection" == "/" ]]; then
      echo "No GNOME login keyring collection was found." >&2
      exit 1
    fi
    locked() {
      busctl --user get-property org.freedesktop.secrets "$collection" \
        org.freedesktop.Secret.Collection Locked
    }
    if [[ "$(locked)" == "b false" ]]; then
      exit 0
    fi
    deadline=$((SECONDS + 290))
    unlocked=false
    while ((SECONDS < deadline)); do
      remaining=$((deadline - SECONDS))
      if ((remaining <= 0)); then break; fi
      # Once the CLI connects, let the user finish its authentication prompt.
      if timeout --kill-after=2 "$remaining" ${lib.getExe attempt} "$reference"; then
        unlocked=true
        break
      fi
      if ((SECONDS + 5 < deadline)); then sleep 5; else break; fi
    done
    if [[ "$unlocked" != true ]]; then
      echo "Could not retrieve the keyring password or unlock GNOME Keyring." >&2
      exit 1
    fi
    if [[ "$(locked)" != "b false" ]]; then
      echo "GNOME Keyring remained locked after the unlock request." >&2
      exit 1
    fi
  '';
}
