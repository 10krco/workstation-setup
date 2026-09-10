{
  description = "First-login enrollment for 10kR NixOS workstations";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: import nixpkgs { inherit system; };
    in
    {
      packages = forAllSystems (system: {
        default = (pkgsFor system).callPackage ./nix/package.nix { };
      });

      nixosModules.keyring = import ./nix/keyring.nix;

      nixosModules.default =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          cfg = config.services.tenkr-workstation-setup;
          stateDirectory = "/var/lib/10kr-workstation-setup";
          enrollmentGate = import ./nix/enrollment-gate.nix {
            inherit pkgs;
            managedUsers = cfg.managedUsers;
          };
          setupSession =
            pkgs.runCommand "tenkr-workstation-setup-session"
              {
                passthru.providedSessions = [ "tenkr-workstation" ];
              }
              ''
                mkdir -p "$out/share/wayland-sessions"
                cat > "$out/share/wayland-sessions/tenkr-workstation.desktop" <<EOF
                [Desktop Entry]
                Name=10kR Workstation
                Comment=Complete setup before starting the desktop
                Exec=${lib.getExe setupRouter}
                Type=Application
                DesktopNames=10kR
                EOF
              '';
          setupRouter = pkgs.writeShellApplication {
            name = "tenkr-workstation-session";
            runtimeInputs = [
              pkgs.sway-unwrapped
              pkgs.coreutils
            ];
            text = ''
              user="$(id -un)"
              if ${enrollmentGate} "$user"; then
                exec ${cfg.normalSessionCommand}
              fi

              sway --config ${setupCompositorConfig}
              if ${enrollmentGate} "$user"; then
                exec ${cfg.normalSessionCommand}
              fi
            '';
          };
          setupCompositorConfig = pkgs.writeText "tenkr-setup-sway.conf" ''
            # Deliberately do not include the user's or the distribution's
            # desktop config: this session has no launcher or terminal bindings.
            xwayland enable
            output * bg #181825 solid_color
            default_border none
            default_floating_border pixel 2
            workspace_layout tabbed
            focus_follows_mouse no
            bindsym Alt+Tab focus next
            exec ${lib.getExe setupEnvironment}
          '';
          setupEnvironment = pkgs.writeShellApplication {
            name = "tenkr-workstation-setup-environment";
            runtimeInputs = [
              pkgs.dbus
              pkgs.systemd
              pkgs.sway-unwrapped
            ];
            text = ''
              # The compositor supplies WAYLAND_DISPLAY to its child. Publish that
              # environment before D-Bus starts a browser or portal for us.
              export XDG_CURRENT_DESKTOP=10kR
              export XDG_SESSION_TYPE=wayland
              export NIXOS_OZONE_WL=1
              export TENKR_GUIDED_SESSION=1
              dbus-update-activation-environment --systemd \
                WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE NIXOS_OZONE_WL
              ${pkgs.polkit_gnome}/libexec/polkit-gnome-authentication-agent-1 &
              agent=$!
              # GNOME Shell normally supplies this agent. The setup compositor
              # needs its own so secured Wi-Fi networks can request passwords.
              ${pkgs.networkmanagerapplet}/bin/nm-applet --indicator &
              network_agent=$!
              cleanup() {
                kill "$agent" "$network_agent" 2>/dev/null || true
                wait "$agent" "$network_agent" 2>/dev/null || true
                # The next desktop publishes its own compositor environment.
                dbus-update-activation-environment WAYLAND_DISPLAY= DISPLAY= || true
                systemctl --user unset-environment WAYLAND_DISPLAY DISPLAY || true
                swaymsg exit || true
              }
              trap cleanup EXIT
              ${lib.getExe cfg.package}
            '';
          };
        in
        {
          imports = [
            ./nix/keyring.nix
            ./nix/login-gate.nix
            ./nix/enrollment-polkit.nix
          ];
          options.services.tenkr-workstation-setup = {
            enable = lib.mkEnableOption "10kR first-login workstation setup";
            package = lib.mkPackageOption self.packages.${pkgs.stdenv.hostPlatform.system} "default" { };
            managedUsers = lib.mkOption {
              type = lib.types.listOf (lib.types.strMatching "[a-z_][a-z0-9_-]*");
              default = [ ];
              example = [ "alice" ];
              description = "Users who must complete workstation enrollment.";
            };
            tailnetName = lib.mkOption {
              type = lib.types.str;
              default = "";
              description = "Exact CurrentTailnet.Name required before enrollment completes.";
            };
            normalSessionCommand = lib.mkOption {
              type = lib.types.str;
              default = "${pkgs.coreutils}/bin/env XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_DESKTOP=gnome ${pkgs.gnome-session}/bin/gnome-session";
              defaultText = lib.literalExpression ''"''${pkgs.coreutils}/bin/env XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_DESKTOP=gnome ''${pkgs.gnome-session}/bin/gnome-session"'';
              description = "Command started after the managed user completes enrollment.";
            };
          };

          config = lib.mkIf cfg.enable {
            assertions = [
              {
                assertion = config.services.displayManager.gdm.enable;
                message = "10kR workstation setup currently requires GDM.";
              }
              {
                assertion = cfg.managedUsers != [ ];
                message = "10kR workstation setup requires at least one managed user.";
              }
              {
                assertion = !(builtins.elem "root" cfg.managedUsers);
                message = "Root must remain available for workstation enrollment recovery.";
              }
              {
                assertion = cfg.tailnetName != "";
                message = "Workstation enrollment requires the intended Tailscale tailnet name.";
              }
              {
                assertion = config.users.mutableUsers;
                message = "Workstation enrollment requires mutable users to preserve chosen passwords.";
              }
            ];

            environment.systemPackages = [
              cfg.package
              pkgs.google-chrome
            ];
            xdg.portal = {
              enable = true;
              extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
              config."10kr".default = [ "gtk" ];
            };
            environment.etc."10kr/workstation-setup-policy.json".text = builtins.toJSON {
              tailnetName = cfg.tailnetName;
            };
            programs._1password.enable = true;
            programs._1password-gui = {
              enable = true;
              polkitPolicyOwners = cfg.managedUsers;
            };
            services.fprintd.enable = true;
            services.tenkr-keyring.enable = true;
            services.tailscale.enable = true;
            networking.networkmanager.enable = true;
            security.polkit.extraConfig = ''
              polkit.addRule(function(action, subject) {
                if (["org.freedesktop.NetworkManager.network-control",
                     "org.freedesktop.NetworkManager.enable-disable-wifi",
                     "org.freedesktop.NetworkManager.settings.modify.system"].indexOf(action.id) !== -1 &&
                    subject.local && subject.active &&
                    ${builtins.toJSON cfg.managedUsers}.indexOf(subject.user) !== -1) {
                  return polkit.Result.YES;
                }
                if ((action.id == "net.reactivated.fprint.device.enroll" ||
                     action.id == "net.reactivated.fprint.device.verify") &&
                    subject.local && subject.active &&
                    ${builtins.toJSON cfg.managedUsers}.indexOf(subject.user) !== -1) {
                  return polkit.Result.YES;
                }
              });
            '';

            # GDM must expose only the router. The router starts either the kiosk
            # or the configured desktop based on root-owned enrollment state.
            services.displayManager.sessionPackages = lib.mkForce [ setupSession ];
            services.displayManager.defaultSession = lib.mkForce "tenkr-workstation";

            systemd.tmpfiles.rules = [
              "d ${stateDirectory} 0755 root root -"
              "d ${stateDirectory}/completed 0755 root root -"
              "d ${stateDirectory}/password-set 0755 root root -"
              "d ${stateDirectory}/verified 0755 root root -"
            ];

            security.pam.services.tenkr-workstation-setup.text = ''
              auth required ${pkgs.linux-pam}/lib/security/pam_unix.so
              account required ${pkgs.linux-pam}/lib/security/pam_unix.so
            '';

            services.dbus.packages = [
              (pkgs.writeTextDir "share/dbus-1/system.d/com.tenkr.WorkstationSetup.conf" ''
                <!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
                  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
                <busconfig>
                  <policy user="root">
                    <allow own="com.tenkr.WorkstationSetup"/>
                  </policy>
                  <policy context="default">
                    <allow send_destination="com.tenkr.WorkstationSetup"
                      send_interface="com.tenkr.WorkstationSetup" send_member="SetPassword"/>
                    <allow send_destination="com.tenkr.WorkstationSetup"
                      send_interface="com.tenkr.WorkstationSetup" send_member="PrepareNetwork"/>
                    <allow send_destination="com.tenkr.WorkstationSetup"
                      send_interface="com.tenkr.WorkstationSetup" send_member="Complete"/>
                    <allow send_destination="com.tenkr.WorkstationSetup"
                      send_interface="com.tenkr.WorkstationSetup" send_member="VerifyNetwork"/>
                  </policy>
                </busconfig>
              '')
            ];

            systemd.services.tenkr-workstation-setup = {
              description = "Workstation enrollment password service";
              wantedBy = [ "multi-user.target" ];
              requires = [ "tenkr-workstation-setup-state.service" ];
              after = [
                "dbus.service"
                "tailscaled.service"
                "tenkr-workstation-setup-state.service"
              ];
              environment.TENKR_CHPASSWD = "${pkgs.shadow}/bin/chpasswd";
              environment.TENKR_TAILSCALE = "${pkgs.tailscale}/bin/tailscale";
              environment.TENKR_TAILNET = cfg.tailnetName;
              environment.TENKR_MANAGED_USERS = builtins.toJSON cfg.managedUsers;
              environment.TENKR_VERIFIER = "${cfg.package}/bin/tenkr-workstation-setup-verify";
              environment.TENKR_SYSTEMD_RUN = "${pkgs.systemd}/bin/systemd-run";
              environment.TENKR_SYSTEMCTL = "${pkgs.systemd}/bin/systemctl";
              serviceConfig = {
                Type = "dbus";
                BusName = "com.tenkr.WorkstationSetup";
                ExecStart = "${cfg.package}/bin/tenkr-workstation-setup-service";
                UMask = "0077";
                PrivateTmp = true;
                ProtectHome = true;
                LimitCORE = 0;
                Restart = "on-failure";
                RestartSec = 5;
                TimeoutStartSec = 30 + 60 * builtins.length cfg.managedUsers;
              };
            };

            systemd.services.tenkr-workstation-setup-state = {
              description = "Initialize 10kR workstation enrollment state";
              wantedBy = [ "multi-user.target" ];
              requiredBy = [ "display-manager.service" ];
              before = [ "display-manager.service" ];
              serviceConfig.Type = "oneshot";
              serviceConfig.RemainAfterExit = true;
              script = ''
                install -d -m 0755 ${stateDirectory}/managed-users
                ${lib.concatMapStringsSep "\n" (user: ''
                  touch ${stateDirectory}/managed-users/${lib.escapeShellArg user}
                '') cfg.managedUsers}
              '';
            };
          };
        };

      checks = forAllSystems (system: {
        keyring-runtime = import ./nix/keyring-runtime-check.nix {
          pkgs = pkgsFor system;
          source = self;
        };
        package = self.packages.${system}.default;
        password-vm = (pkgsFor system).callPackage ./nix/password-vm.nix {
          package = self.packages.${system}.default;
        };
        login-gate-vm = (pkgsFor system).callPackage ./nix/login-gate-vm.nix { };
        completion-vm = (pkgsFor system).callPackage ./nix/completion-vm.nix {
          package = self.packages.${system}.default;
        };
        polkit-vm = (pkgsFor system).callPackage ./nix/polkit-vm.nix { };
        network-vm = (pkgsFor system).callPackage ./nix/network-vm.nix {
          package = self.packages.${system}.default;
        };
        recovery-vm = (pkgsFor system).callPackage ./nix/recovery-vm.nix {
          package = self.packages.${system}.default;
        };
        wifi-vm = (pkgsFor system).callPackage ./nix/wifi-vm.nix {
          module = self.nixosModules.default;
        };
        graphical-vm = (pkgsFor system).callPackage ./nix/graphical-vm.nix {
          module = self.nixosModules.default;
        };
        module =
          let
            evaluated = nixpkgs.lib.nixosSystem {
              inherit system;
              modules = [
                self.nixosModules.default
                {
                  system.stateVersion = "26.05";
                  nixpkgs.config.allowUnfreePredicate =
                    package:
                    builtins.elem (nixpkgs.lib.getName package) [
                      "1password"
                      "1password-cli"
                      "google-chrome"
                    ];
                  services.displayManager.gdm.enable = true;
                  services.desktopManager.gnome.enable = true;
                  programs.hyprland.enable = true;
                  services.tenkr-workstation-setup = {
                    enable = true;
                    managedUsers = [ "alice" ];
                    tailnetName = "example.ts.net";
                  };
                }
              ];
            };
            evaluatedConfig = evaluated.config;
          in
          assert evaluatedConfig.services.displayManager.sessionData.sessionNames == [ "tenkr-workstation" ];
          assert evaluatedConfig.services.displayManager.defaultSession == "tenkr-workstation";
          assert nixpkgs.lib.all
            (
              name:
              nixpkgs.lib.hasInfix "tenkr-enrollment-account-gate"
                evaluatedConfig.security.pam.services.${name}.text
            )
            [
              "login"
              "sshd"
              "sudo"
              "sudo-i"
              "su"
              "su-l"
            ];
          assert evaluatedConfig.programs._1password.enable;
          assert evaluatedConfig.services.tenkr-keyring.enable;
          assert evaluatedConfig.services.gnome.gnome-keyring.enable;
          assert builtins.elem "graphical-session.target"
            evaluatedConfig.systemd.user.services.tenkr-gnome-keyring-unlock.wantedBy;
          assert evaluatedConfig.programs._1password-gui.enable;
          assert evaluatedConfig.programs._1password-gui.polkitPolicyOwners == [ "alice" ];
          assert evaluatedConfig.security.wrappers.op.setgid;
          assert nixpkgs.lib.hasSuffix "/bin/op" evaluatedConfig.security.wrappers.op.source;
          assert nixpkgs.lib.hasInfix "/managed-users/alice"
            evaluatedConfig.systemd.services.tenkr-workstation-setup-state.script;
          (pkgsFor system).runCommand "check-nixos-module" { } ''
            touch "$out"
          '';
        formatting =
          (pkgsFor system).runCommand "check-nix-formatting"
            {
              nativeBuildInputs = [ (pkgsFor system).nixfmt ];
            }
            ''
              cp -r ${self} source
              chmod -R u+w source
              find source -type f -name '*.nix' -print0 | xargs -0 -r nixfmt
              diff -ru --exclude=.git ${self} source
              touch "$out"
            '';
      });

      devShells = forAllSystems (system: {
        default = (pkgsFor system).mkShell {
          DBUS_SESSION_CONFIG = "${self}/tests/session-bus.conf";
          inputsFrom = [ self.packages.${system}.default ];
          packages = with pkgsFor system; [
            git
            openssh
            gh
            gnome-keyring
            nixfmt
            xvfb-run
            dbus
          ];
        };
      });

      formatter = forAllSystems (system: (pkgsFor system).nixfmt);
    };
}
