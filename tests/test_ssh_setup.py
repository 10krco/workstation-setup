import json
import unittest
from unittest.mock import patch

from tenkr_workstation_setup.ssh_setup import ensure_item, register


class SshSetupTest(unittest.TestCase):
    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_existing_item_is_reused_and_only_public_field_requested(self, command):
        command.side_effect = [json.dumps([{"id": "abc123", "title": "key"}]), "ssh-ed25519 AAAA comment"]
        self.assertEqual(ensure_item("Personal", "key"), ("abc123", "ssh-ed25519 AAAA"))
        self.assertEqual(command.call_args.args, ("op", "read", "op://Personal/abc123/public_key"))
        self.assertFalse(any("create" in call.args for call in command.call_args_list))

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_new_item_response_is_discarded(self, command):
        command.side_effect = ["[]", None, json.dumps([{"id": "abc123", "title": "key"}]), "ssh-ed25519 AAAA"]
        ensure_item("Personal", "key")
        self.assertTrue(command.call_args_list[1].kwargs["discard"])

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_ambiguous_titles_do_not_create_another_item(self, command):
        command.return_value = json.dumps([{"id": "a", "title": "key"}, {"id": "b", "title": "key"}])
        with self.assertRaises(RuntimeError):
            ensure_item("Personal", "key")
        self.assertEqual(command.call_count, 1)

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_existing_github_key_is_not_uploaded_again(self, command):
        command.return_value = json.dumps([[{"key": "ssh-ed25519 AAAA comment"}]])
        register("ssh-ed25519 AAAA", "signing", "title")
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[-1], "user/ssh_signing_keys")

    @patch("tenkr_workstation_setup.ssh_setup.command")
    def test_uploaded_key_is_read_back(self, command):
        command.side_effect = ["[[]]", "{}", json.dumps([[{"key": "ssh-ed25519 AAAA"}]])]
        register("ssh-ed25519 AAAA", "authentication", "title")
        self.assertEqual(command.call_count, 3)
