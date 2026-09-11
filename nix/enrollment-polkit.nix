{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.tenkr-workstation-setup;
  gate = import ./enrollment-gate.nix {
    inherit pkgs;
    managedUsers = cfg.managedUsers;
  };
in
{
  config = lib.mkIf cfg.enable {
    security.polkit.enable = true;
    # This must precede the regular NixOS and packaged authorization rules.
    environment.etc."polkit-1/rules.d/00-tenkr-enrollment.rules".text = ''
      polkit.addRule(function(action, subject) {
        if (${builtins.toJSON cfg.managedUsers}.indexOf(subject.user) === -1) return;
        try {
          polkit.spawn(["${gate}", subject.user]);
          return;
        } catch (error) {
          // Missing, forged, or unreadable state means enrollment is incomplete.
        }
        // These affect the user's own 1Password account; its policy still
        // authenticates the user. Never grant them unconditionally here.
        if (["com.1password.1Password.unlock",
             "com.1password.1Password.authorizeCLI",
             "com.1password.1Password.authorizeSshAgent"].indexOf(action.id) !== -1) return;
        if (subject.local && subject.active && [
            "org.freedesktop.NetworkManager.network-control",
            "org.freedesktop.NetworkManager.enable-disable-wifi",
            "org.freedesktop.NetworkManager.enable-disable-network",
            "org.freedesktop.NetworkManager.settings.modify.own",
            "org.freedesktop.NetworkManager.settings.modify.system",
            "net.reactivated.fprint.device.enroll",
            "net.reactivated.fprint.device.verify",
            "org.freedesktop.login1.power-off",
            "org.freedesktop.login1.reboot",
            "org.freedesktop.login1.suspend",
            "org.freedesktop.login1.inhibit-delay-shutdown",
            "org.freedesktop.login1.inhibit-delay-sleep"
          ].indexOf(action.id) !== -1) return;
        return polkit.Result.NO;
      });
    '';
    systemd.services.polkit.reloadTriggers = [
      config.environment.etc."polkit-1/rules.d/00-tenkr-enrollment.rules".source
    ];
    assertions = [
      {
        assertion = builtins.all (user: user == "root") config.nix.settings.trusted-users;
        message = "Enrollment users must not have root-equivalent Nix daemon trust; use trusted-users = [ root ].";
      }
    ];
  };
}
