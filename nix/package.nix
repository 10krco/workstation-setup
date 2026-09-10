{
  lib,
  stdenvNoCC,
  python3,
  gtk4,
  libadwaita,
  wrapGAppsHook4,
  gobject-introspection,
  git,
  openssh,
  gh,
  gnome-control-center,
}:

let
  python = python3.withPackages (packages: [
    packages.pygobject3
    packages.dbus-python
    packages.python-pam
  ]);
in
stdenvNoCC.mkDerivation {
  pname = "tenkr-workstation-setup";
  version = "0.1.0";
  src = ../.;

  nativeBuildInputs = [
    gobject-introspection
    wrapGAppsHook4
  ];
  buildInputs = [
    gtk4
    libadwaita
    python
  ];

  preFixup = ''
    gappsWrapperArgs+=(--prefix PATH : ${
      lib.makeBinPath [
        git
        openssh
        gh
        gnome-control-center
      ]
    })
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin" "$out/lib/tenkr-workstation-setup" "$out/share/applications"
    cp -r tenkr_workstation_setup "$out/lib/tenkr-workstation-setup/"
    cp data/com.tenkr.WorkstationSetup.desktop "$out/share/applications/"
    cat > "$out/bin/tenkr-workstation-setup" <<EOF
    #!${python}/bin/python
    import sys
    sys.path.insert(0, "$out/lib/tenkr-workstation-setup")
    from tenkr_workstation_setup.app import main
    raise SystemExit(main())
    EOF
    chmod +x "$out/bin/tenkr-workstation-setup"
    cat > "$out/bin/tenkr-workstation-setup-service" <<EOF
    #!${python}/bin/python
    import sys
    sys.path.insert(0, "$out/lib/tenkr-workstation-setup")
    from tenkr_workstation_setup.service import main
    main()
    EOF
    chmod +x "$out/bin/tenkr-workstation-setup-service"
    runHook postInstall
  '';

  meta = {
    description = "First-login enrollment for 10kR workstations";
    license = lib.licenses.mit;
    mainProgram = "tenkr-workstation-setup";
    platforms = [ "x86_64-linux" ];
  };
}
