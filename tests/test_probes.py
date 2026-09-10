from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tenkr_workstation_setup.probes import ProbeResult, keyring


class ProbeTest(unittest.TestCase):
    def test_keyring_requires_a_1password_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)):
            self.assertEqual(
                keyring(),
                ProbeResult(False, "The login keyring has not been enrolled with 1Password."),
            )

            reference = Path(directory) / ".config" / "10kr" / "gnome-keyring-1password-secret-reference"
            reference.parent.mkdir(parents=True)
            reference.write_text("op://Personal/example/password\n")
            self.assertTrue(keyring().complete)


if __name__ == "__main__":
    unittest.main()
