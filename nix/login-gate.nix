{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.tenkr-workstation-setup;
  guardedServices = [
    "login"
    "sshd"
    "sudo"
    "sudo-i"
    "su"
    "su-l"
  ];
  gate = import ./enrollment-gate.nix {
    inherit pkgs;
    managedUsers = cfg.managedUsers;
  };
in
{
  config = lib.mkIf cfg.enable {
    security.pam.services = lib.genAttrs guardedServices (name: {
      rules.account.tenkrEnrollment = {
        # Run before any sufficient account rule can short-circuit the stack.
        order =
          (lib.foldl' lib.min 10000 (
            map (rule: rule.order) (
              lib.attrValues (
                lib.removeAttrs config.security.pam.services.${name}.rules.account [ "tenkrEnrollment" ]
              )
            )
          ))
          - 10;
        control = "requisite";
        modulePath = "${pkgs.linux-pam}/lib/security/pam_exec.so";
        args = [
          "quiet"
          "stdout"
          (toString gate)
        ];
      };
    });
  };
}
