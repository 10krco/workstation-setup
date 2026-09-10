import tempfile
import unittest
from pathlib import Path

from tenkr_workstation_setup.state import EnrollmentState, STEPS


class EnrollmentStateTest(unittest.TestCase):
    def test_required_steps_gate_completion_and_state_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = EnrollmentState(root)
            with self.assertRaises(ValueError):
                state.finish()

            for step in STEPS:
                if step.required:
                    state.mark_complete(step)

            EnrollmentState(root).finish()
            self.assertTrue((root / "complete").is_file())


if __name__ == "__main__":
    unittest.main()
