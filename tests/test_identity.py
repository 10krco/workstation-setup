import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tenkr_workstation_setup.identity import git_identity


class IdentityTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.identity.pwd.getpwuid", return_value=Mock(pw_name="alice"))
    def test_name_title_and_work_email_come_from_fleet(self, _pwd):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "users.json"
            path.write_text(json.dumps({"alice": {"fullName": "Alice Example", "title": "Engineer",
                                                  "workEmail": "alice@10kr.co"}}))
            self.assertEqual(git_identity(path), ("Alice Example (Engineer)", "alice@10kr.co"))
            path.write_text(json.dumps({"alice": {"fullName": "Alice Example", "workEmail": "alice@10kr.co"}}))
            with self.assertRaises(RuntimeError):
                git_identity(path)
