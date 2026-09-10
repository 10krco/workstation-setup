{
  pkgs,
  module,
  userName ? "alice",
  fullName ? "Alice Example",
  title ? "Engineer",
  workEmail ? "alice@example.com",
  autoLogin ? false,
}:
let
  pamPython = pkgs.python3.withPackages (p: [ p.python-pam ]);
  checkPassword = pkgs.writeText "check-graphical-password.py" ''
    import pam
    authenticate = pam.pam().authenticate
    assert authenticate("${userName}", "replacement-test-password", service="tenkr-workstation-setup")
    assert not authenticate("${userName}", "initial-test-password", service="tenkr-workstation-setup")
  '';
in
pkgs.testers.runNixOSTest {
  name = "workstation-graphical-enrollment";
  enableOCR = true;
  node.pkgs = pkgs.lib.mkForce (
    import pkgs.path {
      system = pkgs.stdenv.hostPlatform.system;
      config.allowUnfreePredicate =
        package:
        builtins.elem (pkgs.lib.getName package) [
          "1password"
          "1password-cli"
          "google-chrome"
        ];
    }
  );
  nodes.machine = { pkgs, ... }: {
    imports = [ module ];
    virtualisation.memorySize = 4096;
    virtualisation.cores = 2;
    virtualisation.qemu.options = [ "-vga none -device virtio-gpu-pci" ];
    services.displayManager.gdm.enable = true;
    services.displayManager.autoLogin = {
      enable = autoLogin;
      user = userName;
    };
    services.desktopManager.gnome.enable = true;
    environment.sessionVariables.GSK_RENDERER = "cairo";
    # The virtual GPU has no accelerated EGL context. Keep the real app and
    # authentication integrations, but use Electron's software renderer here.
    programs._1password-gui.package = pkgs._1password-gui.overrideAttrs (old: {
      preFixup = old.preFixup + ''
        wrapProgram "$out/bin/1password" --add-flags "--disable-gpu --ozone-platform=wayland"
      '';
    });
    users.users.${userName} = {
      isNormalUser = true;
      uid = 1000;
      initialPassword = "initial-test-password";
    };
    services.tenkr-workstation-setup = {
      enable = true;
      managedUsers = [ userName ];
      tailnetName = "example.ts.net";
    };
    environment.etc."10kr/workstation-users.json".text = builtins.toJSON {
      ${userName} = {
        inherit fullName title workEmail;
      };
    };
  };
  testScript = ''
    from typing import Any, cast
    import shlex

    def click(x, y):
        assert machine.qmp_client is not None
        # The driver annotates QMP arguments as strings, but this QMP method
        # requires a JSON array of input events.
        machine.qmp_client.send("input-send-event", cast(Any, {"events": [
            {"type": "abs", "data": {"axis": "x", "value": int(x * 32767 / 1280)}},
            {"type": "abs", "data": {"axis": "y", "value": int(y * 32767 / 800)}}
        ]}))
        machine.sleep(1)
        machine.send_monitor_command("mouse_button 1")
        machine.send_monitor_command("mouse_button 0")
        machine.sleep(1)

    machine.start()
    machine.wait_for_unit("display-manager.service")
    ${pkgs.lib.optionalString (!autoLogin) ''
      machine.wait_for_text("Not listed", timeout=90)
      machine.send_key("ret")
      # The large account label identifies the password page; its faint
      # password placeholder is not reliably recognized by OCR.
      machine.wait_for_text("${userName}", timeout=30)
      machine.send_chars("initial-test-password")
      machine.send_key("ret")
    ''}
    machine.wait_until_succeeds("pgrep -u ${userName} -f bin/tenkr-workstation-setup", timeout=60)
    # The standalone image must provide the services used by GUI enrollment.
    for unit in ["tenkr-onepassword", "tenkr-gnome-keyring-unlock"]:
        loaded = machine.succeed("setpriv --reuid=1000 --regid=100 --init-groups env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user show " + unit + " --property=LoadState --value").strip()
        assert loaded == "loaded", (unit, loaded)
    machine.sleep(10)
    machine.wait_for_text("First-login checklist", timeout=60)
    machine.screenshot("first-login")
    machine.wait_until_succeeds("pgrep -u ${userName} -f polkit-gnome-authentication-agent-1")
    click(875, 155)
    machine.wait_for_text("Supplied password", timeout=30)
    machine.screenshot("password-dialog")
    click(600, 345)
    machine.send_chars("initial-test-password")
    click(600, 400)
    machine.send_chars("replacement-test-password")
    click(600, 455)
    machine.send_chars("replacement-test-password")
    click(640, 526)
    machine.wait_for_file("/var/lib/10kr-workstation-setup/password-set/${userName}", timeout=45)
    machine.succeed("${pamPython}/bin/python ${checkPassword}")
    machine.succeed("journalctl -b -u display-manager --no-pager")
    machine.fail("test -e /var/lib/10kr-workstation-setup/completed/${userName}")
    machine.wait_for_text("Your personal login password is set", timeout=30)
    machine.wait_for_text("not required", timeout=30)
    click(875, 358)
    machine.wait_for_text("A guide stays beside", timeout=30)
    machine.screenshot("onepassword-instructions")
    click(640, 468)
    machine.wait_for_text("Return to setup and check", timeout=45)
    machine.wait_for_text("Create New Account", timeout=60)
    machine.screenshot("external-app-guide")
    machine.fail("test -e /home/${userName}/.config/10kr/workstation-setup/onepassword.complete")
    click(1110, 760)
    machine.wait_for_text("First-login checklist", timeout=30)
    machine.fail("test -e /var/lib/10kr-workstation-setup/completed/${userName}")
    # Closing setup cannot start the desktop. The chosen password and pending
    # enrollment survive another ordinary login.
    click(1256, 48)
    machine.wait_for_text("Not listed", timeout=90)
    machine.fail("pgrep -u ${userName} -f '[/]gnome-shell(-wrapped)?$'")
    machine.send_key("ret")
    machine.wait_for_text("${userName}", timeout=30)
    machine.send_chars("replacement-test-password")
    machine.send_key("ret")
    machine.wait_for_text("First-login checklist", timeout=90)
    machine.wait_for_text("Your personal login password is set", timeout=30)

    # Exercise only the session router's completed transition here. Privileged
    # completion and rejection are independently tested in completion-vm; this
    # root-created fixture is not evidence of real account enrollment.
    machine.succeed("touch /var/lib/10kr-workstation-setup/completed/${userName}")
    # Request the normal Wayland window-close protocol. The first session above
    # tests the titlebar button; this assertion isolates the router from pointer
    # timing during asynchronous checklist refreshes after a second login.
    sway_socket = machine.succeed("ls /run/user/1000/sway-ipc.*.sock").strip()
    machine.succeed("env SWAYSOCK=" + shlex.quote(sway_socket) + " ${pkgs.sway-unwrapped}/bin/swaymsg " + shlex.quote('[app_id="com.tenkr.WorkstationSetup"] kill'))
    machine.wait_until_succeeds("setpriv --reuid=1000 --regid=100 --init-groups env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus busctl --user status org.gnome.Shell", timeout=90)
    machine.wait_for_text("Take Tour|Type to search", timeout=90)
    machine.screenshot("completed-desktop")
  '';
}
