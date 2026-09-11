{ pkgs, source }:
let
  python = pkgs.python3.withPackages (p: [ p.dbus-python ]);
  mockOp = pkgs.writeShellScript "fixture-op" ''
    printf x >> "$HOME/op-calls"
    printf %s replacement-test-password
  '';
  unlock = import ./keyring-unlock.nix {
    inherit pkgs;
    inherit (pkgs) lib;
    opExecutable = mockOp;
  };
in
pkgs.runCommand "check-keyring-login-unlock"
  {
    nativeBuildInputs = [
      python
      pkgs.dbus
      pkgs.gnome-keyring
    ];
  }
  ''
    cp -r ${source} source
    chmod -R u+w source
    cd source
    export TENKR_KEYRING_UNLOCK_TEST=${pkgs.lib.getExe unlock}
    python tests/run_keyring_runtime.py
    touch "$out"
  ''
