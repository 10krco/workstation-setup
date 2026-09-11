"""Private, inherited-pipe access to an onboarding-owned Chrome process."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


_LAUNCHER = """
import os, sys
reader = os.dup(int(sys.argv[1]))
writer = os.dup(int(sys.argv[2]))
os.dup2(reader, 3)
os.dup2(writer, 4)
os.set_inheritable(3, True)
os.set_inheritable(4, True)
for fd in {reader, writer, int(sys.argv[1]), int(sys.argv[2])} - {3, 4}:
    os.close(fd)
os.execvp(sys.argv[3], sys.argv[3:])
"""


class ChromePipe:
    def __init__(self, profile, executable="google-chrome", extra_args=()):
        profile = Path(profile).absolute()
        profile.mkdir(mode=0o700, parents=True, exist_ok=True)
        read_child, self.writer = os.pipe()
        self.reader, write_child = os.pipe()
        self.buffer, self.sequence = b"", 0
        self.closed = False
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-c", _LAUNCHER, str(read_child), str(write_child), executable,
                 f"--user-data-dir={profile}", "--remote-debugging-pipe", "--no-first-run",
                 *extra_args, "chrome://settings/people"],
                pass_fds=(read_child, write_child), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
        except BaseException:
            os.close(self.writer)
            os.close(self.reader)
            raise
        finally:
            os.close(read_child)
            os.close(write_child)

    def call(self, method, params=None, session=None, timeout=15):
        self.sequence += 1
        request = {"id": self.sequence, "method": method, "params": params or {}}
        if session is not None:
            request["sessionId"] = session
        packet = json.dumps(request).encode() + b"\0"
        while packet:
            written = os.write(self.writer, packet)
            packet = packet[written:]
        deadline = time.monotonic() + timeout
        while True:
            while b"\0" in self.buffer:
                payload, self.buffer = self.buffer.split(b"\0", 1)
                response = json.loads(payload)
                if response.get("id") == self.sequence:
                    if "error" in response:
                        raise RuntimeError("Chrome could not provide the requested setup status.")
                    return response.get("result", {})
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.reader], [], [], remaining)[0]:
                raise RuntimeError("Chrome did not respond. Close the work browser and retry setup.")
            chunk = os.read(self.reader, 65536)
            if not chunk:
                raise RuntimeError("The work browser closed before setup was verified.")
            self.buffer += chunk
            if len(self.buffer) > 4 * 1024 * 1024:
                raise RuntimeError("Chrome returned an unexpectedly large setup response.")

    def page(self, url):
        target = self.call("Target.createTarget", {"url": url, "background": True})["targetId"]
        session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        return target, session

    def evaluate(self, session, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                "returnByValue": True}, session)
        if "exceptionDetails" in result:
            raise RuntimeError("This Chrome version could not report its setup state.")
        return result["result"].get("value")

    def close(self):
        if self.closed:
            return
        try:
            if self.process.poll() is None:
                try:
                    self.call("Browser.close", timeout=5)
                except (OSError, RuntimeError):
                    pass
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait()
        finally:
            self.closed = True
            os.close(self.reader)
            os.close(self.writer)
