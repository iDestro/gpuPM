"""Offline checks only: no SSH, root, socket or host accounts required."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from native_acceptance_common import CheckFailed, Fixtures, execute, require
from native_ssh_acceptance import (
    change_interactively,
    diagnostic_tail,
    expiry_denied,
    prompt_reply,
    sftp_denied_after_expiry,
)
from native_storage_acceptance import check_reader_file


class PromptTests(unittest.TestCase):
    def test_login_username_new_does_not_select_new_password(self):
        self.assertEqual(
            prompt_reply(b"newuser@127.0.0.1's password: ", "old", "new"), "old"
        )

    def test_diagnostics_redact_before_truncating_and_remove_controls(self):
        old, new = "secretOldPassword", "secretNewPassword"
        transcript = ("noise " * 500 + old + "\x1b[31m " + new + "\x1b[0m").encode()
        text = diagnostic_tail(transcript, old, new, limit=30)
        self.assertNotIn(old, text)
        self.assertNotIn(new, text)
        self.assertNotIn("Password", text)
        self.assertNotIn("\x1b", text)
        self.assertIn("[redacted]", text)
        self.assertNotIn(
            "private-body",
            diagnostic_tail(
                b"-----BEGIN OPENSSH PRIVATE KEY-----\nprivate-body\n", old, new
            ),
        )

    def test_initial_denial_requires_expiry_evidence(self):
        for message in (
            "Connection refused",
            "Permission denied (publickey,password).",
            "Host key verification failed",
        ):
            self.assertFalse(
                expiry_denied(Mock(returncode=255, stdout="", stderr=message))
            )
        self.assertTrue(
            expiry_denied(
                Mock(
                    returncode=1,
                    stdout="",
                    stderr="Password change required but no TTY available.",
                )
            )
        )
        self.assertFalse(
            expiry_denied(
                Mock(
                    returncode=0,
                    stdout="GPUPM_COMMAND_EXECUTED",
                    stderr="Your password has expired",
                )
            )
        )

    def test_sftp_denial_needs_matching_auth_and_paired_expiry(self):
        for mode, auth in (("password", "password"), ("key", "publickey")):
            result = Mock(
                returncode=255,
                stdout="",
                stderr=f'Authenticated to 127.0.0.1 ([127.0.0.1]:22) using "{auth}".\ndebug1: Sending subsystem: sftp\nConnection closed.\n',
            )
            self.assertTrue(sftp_denied_after_expiry(result, mode, True))
            self.assertFalse(sftp_denied_after_expiry(result, mode, False))
            self.assertFalse(
                sftp_denied_after_expiry(
                    result, "key" if mode == "password" else "password", True
                )
            )
            result.stdout = "Remote working directory: /home/test"
            self.assertFalse(sftp_denied_after_expiry(result, mode, True))
        self.assertFalse(
            sftp_denied_after_expiry(
                Mock(
                    returncode=255,
                    stdout="",
                    stderr="Connection closed.\nConnection closed\n",
                ),
                "password",
                True,
            )
        )

    def test_complete_prompts(self):
        for prompt in (
            b"user@127.0.0.1's password: ",
            b"(current) UNIX password:",
            b"Current password:",
        ):
            self.assertEqual(prompt_reply(prompt, "old", "new"), "old")
        for prompt in (
            b"New password:",
            b"Retype new password:",
            b"Enter new UNIX password:",
        ):
            self.assertEqual(prompt_reply(prompt, "old", "new"), "new")

    def test_chinese_password_prompts(self):
        for prompt in ("当前的密码： ", "当前 UNIX 密码:"):
            self.assertEqual(prompt_reply(prompt.encode(), "old", "new"), "old")
        for prompt in (
            "新的密码： ",
            "新的 UNIX 密码：",
            "重新输入新的密码： ",
            "再次输入新的 密码:",
        ):
            self.assertEqual(prompt_reply(prompt.encode(), "old", "new"), "new")

    def test_pty_split_utf8_chinese_prompts_and_success(self):
        program = """import os,time
for prompt, expected in [('当前的密码： ', 'old'), ('新的密码： ', 'new'), ('重新输入新的密码： ', 'new')]:
 for byte in prompt.encode():
  os.write(1,bytes([byte])); time.sleep(.001)
 if input() != expected: raise SystemExit(2)
print('passwd：已成功更新密码', flush=True)
"""
        change_interactively(
            [sys.executable, "-c", program], dict(os.environ), "old", "new"
        )

    def test_partial_and_banner_are_not_prompts(self):
        for text in (
            b"New pass",
            b"Your password has expired.",
            b"Current password:\r\nWrong password\r\n",
        ):
            self.assertIsNone(prompt_reply(text, "old", "new"))

    def test_pty_split_prompts_and_change(self):
        program = """import os,time
