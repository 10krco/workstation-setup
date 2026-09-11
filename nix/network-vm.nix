{ pkgs, package }:
let
  exercise = pkgs.writeText "exercise-tailscale-enrollment.py" ''
    import sys
    sys.path.insert(0, "${package}/lib/tenkr-workstation-setup")
    from tenkr_workstation_setup.network import restrict, enable_remote
    executable = "${pkgs.tailscale}/bin/tailscale"
    if sys.argv[1] == "restrict":
        restrict(executable)
    else:
        enable_remote("alice", executable)
  '';
in
pkgs.testers.runNixOSTest {
  name = "workstation-tailscale-enrollment";
  nodes.machine = {
    services.tailscale.enable = true;
    users.users.alice.isNormalUser = true;
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("tailscaled.service")
    exercise = "${pkgs.python3}/bin/python3 ${exercise} "
    machine.succeed(exercise + "restrict")
    machine.succeed("runuser -u alice -- tailscale status --json")
    machine.fail("runuser -u alice -- tailscale set --ssh=true")
    machine.succeed(exercise + "enable")
    machine.succeed("runuser -u alice -- tailscale set --ssh=false")
    machine.succeed(exercise + "restrict")
    machine.fail("runuser -u alice -- tailscale set --operator=alice --ssh=true")
  '';
}
