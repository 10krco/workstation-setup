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
    config = root / "bus.conf"
    config.write_text('''<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>
<auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/>
<allow own="*"/></policy></busconfig>''')
    environment = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(root / "config"),
                       XDG_DATA_HOME=str(root / "data"), XDG_RUNTIME_DIR=str(runtime),
                       TENKR_KEYRING_TEST="1")
    result = subprocess.run(["dbus-run-session", f"--config-file={config}", "--", sys.executable,
                             "-m", "unittest", "discover", "-s", "tests", "-p", "test_keyring.py", "-v"],
                            env=environment)
    raise SystemExit(result.returncode)
