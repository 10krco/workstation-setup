"""Cancellable fprintd enrollment. GTK owns signal dispatch; work runs off-thread."""
import queue
import time

from gi.repository import Gio, GLib

SERVICE = "net.reactivated.Fprint"
DEVICE = SERVICE + ".Device"
FINGER = "right-index-finger"


class Reader:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        result = self.bus.call_sync(SERVICE, "/net/reactivated/Fprint/Manager",
                                   SERVICE + ".Manager", "GetDefaultDevice", None,
                                   GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 10000, None)
        self.path = result.unpack()[0]
        self.events = queue.Queue()
        self.subscription = self.bus.signal_subscribe(
            SERVICE, DEVICE, "EnrollStatus", self.path, None, Gio.DBusSignalFlags.NONE,
            lambda _bus, _sender, _path, _iface, _name, parameters:
                self.events.put(parameters.unpack()),
        )

    def call(self, method, value=None):
        args = None if value is None else GLib.Variant("(s)", (value,))
        return self.bus.call_sync(SERVICE, self.path, DEVICE, method, args, None,
                                  Gio.DBusCallFlags.NONE, 30000, None).unpack()

    def fingers(self):
        try:
            return self.call("ListEnrolledFingers", "")[0]
        except GLib.Error as error:
            if Gio.DBusError.get_remote_error(error) == SERVICE + ".Error.NoEnrolledPrints":
                return []
            raise

    def close(self):
        self.bus.signal_unsubscribe(self.subscription)


def enroll(reader, cancel, progress, timeout=180):
    claimed = started = disconnected = False
    try:
        if cancel.is_set():
            return False
        reader.call("Claim", "")
        claimed = True
        if FINGER in reader.fingers():
            progress("Your right index finger is already enrolled.")
            return True
        reader.call("EnrollStart", FINGER)
        started = True
        progress("Touch the reader with your right index finger, then lift it between scans.")
        deadline = time.monotonic() + timeout
        stages = 0
        while not cancel.is_set():
            if time.monotonic() >= deadline:
                raise RuntimeError("Enrollment timed out. Try again when you are ready.")
            try:
                status, done = reader.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if status == "enroll-disconnected":
                disconnected = True
                raise RuntimeError("The fingerprint reader disconnected. Reconnect it and try again.")
            if status == "enroll-completed" and done:
                reader.call("EnrollStop")
                started = False
                if FINGER not in reader.fingers():
                    raise RuntimeError("The reader did not save the fingerprint. Please retry.")
                progress("Your right index fingerprint is saved.")
                return True
            if done:
                raise RuntimeError({
                    "enroll-duplicate": "That fingerprint is already stored on the reader. Ask your administrator to review the existing enrollment.",
                    "enroll-data-full": "The reader is full. Ask your administrator to review stored fingerprints.",
                }.get(status, "The scan could not be completed. Please try again."))
            if status == "enroll-stage-passed":
                stages += 1
                progress(f"Scan {stages} accepted. Lift and reposition your right index finger.")
            else:
                progress({
                    "enroll-finger-not-centered": "Center your right index finger on the reader.",
                    "enroll-remove-and-retry": "Lift your finger, then touch the reader again.",
                    "enroll-too-fast": "Keep your finger on the reader a little longer.",
                    "enroll-swipe-too-short": "Move your finger across the whole reader.",
                }.get(status, "Please scan your right index finger again."))
        return False
    finally:
        if not disconnected:
            for needed, method in ((started, "EnrollStop"), (claimed, "Release")):
                if needed:
                    try:
                        reader.call(method)
                    except GLib.Error:
                        pass
        reader.close()


def enrolled_fingers():
    reader = Reader()
    try:
        return reader.fingers()
    finally:
        reader.close()