for prefix, suffix, expected in [('Current pass', 'word:', 'old'), ('New pass', 'word:', 'new'), ('Retype new pass', 'word:', 'new')]:
 os.write(1,prefix.encode()); time.sleep(.03); os.write(1,suffix.encode())
 if input() != expected: raise SystemExit(2)
print('passwd: password updated successfully', flush=True)
"""
        change_interactively(
            [sys.executable, "-c", program], dict(os.environ), "old", "new"
        )

    def test_pty_failure_diagnostic_redacts_echoed_credentials(self):
        old, new = "OldTestCredential123!", "NewTestCredential456!"
        program = f"print({old!r}); print({new!r}); print('unexpected prompt')"
        with self.assertRaises(CheckFailed) as error:
            change_interactively(
                [sys.executable, "-c", program], dict(os.environ), old, new
            )
        message = str(error.exception)
        self.assertNotIn(old, message)
        self.assertNotIn(new, message)
        self.assertIn("terminal_closed", message)
        self.assertIn("prompts=", message)
        self.assertIn("unexpected prompt", message)

    def test_pty_failure_is_not_success(self):
        with self.assertRaises(CheckFailed):
            change_interactively(
                [sys.executable, "-c", "print('Permission denied')"],
                dict(os.environ),
                "old",
                "new",
            )


class FixtureTests(unittest.TestCase):
    def test_password_is_excluded_from_preview(self):
        fixture = Fixtures.__new__(Fixtures)
        account = {"id": "1234", "uid": 1234, "username": "gpupmqa_test", "revision": 1}
        fixture.names = [account["username"]]
        fixture.agent = Mock()
        fixture.agent.call.side_effect = [[account], {"token": "t"}, account]
        fixture.change(
            account, "update", {"password": "secret", "require_password_change": True}
        )
        preview = fixture.agent.call.call_args_list[1].args[1]
        execution = fixture.agent.call.call_args_list[2].args[1]
        self.assertNotIn("password", preview["changes"])
        self.assertEqual(execution["changes"]["password"], "secret")

    def test_changed_identity_is_refused(self):
        fixture = Fixtures.__new__(Fixtures)
        fixture.names = ["gpupmqa_test"]
        fixture.agent = Mock()
        fixture.agent.call.return_value = [
            {"id": "1234", "uid": 5678, "username": "gpupmqa_test", "revision": 1}
        ]
        with self.assertRaises(CheckFailed):
            fixture.change({"id": "1234", "uid": 1234}, "delete")
        self.assertEqual(fixture.agent.call.call_count, 1)

    def test_cleanup_does_not_target_existing_users(self):
        fixture = Fixtures.__new__(Fixtures)
        fixture.names = ["gpupmqa_test"]
        fixture.agent = Mock()
        account = {"username": "gpupmqa_test", "uid": 1234}
        fixture.accounts = [account]
        fixture.agent.call.return_value = [{"username": "existing"}, account]
        fixture.change = Mock()
        self.assertEqual(fixture.cleanup(), [])
        fixture.change.assert_called_once_with(account, "delete")

    def test_report_does_not_include_exception_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            args = Mock(socket="unused", output=str(output))
            with (
                patch(
                    "native_acceptance_common.Fixtures",
                    side_effect=ValueError("secret password"),
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(execute(args, Mock()), 1)
            self.assertNotIn("secret", output.read_text())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


class StorageEvidenceTests(unittest.TestCase):



    def test_readonly_check_rejects_writable_existing_file(self):
        fixture = Mock()
        fixture.check.side_effect = require
        with (
            patch("native_storage_acceptance.as_user", return_value=Mock(returncode=0)),
            self.assertRaisesRegex(CheckFailed, "existing_file_write_denied"),
        ):
            check_reader_file(fixture, {}, "/unused")

    def test_readonly_check_verifies_content_after_denial(self):
        fixture = Mock()
        fixture.check.side_effect = require
        for content, passes in (("shared\n", True), ("modified\n", False)):
            with patch(
                "native_storage_acceptance.as_user",
                side_effect=[Mock(returncode=1), Mock(returncode=0, stdout=content)],
            ):
                if passes:
                    check_reader_file(fixture, {}, "/unused")
                else:
                    with self.assertRaisesRegex(
                        CheckFailed, "preserves_existing_content"
                    ):
                        check_reader_file(fixture, {}, "/unused")


if __name__ == "__main__":
    unittest.main()
