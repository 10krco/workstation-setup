{ pkgs, package }:
let
  python = pkgs.python3.withPackages (p: [ p.python-pam ]);
  exercise = pkgs.writeText "exercise-password-enrollment.py" ''
    import sys
    from pathlib import Path
    import pam
    sys.path.insert(0, "${package}/lib/tenkr-workstation-setup")
    from tenkr_workstation_setup.password_backend import set_password

    root = Path("/var/lib/10kr-workstation-setup")
    authenticate = lambda user, password: pam.pam().authenticate(
        user, password, service="tenkr-workstation-setup")
    if len(sys.argv) > 1:
        assert authenticate("alice", "replacement-test-password")
        assert not authenticate("alice", "initial-test-password")
        assert (root / "password-set/alice").is_file()
        sys.exit(0)
    (root / "managed-users").mkdir(parents=True)
    (root / "managed-users/alice").touch()
    assert authenticate("alice", "initial-test-password")
    try:
        set_password("alice", "incorrect", "replacement-test-password", root,
                     authenticate, "${pkgs.shadow}/bin/chpasswd")
    except PermissionError:
        pass
    else:
        raise AssertionError("incorrect current password accepted")
    assert not (root / "password-set/alice").exists()
    set_password("alice", "initial-test-password", "replacement-test-password", root,
                 authenticate, "${pkgs.shadow}/bin/chpasswd")
    assert authenticate("alice", "replacement-test-password")
    assert not authenticate("alice", "initial-test-password")
    assert (root / "password-set/alice").read_text().strip() == "1"
  '';
in
pkgs.testers.runNixOSTest {
  name = "workstation-password-enrollment";
  nodes.machine = {
    users.users.alice = {
      isNormalUser = true;
      initialPassword = "initial-test-password";
    };
    security.pam.services.tenkr-workstation-setup.text = ''
      auth required ${pkgs.linux-pam}/lib/security/pam_unix.so
      account required ${pkgs.linux-pam}/lib/security/pam_unix.so
    '';
  };
  testScript = ''
    machine.start(allow_reboot=True)
    machine.wait_for_unit("multi-user.target")
    machine.succeed("${python}/bin/python ${exercise}")
    machine.reboot()
    machine.wait_for_unit("multi-user.target")
    machine.succeed("${python}/bin/python ${exercise} verify-after-reboot")
  '';
}
