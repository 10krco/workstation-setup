"""Run the real keyring test using only a disposable home and session bus."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="tenkr-keyring-test-") as directory:
    root = Path(directory)
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    config = Path(__file__).with_name("session-bus.conf").resolve()
    environment = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(root / "config"),
                       XDG_DATA_HOME=str(root / "data"), XDG_RUNTIME_DIR=str(runtime),
                       TENKR_KEYRING_TEST="1")
    result = subprocess.run(["dbus-run-session", f"--config-file={config}", "--", sys.executable,
                             "-m", "unittest", "discover", "-s", "tests", "-p", "test_keyring.py", "-v"],
                            env=environment)
    raise SystemExit(result.returncode)
