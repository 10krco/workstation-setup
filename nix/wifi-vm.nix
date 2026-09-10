{ pkgs, module }:
let
  baseTest = pkgs.callPackage ./graphical-vm.nix { inherit module; };
  apConfig = pkgs.writeText "onboarding-test-ap.conf" ''
    interface=wlan0
    driver=nl80211
    ssid=10kR Onboarding Test
    hw_mode=g
    channel=1
    wpa=2
    wpa_passphrase=onboarding-fixture
    wpa_key_mgmt=WPA-PSK
    rsn_pairwise=CCMP
  '';
in
baseTest.extend {
  modules = [
    {
      name = pkgs.lib.mkForce "workstation-wifi-enrollment";
      nodes.machine = {
        boot.kernelModules = [ "mac80211_hwsim" ];
        boot.extraModprobeConfig = "options mac80211_hwsim radios=2";
        # qemu-vm disables wireless by default. Use the real service and policy.
        networking.wireless.enable = pkgs.lib.mkOverride 9 true;
        networking.networkmanager.unmanaged = [ "interface-name:wlan0" ];
        systemd.services.onboarding-test-ap = {
          wantedBy = [ "multi-user.target" ];
          after = [
            "NetworkManager.service"
            "sys-subsystem-net-devices-wlan0.device"
          ];
          requires = [ "sys-subsystem-net-devices-wlan0.device" ];
          preStart = ''
            ${pkgs.iproute2}/bin/ip address replace 192.0.2.1/24 dev wlan0
            ${pkgs.iproute2}/bin/ip link set wlan0 up
          '';
          serviceConfig.ExecStart = "${pkgs.hostapd}/bin/hostapd ${apConfig}";
        };
        systemd.services.onboarding-test-dhcp = {
          wantedBy = [ "multi-user.target" ];
          after = [ "onboarding-test-ap.service" ];
          requires = [ "onboarding-test-ap.service" ];
          serviceConfig.ExecStart = "${pkgs.dnsmasq}/bin/dnsmasq --no-daemon --interface=wlan0 --bind-interfaces --port=0 --dhcp-range=192.0.2.10,192.0.2.20,255.255.255.0,1h";
        };
        networking.firewall.allowedUDPPorts = [ 67 ];
      };
      testScript = pkgs.lib.mkForce ''
        from typing import Any, cast

        def click(x, y):
            assert machine.qmp_client is not None
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
        machine.wait_for_unit("onboarding-test-ap.service")
        machine.wait_until_succeeds("nmcli -t -f SSID device wifi list ifname wlan1 | grep -Fx '10kR Onboarding Test'", timeout=45)
        machine.wait_for_text("Not listed", timeout=90)
        machine.send_key("ret")
        machine.wait_for_text("alice", timeout=30)
        machine.send_chars("initial-test-password")
        machine.send_key("ret")
        machine.wait_for_text("First-login checklist", timeout=90)
        machine.wait_until_succeeds("pgrep -u alice -f nm-applet", timeout=30)
        click(875, 235)
        machine.wait_for_text("Open Wi-Fi settings", timeout=30)
        click(640, 495)
        machine.wait_for_text("10kR Onboarding Test", timeout=60)
        machine.screenshot("wifi-network-choice")
        click(580, 395)
        machine.wait_for_text("Authentication required by Wi-Fi network", timeout=90)
        # Cancel and retry through the GUI without marking enrollment complete.
        click(600, 502)
        machine.fail("test -e /var/lib/10kr-workstation-setup/completed/alice")
        click(580, 395)
        machine.wait_for_text("Authentication required by Wi-Fi network", timeout=90)
        click(500, 425)
        machine.send_chars("onboarding-fixture")
        click(705, 502)
        machine.wait_until_succeeds("nmcli -t -f GENERAL.STATE device show wlan1 | grep -F '100 (connected)'", timeout=60)
        machine.wait_until_succeeds("nmcli -g IP4.ADDRESS device show wlan1 | grep '^192.0.2.'", timeout=30)
        machine.screenshot("wifi-connected-with-guide")
        click(1110, 760)
        machine.wait_for_text("First-login checklist", timeout=30)
        machine.fail("test -e /var/lib/10kr-workstation-setup/completed/alice")
        machine.screenshot("wifi-return-to-setup")
        click(1256, 48)
        machine.wait_for_text("Not listed", timeout=90)
        machine.wait_until_fails("pgrep -u alice -f nm-applet", timeout=30)
      '';
    }
  ];
}
