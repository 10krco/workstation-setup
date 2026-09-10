import queue
import threading
import unittest
from unittest.mock import Mock

from tenkr_workstation_setup.fingerprint import FINGER, enroll


class FingerprintTest(unittest.TestCase):
    def reader(self, *events, saved=True):
        reader = Mock()
        reader.events = queue.Queue()
        for event in events:
            reader.events.put(event)
        reader.fingers.side_effect = [[], [FINGER] if saved else []]
        return reader

    def test_success_is_verified_and_reader_released(self):
        reader = self.reader(("enroll-stage-passed", False), ("enroll-completed", True))
        progress = Mock()
        self.assertTrue(enroll(reader, threading.Event(), progress))
        self.assertEqual([c.args[0] for c in reader.call.call_args_list],
                         ["Claim", "EnrollStart", "EnrollStop", "Release"])
        reader.close.assert_called_once()

    def test_unsaved_print_does_not_report_success(self):
        reader = self.reader(("enroll-completed", True), saved=False)
        with self.assertRaisesRegex(RuntimeError, "did not save"):
            enroll(reader, threading.Event(), Mock())
        reader.call.assert_called_with("Release")

    def test_cancellation_stops_scan_and_releases_device(self):
        reader = self.reader()
        cancel = threading.Event()
        self.assertFalse(enroll(reader, cancel, lambda _: cancel.set()))
        self.assertEqual([c.args[0] for c in reader.call.call_args_list],
                         ["Claim", "EnrollStart", "EnrollStop", "Release"])

    def test_disconnection_does_not_call_dead_device(self):
        reader = self.reader(("enroll-disconnected", True))
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            enroll(reader, threading.Event(), Mock())
        self.assertEqual([c.args[0] for c in reader.call.call_args_list], ["Claim", "EnrollStart"])
        reader.close.assert_called_once()

    def test_timeout_releases_device(self):
        reader = self.reader()
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            enroll(reader, threading.Event(), Mock(), timeout=0)
        reader.call.assert_called_with("Release")
