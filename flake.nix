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
              pkgs.cage
              pkgs.coreutils
            ];
            text = ''
              user="$(id -un)"
              managed=${lib.escapeShellArg stateDirectory}/managed-users/"$user"
              completion=${lib.escapeShellArg stateDirectory}/completed/"$user"

              if [[ ! -e "$managed" || -e "$completion" ]]; then
                exec ${cfg.normalSessionCommand}
              fi

              exec cage -d -- ${lib.getExe cfg.package}
            '';
          };
        in
        {
          options.services.tenkr-workstation-setup = {
            enable = lib.mkEnableOption "10kR first-login workstation setup";
            package = lib.mkPackageOption self.packages.${pkgs.stdenv.hostPlatform.system} "default" { };
            managedUsers = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              example = [ "alice" ];
              description = "Users who must complete workstation enrollment.";
            };
            normalSessionCommand = lib.mkOption {
              type = lib.types.str;
              default = "${pkgs.gnome-session}/bin/gnome-session";
              defaultText = lib.literalExpression ''"''${pkgs.gnome-session}/bin/gnome-session"'';
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
            ];

            environment.systemPackages = [ cfg.package ];

            # GDM must expose only the router. The router starts either the kiosk
            # or the configured desktop based on root-owned enrollment state.
            services.displayManager.sessionPackages = lib.mkForce [ setupSession ];
            services.displayManager.defaultSession = lib.mkForce "tenkr-workstation";

            systemd.tmpfiles.rules = [
              "d ${stateDirectory} 0755 root root -"
              "d ${stateDirectory}/completed 0755 root root -"
            ];

            systemd.services.tenkr-workstation-setup-state = {
              description = "Initialize 10kR workstation enrollment state";
              wantedBy = [ "multi-user.target" ];
              before = [ "display-manager.service" ];
              serviceConfig.Type = "oneshot";
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
        package = self.packages.${system}.default;
        module =
          let
            evaluated = nixpkgs.lib.nixosSystem {
              inherit system;
              modules = [
                self.nixosModules.default
                {
                  system.stateVersion = "26.05";
                  services.displayManager.gdm.enable = true;
                  services.desktopManager.gnome.enable = true;
                  programs.hyprland.enable = true;
                  services.tenkr-workstation-setup = {
                    enable = true;
                    managedUsers = [ "alice" ];
                  };
                }
              ];
            };
            evaluatedConfig = evaluated.config;
          in
          assert evaluatedConfig.services.displayManager.sessionData.sessionNames == [ "tenkr-workstation" ];
          assert evaluatedConfig.services.displayManager.defaultSession == "tenkr-workstation";
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
          inputsFrom = [ self.packages.${system}.default ];
          packages = [ (pkgsFor system).nixfmt ];
        };
      });

      formatter = forAllSystems (system: (pkgsFor system).nixfmt);
    };
}
