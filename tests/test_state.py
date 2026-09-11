import tempfile
import unittest
from pathlib import Path

from tenkr_workstation_setup.state import EnrollmentState, STEPS


class EnrollmentStateTest(unittest.TestCase):
    def test_progress_resumes_without_creating_authoritative_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = EnrollmentState(root)
            for step in STEPS:
                if step.required:
                    state.mark_complete(step)

            resumed = EnrollmentState(root)
            self.assertTrue(all(resumed.is_complete(step) for step in STEPS if step.required))
            self.assertFalse((root / "complete").exists())


if __name__ == "__main__":
    unittest.main()
