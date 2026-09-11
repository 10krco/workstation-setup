{ pkgs, lib }:
let
  policy = pkgs.writeTextDir "share/polkit-1/actions/com.tenkr.test.policy" ''
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
      "http://www.freedesktop.org/standards/PolicyKit/1.0/policyconfig.dtd">
    <policyconfig>
      <action id="com.tenkr.test.admin">
        <description>Test privileged action</description><message>Test authorization</message>
        <defaults><allow_any>yes</allow_any><allow_inactive>yes</allow_inactive><allow_active>yes</allow_active></defaults>
      </action>
      <action id="com.1password.1Password.authorizeCLI">
        <description>Test permitted policy path</description><message>Test authorization</message>
        <defaults><allow_any>yes</allow_any><allow_inactive>yes</allow_inactive><allow_active>yes</allow_active></defaults>
      </action>
      <action id="com.1password.1Password.authorizeSshAgent">
        <description>Test retained authentication requirement</description><message>Test authorization</message>
        <defaults><allow_any>auth_self</allow_any><allow_inactive>auth_self</allow_inactive><allow_active>auth_self</allow_active></defaults>
      </action>
      <action id="org.freedesktop.NetworkManager.network-control">
        <description>Test inactive network access</description><message>Test authorization</message>
        <defaults><allow_any>yes</allow_any><allow_inactive>yes</allow_inactive><allow_active>yes</allow_active></defaults>
      </action>
    </policyconfig>
  '';
in
pkgs.testers.runNixOSTest {
  name = "workstation-enrollment-polkit";
  nodes.machine = {
    imports = [ ./enrollment-polkit.nix ];
    options.services.tenkr-workstation-setup = {
      enable = lib.mkEnableOption "test enrollment";
      managedUsers = lib.mkOption { type = lib.types.listOf lib.types.str; };
    };
    config = {
      services.tenkr-workstation-setup = {
        enable = true;
        managedUsers = [ "alice" ];
      };
      users.users.alice = {
        isNormalUser = true;
        extraGroups = [ "wheel" ];
      };
      users.users.recovery.isNormalUser = true;
      security.polkit.extraConfig = ''
        polkit.addRule(function(action, subject) {
          if (action.id === "com.tenkr.test.admin") return polkit.Result.YES;
        });
      '';
      environment.systemPackages = [ policy ];
      security.polkit.enable = true;
    };
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("polkit.service")
    def check(user, action):
        return "runuser -u " + user + " -- sh -c 'pkcheck --action-id " + action + " --process $$'"
    admin = "com.tenkr.test.admin"
    cli = "com.1password.1Password.authorizeCLI"
    signing = "com.1password.1Password.authorizeSshAgent"
    network = "org.freedesktop.NetworkManager.network-control"
    machine.fail(check("alice", admin))
    machine.succeed(check("recovery", admin))
    machine.succeed(check("alice", cli))
    machine.fail(check("alice", signing))
    machine.fail(check("alice", network))
    machine.succeed("runuser -u alice -- mkdir -p /home/alice/.config/10kr/workstation-setup")
    machine.succeed("runuser -u alice -- touch /home/alice/.config/10kr/workstation-setup/complete")
    machine.fail(check("alice", admin))
    machine.succeed("install -d -m 0755 /var/lib/10kr-workstation-setup/completed")
    machine.succeed("touch /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed(check("alice", admin))
    machine.succeed(check("alice", network))
    machine.fail(check("alice", signing))
    machine.succeed("rm /var/lib/10kr-workstation-setup/completed/alice")
    machine.fail(check("alice", admin))
  '';
}
