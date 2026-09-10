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
        in
        {
          options.services.tenkr-workstation-setup = {
            enable = lib.mkEnableOption "10kR first-login workstation setup";
            package = lib.mkPackageOption self.packages.${pkgs.stdenv.hostPlatform.system} "default" { };
          };

          config = lib.mkIf cfg.enable {
            environment.systemPackages = [ cfg.package ];
            systemd.user.services.tenkr-workstation-setup = {
              description = "10kR first-login workstation setup";
              wantedBy = [ "graphical-session.target" ];
              after = [ "graphical-session.target" ];
              partOf = [ "graphical-session.target" ];
              unitConfig.ConditionPathExists = "!%h/.config/10kr/workstation-setup/complete";
              serviceConfig = {
                Type = "simple";
                ExecStart = lib.getExe cfg.package;
                Restart = "on-failure";
                RestartSec = 3;
              };
            };
          };
        };

      checks = forAllSystems (system: {
        package = self.packages.${system}.default;
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
