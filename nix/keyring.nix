{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.tenkr-keyring;
  reference = "%h/.config/10kr/gnome-keyring-1password-secret-reference";
  unlock = import ./keyring-unlock.nix { inherit pkgs lib; };
in
{
  options.services.tenkr-keyring.enable = lib.mkEnableOption "encrypted GNOME Keyring unlocking through 1Password";
  config = lib.mkIf cfg.enable {
    programs._1password.enable = true;
    programs._1password-gui.enable = true;
    services.gnome.gnome-keyring.enable = true;
    systemd.user.services = {
      tenkr-onepassword = {
        description = "1Password for enrolled GNOME Keyring users";
        wantedBy = [ "graphical-session.target" ];
        after = [
          "graphical-session-pre.target"
          "wayland-session-waitenv.service"
        ];
        partOf = [ "graphical-session.target" ];
        unitConfig.ConditionPathExists = reference;
        environment = {
          ELECTRON_OZONE_PLATFORM_HINT = "auto";
          NIXOS_OZONE_WL = "1";
        };
        serviceConfig = {
          ExecStart = "${config.programs._1password-gui.package}/bin/1password --silent";
          Restart = "on-failure";
          RestartSec = 2;
        };
      };
      tenkr-gnome-keyring-unlock = {
        description = "Unlock GNOME Keyring using a password stored in 1Password";
        wantedBy = [ "graphical-session.target" ];
        wants = [ "tenkr-onepassword.service" ];
        after = [ "tenkr-onepassword.service" ];
        partOf = [ "graphical-session.target" ];
        unitConfig = {
          ConditionPathExists = reference;
          StartLimitIntervalSec = 900;
          StartLimitBurst = 3;
        };
        serviceConfig = {
          Type = "oneshot";
          ExecStart = lib.getExe unlock;
          TimeoutStartSec = 310;
          Restart = "on-failure";
          RestartSec = 10;
          LimitCORE = 0;
        };
      };
    };
  };
}
