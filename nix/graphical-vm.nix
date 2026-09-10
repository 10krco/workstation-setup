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
  nodes.machine = {
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
  '';
}
