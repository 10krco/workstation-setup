{ pkgs, lib }:
let
  gate = import ./enrollment-gate.nix {
    inherit pkgs;
    managedUsers = [ "alice" ];
  };
  exercise = pkgs.writeText "exercise-enrollment-account-gate.py" ''
    import ctypes
    import sys
    pam = ctypes.CDLL("${pkgs.linux-pam}/lib/libpam.so.0")
    pam.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                              ctypes.POINTER(ctypes.c_void_p)]
    pam.pam_set_item.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    pam.pam_putenv.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    pam.pam_acct_mgmt.argtypes = [ctypes.c_void_p, ctypes.c_int]
    pam.pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libc = ctypes.CDLL(None)
    libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    libc.calloc.restype = ctypes.c_void_p
    class Response(ctypes.Structure):
        _fields_ = [("text", ctypes.c_void_p), ("code", ctypes.c_int)]
    callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    @callback_type
    def conversation(count, messages, responses, data):
        # Account checks emit informational messages, never password prompts.
        responses[0] = libc.calloc(count, ctypes.sizeof(Response))
        return 0 if responses[0] else 19
    class Conversation(ctypes.Structure):
        _fields_ = [("callback", callback_type), ("data", ctypes.c_void_p)]
    conv = Conversation(conversation, None)
    def allowed(service, user, requester=None):
        handle = ctypes.c_void_p()
        assert pam.pam_start(service.encode(), user.encode(), ctypes.byref(conv), ctypes.byref(handle)) == 0
        try:
            # Environment names must not override the real PAM account items.
            assert pam.pam_putenv(handle, b"PAM_USER=root") == 0
            assert pam.pam_putenv(handle, b"PAM_RUSER=recovery") == 0
            if requester:
                assert pam.pam_set_item(handle, 8, ctypes.c_char_p(requester.encode())) == 0
            return pam.pam_acct_mgmt(handle, 0) == 0
        finally:
            pam.pam_end(handle, 0)
    completed = sys.argv[1] == "complete"
    for service in ("login", "sshd", "sudo", "sudo-i", "su", "su-l"):
        assert allowed(service, "alice") == completed, (service, "target")
        assert allowed(service, "root", "alice") == completed, (service, "requester")
        assert allowed(service, "root"), (service, "root recovery")
        assert allowed(service, "recovery"), (service, "unmanaged recovery")
    # The graphical setup and its password operation must remain accessible.
    assert allowed("tenkr-test-graphical", "alice")
  '';
in
pkgs.testers.runNixOSTest {
  name = "workstation-enrollment-account-gate";
  nodes.machine = {
    imports = [ ./login-gate.nix ];
    options.services.tenkr-workstation-setup = {
      enable = lib.mkEnableOption "test enrollment";
      managedUsers = lib.mkOption { type = lib.types.listOf lib.types.str; };
    };
    config = {
      services.tenkr-workstation-setup = {
        enable = true;
        managedUsers = [ "alice" ];
      };
      users.users.alice = {
        isNormalUser = true;
        initialPassword = "initial-test-password";
        extraGroups = [ "wheel" ];
      };
      users.users.recovery = {
        isNormalUser = true;
        initialPassword = "recovery-test-password";
      };
      security.sudo.wheelNeedsPassword = false;
      security.pam.services.tenkr-test-graphical = { };
    };
  };
  testScript = ''
    machine.start(allow_reboot=True)
    machine.wait_for_unit("multi-user.target")
    check = "${pkgs.python3}/bin/python3 ${exercise} "
    machine.succeed(check + "incomplete")
    machine.fail("${gate} alice")
    machine.succeed("${gate} recovery")
    machine.fail("setsid runuser -u alice -- sudo -n true")
    # User-owned receipts and even an accidentally writable root marker fail closed.
    machine.succeed("runuser -u alice -- mkdir -p /home/alice/.config/10kr/workstation-setup")
    machine.succeed("runuser -u alice -- touch /home/alice/.config/10kr/workstation-setup/complete")
    machine.succeed("install -d -m 0755 /var/lib/10kr-workstation-setup/completed")
    machine.fail("runuser -u alice -- touch /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed(check + "incomplete")
    machine.succeed("ln -s /home/alice/.config/10kr/workstation-setup/complete /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed(check + "incomplete")
    machine.succeed("rm /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed("touch /var/lib/10kr-workstation-setup/completed/alice; chmod 0666 /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed(check + "incomplete")
    machine.succeed("chmod 0644 /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed("chown alice /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed(check + "incomplete")
    machine.succeed("chown root /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed("chmod 0777 /var/lib/10kr-workstation-setup/completed")
    machine.succeed(check + "incomplete")
    machine.succeed("chmod 0755 /var/lib/10kr-workstation-setup/completed")
    machine.succeed(check + "complete")
    machine.succeed("${gate} alice")
    machine.succeed("setsid runuser -u alice -- sudo -n true")
    machine.reboot()
    machine.wait_for_unit("multi-user.target")
    machine.succeed(check + "complete")
    machine.succeed("rm /var/lib/10kr-workstation-setup/completed/alice")
    machine.succeed(check + "incomplete")
  '';
}
