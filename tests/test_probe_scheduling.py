import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tenkr_workstation_setup.app import SetupWindow
from tenkr_workstation_setup.probes import ProbeResult


class ProbeSchedulingTest(unittest.TestCase):
    def test_refreshes_do_not_overlap_and_stale_work_is_dropped(self):
        window = SimpleNamespace(_probe_lock=threading.Lock(), _probe_generation=1, _apply_probes=Mock())
        entered, release = threading.Event(), threading.Event()
        active, peak = 0, 0
        def probe(_step):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            entered.set()
            release.wait(2)
            active -= 1
            return ProbeResult(False, "Incomplete")
        with patch("tenkr_workstation_setup.app.probe", side_effect=probe), patch("tenkr_workstation_setup.app.GLib.idle_add") as idle:
            first = threading.Thread(target=SetupWindow._collect_probes, args=(window, 1, False))
            first.start()
            self.assertTrue(entered.wait(2))
            window._probe_generation = 2
            second = threading.Thread(target=SetupWindow._collect_probes, args=(window, 2, False))
            second.start()
            release.set()
            first.join(5)
            second.join(5)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(peak, 1)
            self.assertEqual(idle.call_count, 1)
            self.assertEqual(idle.call_args.args[1], 2)
