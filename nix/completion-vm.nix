{ pkgs, package }:
let
  verifier = pkgs.writeScript "test-enrollment-verifier" ''
    #!${pkgs.python3}/bin/python3 -I
    import os, pwd
    from pathlib import Path
    assert os.getuid() != 0
    assert pwd.getpwuid(os.getuid()).pw_name == "alice"
    assert os.environ["HOME"] == "/home/alice"
    assert "OP_SERVICE_ACCOUNT_TOKEN" not in os.environ
    assert Path.cwd() == Path("/home/alice")
    assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    try:
        Path("/var/lib/10kr-workstation-setup/completed/forged").touch()
    except PermissionError:
        pass
    else:
        raise AssertionError("verification worker could write root state")
    print("[]")
  '';
  exercise = pkgs.writeText "exercise-completion.py" ''
    import os, sys
    from pathlib import Path
    sys.path.insert(0, "${package}/lib/tenkr-workstation-setup")
    from tenkr_workstation_setup.completion import complete, worker, published
    root = Path("/var/lib/10kr-workstation-setup")
    for directory in ("managed-users", "password-set", "completed"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for directory in ("managed-users", "password-set"):
        (root / directory / "alice").touch()
    os.environ["OP_SERVICE_ACCOUNT_TOKEN"] = "must-not-reach-worker"
    run = lambda: worker("alice", "wayland-0", "${verifier}",
                         "${pkgs.systemd}/bin/systemd-run", "${pkgs.systemd}/bin/systemctl")
    assert run() == []
    assert not (root / "completed/alice").exists()
    assert not published("alice")
    assert complete("alice", lambda: ["chrome"], lambda user: [], lambda: True) == ["chrome"]
    assert not (root / "completed/alice").exists()
    assert complete("alice", run, lambda user: [], lambda: True) == []
    assert (root / "completed/alice").stat().st_uid == 0
    assert (root / "completed/alice").read_text() == "1\n"
    assert published("alice")
  '';
in
pkgs.testers.runNixOSTest {
  name = "workstation-privileged-completion";
  nodes.machine = {
    users.users.alice = {
      isNormalUser = true;
      uid = 1000;
      initialPassword = "test-password";
    };
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.succeed("${pkgs.python3}/bin/python3 ${exercise}")
  '';
}
