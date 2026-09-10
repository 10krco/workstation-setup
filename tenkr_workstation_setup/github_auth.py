"""GitHub CLI device login without a terminal or exposing CLI output."""
import os
import re
import selectors
import shutil
import signal
import subprocess
import time


def authorized():
    for endpoint in ("user/keys", "user/ssh_signing_keys", "user/emails"):
        result = subprocess.run(["gh", "api", "--hostname", "github.com", endpoint], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=20, check=False)
        if result.returncode:
            return False
    return True


def device_code(text):
    match = re.search(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})", text)
    return match.group(1) if match else None


def login(cancel, display_code, timeout=300):
    if cancel.is_set():
        return False
    if authorized():
        return True
    environment = dict(os.environ, GH_BROWSER=shutil.which("true") or "true", NO_COLOR="1")
    args = ["gh", "auth", "login", "--hostname", "github.com", "--web", "--git-protocol", "ssh",
            "--skip-ssh-key", "--scopes", "admin:public_key,admin:ssh_signing_key,user:email"]
    with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, env=environment, start_new_session=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline, received, shown = time.monotonic() + timeout, "", False
                while process.poll() is None:
                    if cancel.is_set():
                        return False
                    if time.monotonic() >= deadline:
                        raise RuntimeError("GitHub sign-in timed out. Please retry.")
                    for key, _ in selector.select(0.2):
                        chunk = os.read(key.fileobj.fileno(), 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        received = (received + chunk.decode("utf-8", errors="replace"))[-8192:]
                        code = device_code(received)
                        if code and not shown:
                            shown = True
                            display_code(code)
                if process.returncode or not authorized():
                    raise RuntimeError("GitHub sign-in did not grant access to manage authentication and signing keys. Retry and approve the requested access.")
                return True
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
