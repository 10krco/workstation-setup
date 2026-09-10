{ pkgs, package }:
let
  exercise = pkgs.writeText "exercise-enrollment-recovery.py" ''
    import json, os, signal, sys
    from pathlib import Path
    sys.path.insert(0, "${package}/lib/tenkr-workstation-setup")
    from tenkr_workstation_setup.completion import complete, recover, published, protected_record
    from tenkr_workstation_setup.network import command, restrict, enable_remote
    root = Path("/var/lib/10kr-workstation-setup")
    executable = "${pkgs.tailscale}/bin/tailscale"
    enable = lambda: enable_remote("alice", executable)
    rollback = lambda: restrict(executable)
    if sys.argv[1] == "crash":
        for kind in ("managed-users", "password-set"):
            (root / kind).mkdir(parents=True, exist_ok=True)
            (root / kind / "alice").touch()
        os.sync()
        rollback()
        def crash_after_enable():
            enable()
            os.kill(os.getpid(), signal.SIGKILL)
        complete("alice", lambda: [], lambda user: [], lambda: True,
                 activate_network=crash_after_enable, rollback_network=rollback)
        raise AssertionError("crash was not injected")
    elif sys.argv[1] == "recover":
        assert protected_record("alice", "verified")
        assert not published("alice")
        assert not recover("alice", lambda user: ["fingerprint"], enable, rollback)
        assert not published("alice")
        prefs = json.loads(command(executable, "debug", "prefs"))
        assert prefs["RunSSH"] is False and not prefs.get("OperatorUser")
        marker = root / "verified/alice"
        os.chown(marker, 1000, -1)
        assert not recover("alice", lambda user: [], enable, rollback)
        os.chown(marker, 0, -1)
        assert recover("alice", lambda user: [], enable, rollback)
        assert published("alice")
    else:
        assert published("alice")
        def unexpected(*args):
            raise AssertionError("completed enrollment was replayed")
        assert recover("alice", unexpected, enable, unexpected)
        prefs = json.loads(command(executable, "debug", "prefs"))
        assert prefs["RunSSH"] is True and prefs["OperatorUser"] == "alice"
  '';
in
pkgs.testers.runNixOSTest {
  name = "workstation-enrollment-crash-recovery";
  nodes.machine = {
    services.tailscale.enable = true;
    users.users.alice = {
      isNormalUser = true;
      uid = 1000;
    };
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("tailscaled.service")
    exercise = "${pkgs.python3}/bin/python3 ${exercise} "
    machine.fail(exercise + "crash")
    # A hard power failure must not lose the verification journal.
    machine.crash()
    machine.start()
    machine.wait_for_unit("tailscaled.service")
    machine.succeed(exercise + "recover")
    machine.crash()
    machine.start()
    machine.wait_for_unit("tailscaled.service")
    machine.succeed(exercise + "verify")
  '';
}
