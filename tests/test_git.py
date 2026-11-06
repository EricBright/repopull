"""Tests for git result classification, redaction, and process cleanup."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, Timer
from unittest.mock import patch

from repopull.git import GitResult, _git_env, is_network_error, run_git


def _result(
    *,
    stderr: str = "",
    stdout: str = "",
    timed_out: bool = False,
) -> GitResult:
    return GitResult(
        args=("git",),
        returncode=124 if timed_out else 128,
        stdout=stdout,
        stderr=stderr,
        timeout_s=30,
        timed_out=timed_out,
    )


class NetworkClassificationTests(unittest.TestCase):
    def test_dns_and_transport_failures_are_network(self) -> None:
        for text in (
            "fatal: unable to access 'https://example/repo': Could not resolve host: example",
            "ssh: connect to host example port 22: Connection timed out",
            "fatal: the remote end hung up unexpectedly",
            "error: RPC failed; curl 56 GnuTLS recv error",
            "fatal: unable to access: Connection reset by peer",
        ):
            self.assertTrue(is_network_error(_result(stderr=text)), text)

    def test_timeout_is_network(self) -> None:
        self.assertTrue(is_network_error(_result(timed_out=True)))

    def test_repo_and_auth_errors_are_not_network(self) -> None:
        for text in (
            "fatal: not a git repository",
            "fatal: Authentication failed for 'https://example/repo'",
            "fatal: couldn't find remote ref main",
            "error: Your local changes would be overwritten",
        ):
            self.assertFalse(is_network_error(_result(stderr=text)), text)

    def test_summary_redacts_url_userinfo(self) -> None:
        result = _result(
            stderr="fatal: unable to access 'https://user:secret@example/repo'"
        )

        summary = result.summary()

        self.assertNotIn("secret", summary)
        self.assertNotIn("user", summary)
        self.assertIn("https://***@example/repo", summary)

    def test_summary_redacts_token_username(self) -> None:
        result = _result(
            stderr="fatal: unable to access 'https://ghp_token@example/repo'"
        )

        summary = result.summary()

        self.assertNotIn("ghp_token", summary)
        self.assertIn("https://***@example/repo", summary)


class EnvironmentTests(unittest.TestCase):
    def test_repo_locating_and_injected_config_are_scrubbed(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GIT_DIR": "/tmp/elsewhere",
                "GIT_WORK_TREE": "/tmp/elsewhere",
                "GIT_INDEX_FILE": "/tmp/index",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.sshCommand",
                "GIT_CONFIG_VALUE_0": "bad",
                "KEEP_ME": "yes",
            },
            clear=False,
        ):
            env = _git_env(None)

        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_WORK_TREE", env)
        self.assertNotIn("GIT_INDEX_FILE", env)
        self.assertNotIn("GIT_CONFIG_COUNT", env)
        self.assertNotIn("GIT_CONFIG_KEY_0", env)
        self.assertNotIn("GIT_CONFIG_VALUE_0", env)
        self.assertEqual(env["KEEP_ME"], "yes")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")


@unittest.skipUnless(sys.platform.startswith("linux"), "process groups are POSIX")
class ProcessGroupTests(unittest.TestCase):
    def test_cancel_stops_the_git_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            fake_bin = base / "bin"
            fake_bin.mkdir()
            pid_file = base / "child.pid"
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/bin/sh\n"
                "sleep 30 &\n"
                "echo $! > \"$PIDFILE\"\n"
                "wait\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o755)
            cancel = Event()
            timer = Timer(0.2, cancel.set)
            timer.start()
            self.addCleanup(timer.cancel)

            result = run_git(
                repo,
                "fetch",
                timeout=30,
                cancel=cancel,
                env={
                    "PATH": f"{fake_bin}:/usr/bin:/bin",
                    "PIDFILE": str(pid_file),
                },
            )

            self.assertTrue(result.cancelled)
            self.assertEqual(result.summary(), "cancelled")
            self.assertTrue(pid_file.is_file())
            child = int(pid_file.read_text(encoding="utf-8").strip())
            for _ in range(20):
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"child process {child} survived cancellation")

    def test_timeout_stops_the_git_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            fake_bin = base / "bin"
            fake_bin.mkdir()
            pid_file = base / "child.pid"
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/bin/sh\n"
                "sleep 30 &\n"
                "echo $! > \"$PIDFILE\"\n"
                "wait\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o755)

            result = run_git(
                repo,
                "fetch",
                timeout=0.3,
                env={
                    "PATH": f"{fake_bin}:/usr/bin:/bin",
                    "PIDFILE": str(pid_file),
                },
            )

            self.assertTrue(result.timed_out)
            self.assertTrue(pid_file.is_file())
            child = int(pid_file.read_text(encoding="utf-8").strip())
            for _ in range(20):
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"child process {child} survived the timeout")
