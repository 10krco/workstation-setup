import json
import sys
import unittest
from unittest.mock import patch

from tenkr_workstation_setup.personalization import activate, resolve, run


class PersonalizationTest(unittest.TestCase):
    def test_command_failure_does_not_expose_captured_output(self):
        with self.assertRaises(RuntimeError) as error:
            run(sys.executable, "-c", "import sys; print('private-output'); sys.exit(1)")
        self.assertNotIn("private-output", str(error.exception))

    def test_timeout_terminates_command(self):
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            run(sys.executable, "-c", "import time; time.sleep(30)", timeout=0.1)

    @patch("tenkr_workstation_setup.personalization.run")
    def test_branch_is_pinned_before_build_and_activation(self, run):
        revision = "a" * 40
        run.return_value = json.dumps({"locked": {"type": "github", "rev": revision}})
        remote = resolve("github:example/home/main#alice@workstation")
        self.assertEqual(remote.source, f"github:example/home/{revision}")
        self.assertIn(revision, run.call_args.args[-1])
        self.assertNotIn("home-manager", [c.args[0] for c in run.call_args_list])
        activate(remote)
        self.assertEqual(run.call_args.args,
                         ("home-manager", "switch", "--no-update-lock-file", "--flake", remote.flake))

    @patch("tenkr_workstation_setup.personalization.run")
    def test_rejects_local_and_malformed_sources_before_any_command(self, run):
        for value in (".#alice", "path:/tmp/config#alice", "github:x/y#bad\"output", "github:x/y"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve(value)
        run.assert_not_called()

    @patch("tenkr_workstation_setup.personalization.run")
    def test_missing_revision_cannot_reach_build(self, run):
        run.return_value = json.dumps({"locked": {"type": "github"}})
        with self.assertRaises(ValueError):
            resolve("github:example/home#alice")
        self.assertEqual(run.call_count, 1)

    @patch("tenkr_workstation_setup.personalization.run")
    def test_failed_build_cannot_reach_activation(self, run):
        run.side_effect = [json.dumps({"locked": {"type": "github", "rev": "b" * 40}}),
                           RuntimeError("build failed")]
        with self.assertRaises(RuntimeError):
            resolve("github:example/home#alice")
        self.assertNotIn("home-manager", [c.args[0] for c in run.call_args_list])
