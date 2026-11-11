"""Typed, thin wrappers around the git CLI.

Every function runs git with a timeout, a non-interactive environment, and a
stable locale. Nothing here mutates a repository except the four explicitly
named mutating helpers at the bottom.
"""

from __future__ import annotations

import codecs
import os
import re
import selectors
import signal
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event

_ASKPASS = "/bin/true" if Path("/bin/true").exists() else "true"
_SETPRIV = shutil.which("setpriv")
_SETPRIV_SUPPORTED: bool | None = None


def _parent_death_launcher() -> tuple[str, ...]:
    """Return a setpriv prefix when this host supports --pdeathsig."""
    global _SETPRIV_SUPPORTED
    if _SETPRIV is None:
        return ()
    if _SETPRIV_SUPPORTED is None:
        try:
            probe = subprocess.run(
                [_SETPRIV, "--pdeathsig", "TERM", "--", _ASKPASS],
                capture_output=True,
                timeout=2,
                check=False,
            )
            _SETPRIV_SUPPORTED = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _SETPRIV_SUPPORTED = False
    if not _SETPRIV_SUPPORTED:
        return ()
    return (_SETPRIV, "--pdeathsig", "TERM", "--")

_CREDENTIALS = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@\s]+)@"
)

_SCRUBBED_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_EXEC_PATH",
        "GIT_TEMPLATE_DIR",
        "GIT_PROXY_COMMAND",
    }
)

_NETWORK_MARKERS = (
    "could not resolve host",
    "temporary failure in name resolution",
    "name or service not known",
    "network is unreachable",
    "no route to host",
    "connection timed out",
    "connection refused",
    "connection reset by peer",
    "connection closed",
    "could not connect to server",
    "failed to connect",
    "early eof",
    "remote end hung up unexpectedly",
    "unexpected disconnect",
    "rpc failed",
    "ssl connection timeout",
    "gnutls_handshake",
    "operation timed out",
    "proxy",
    "tunnel connection failed",
    "the remote end hung up",
)


class GitError(RuntimeError):
    """Raised when a git command that must succeed fails."""


@dataclass(frozen=True, slots=True)
class GitResult:
    """Outcome of one git invocation."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timeout_s: float
    timed_out: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        """True when git exited 0 and did not time out or cancel."""
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    def summary(self, *, limit: int = 200) -> str:
        """One-line description, suitable for a report cell."""
        if self.cancelled:
            return "cancelled"
        if self.timed_out:
            return f"timed out after {self.timeout_s:g}s"
        text = _redact((self.stderr or self.stdout).strip())
        if not text:
            return f"git exited {self.returncode}"
        line = text.splitlines()[-1].strip()
        return line[:limit]


def _redact(text: str) -> str:
    """Remove URL userinfo from git's error text before it reaches a log."""
    return _CREDENTIALS.sub(r"\1***@", text)


def is_network_error(result: GitResult) -> bool:
    """True when a failed command looks like a network outage, not a repo error."""
    if result.cancelled:
        return False
    if result.timed_out:
        return True
    text = f"{result.stderr}\n{result.stdout}".casefold()
    return any(marker in text for marker in _NETWORK_MARKERS)


def _signal_process_group(
    process: subprocess.Popen[str], sig: signal.Signals
) -> None:
    """Signal the child's process group, ignoring an already-dead child."""
    try:
        os.killpg(process.pid, sig)
    except OSError:
        pass


def _terminate_process_group(
    process: subprocess.Popen[str],
) -> tuple[str, str]:
    """Stop git and any remote helper it spawned, then drain the pipes.

    This is the cleanup path for timeout, cancellation, and any exception from
    `communicate()`. It must never leave a live child behind and must not mask
    the caller's exception with a second failure from a closed pipe.
    """
    _signal_process_group(process, signal.SIGTERM)
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        _signal_process_group(process, signal.SIGKILL)
    except Exception:
        _signal_process_group(process, signal.SIGKILL)
    try:
        return process.communicate(timeout=5)
    except Exception:
        # Pipes may already be closed; reap without them as a last resort.
        try:
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return "", ""


def _git_env(extra: Mapping[str, str] | None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _SCRUBBED_ENV
        and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = _ASKPASS
    env["GIT_PAGER"] = "cat"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["LC_ALL"] = "C"
    if extra:
        env.update(extra)
    return env


def _wait_captured(
    process: subprocess.Popen[str],
    *,
    command: tuple[str, ...],
    timeout: float,
    cancel: Event | None,
) -> GitResult:
    """Wait for git to exit and collect its output in one piece."""
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    stdout, stderr = _terminate_process_group(process)
                    return GitResult(
                        args=command,
                        returncode=130,
                        stdout=stdout,
                        stderr=stderr,
                        timeout_s=timeout,
                        cancelled=True,
                    )
                if time.monotonic() >= deadline:
                    stdout, stderr = _terminate_process_group(process)
                    return GitResult(
                        args=command,
                        returncode=124,
                        stdout=stdout,
                        stderr=stderr,
                        timeout_s=timeout,
                        timed_out=True,
                    )
    except BaseException:
        # communicate() can raise for a closed or undecodable pipe, and
        # KeyboardInterrupt can arrive mid-wait. Kill the group before the
        # exception leaves, then preserve the original failure.
        _terminate_process_group(process)
        raise
    return GitResult(
        args=command,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
        timeout_s=timeout,
    )


def _wait_streaming(
    process: subprocess.Popen[str],
    *,
    command: tuple[str, ...],
    timeout: float,
    cancel: Event | None,
    on_stderr: Callable[[str], None],
) -> GitResult:
    """Wait for git while handing stderr fragments to `on_stderr` as they land.

    `git clone --progress` rewrites its progress line with a carriage return,
    so fragments are split on both CR and LF. Readiness comes from a selector
    over the pipe descriptors, and the bytes are read from the descriptor so
    the pipes cannot deadlock on a full buffer. Cancellation, the deadline,
    and the process-group kill are the same ones `_wait_captured` uses.
    """
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    raw: dict[str, list[str]] = {"stdout": [], "stderr": []}
    decoders = {
        name: codecs.getincrementaldecoder("utf-8")("replace") for name in raw
    }
    pending = ""
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        if stream is not None:
            selector.register(stream.fileno(), selectors.EVENT_READ, name)

    def consume(chunk: bytes) -> None:
        nonlocal pending
        text = decoders["stderr"].decode(chunk)
        if not text:
            return
        raw["stderr"].append(text)
        fragments = re.split(r"[\r\n]", pending + text)
        pending = fragments.pop()
        for fragment in fragments:
            if fragment.strip():
                on_stderr(fragment)

    try:
        while True:
            if cancel is not None and cancel.is_set():
                stdout, stderr = _terminate_process_group(process)
                return GitResult(
                    args=command,
                    returncode=130,
                    stdout="".join(raw["stdout"]) + stdout,
                    stderr="".join(raw["stderr"]) + stderr,
                    timeout_s=timeout,
                    cancelled=True,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stdout, stderr = _terminate_process_group(process)
                return GitResult(
                    args=command,
                    returncode=124,
                    stdout="".join(raw["stdout"]) + stdout,
                    stderr="".join(raw["stderr"]) + stderr,
                    timeout_s=timeout,
                    timed_out=True,
                )
            for key, _ in selector.select(timeout=min(0.2, remaining)):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fd)
                elif key.data == "stdout":
                    raw["stdout"].append(decoders["stdout"].decode(chunk))
                else:
                    consume(chunk)
            if not selector.get_map() and process.poll() is not None:
                break
    except BaseException:
        _terminate_process_group(process)
        raise
    finally:
        selector.close()
        # communicate() closes the pipes on the stop paths; the successful
        # path read them directly, so close them here or they stay open until
        # the garbage collector complains.
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    return GitResult(
        args=command,
        returncode=process.returncode,
        stdout="".join(raw["stdout"]),
        stderr="".join(raw["stderr"]),
        timeout_s=timeout,
    )


def run_git(
    repo: Path,
    *args: str,
    timeout: float,
    env: Mapping[str, str] | None = None,
    cancel: Event | None = None,
    on_stderr: Callable[[str], None] | None = None,
) -> GitResult:
    """Run `git -C <repo> <args...>` and capture its output.

    With `on_stderr`, the command is streamed instead of captured whole: each
    progress fragment is passed to the callback as it arrives, so a long clone
    can report progress before it finishes.
    """
    command = (
        *_parent_death_launcher(),
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repo),
        *args,
    )
    if cancel is not None and cancel.is_set():
        return GitResult(
            args=command,
            returncode=130,
            stdout="",
            stderr="cancelled",
            timeout_s=timeout,
            cancelled=True,
        )
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_git_env(env),
            # A new session lets timeout/cancel kill the whole git group. A
            # SIGKILL of repopull itself is still outside this mechanism.
            start_new_session=True,
        )
    except OSError as exc:
        return GitResult(
            args=command,
            returncode=127,
            stdout="",
            stderr=str(exc),
            timeout_s=timeout,
        )
    if on_stderr is None:
        return _wait_captured(
            process, command=command, timeout=timeout, cancel=cancel
        )
    return _wait_streaming(
        process,
        command=command,
        timeout=timeout,
        cancel=cancel,
        on_stderr=on_stderr,
    )


def _require(result: GitResult) -> str:
    if not result.ok:
        raise GitError(result.summary())
    return result.stdout.strip()


def head_sha(repo: Path, *, timeout: float) -> str | None:
    """Commit SHA at HEAD, or None when HEAD is unborn (an empty repo)."""
    result = run_git(
        repo, "rev-parse", "--verify", "--quiet", "HEAD", timeout=timeout
    )
    if not result.ok:
        return None
    sha = result.stdout.strip()
    return sha or None


def current_branch(repo: Path, *, timeout: float) -> str | None:
    """Current branch name, or None when HEAD is detached."""
    name = _require(run_git(repo, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout))
    return None if name == "HEAD" else name


def upstream_ref(repo: Path, *, branch: str | None, timeout: float) -> str | None:
    """Tracking ref for `branch`, falling back to `origin/<branch>`.

    Some clones have no configured upstream even though the matching remote
    branch exists (for example a clone made without `--track`). The fallback
    keeps those repositories syncable without rewriting their config.
    """
    configured = run_git(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}",
        timeout=timeout,
    )
    if configured.ok:
        ref = configured.stdout.strip()
        if ref and "@{u}" not in ref:
            return ref

    if branch:
        candidate = f"origin/{branch}"
        exists = run_git(
            repo,
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/remotes/{candidate}",
            timeout=timeout,
        )
        if exists.ok:
            return candidate
    return None


def is_dirty(repo: Path, *, timeout: float) -> bool:
    """True when tracked files differ from HEAD.

    Untracked files are deliberately excluded: build artefacts are normal in
    a watched copy and must never block a sync.
    """
    result = run_git(
        repo,
        "status",
        "--porcelain",
        "--untracked-files=no",
        timeout=timeout,
    )
    return bool(_require(result))


def ahead_behind(repo: Path, upstream: str, *, timeout: float) -> tuple[int, int]:
    """Return `(ahead, behind)` of HEAD relative to `upstream`."""
    output = _require(
        run_git(
            repo,
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...{upstream}",
            timeout=timeout,
        )
    )
    parts = output.split()
    if len(parts) != 2:
        raise GitError(f"cannot parse ahead/behind for {repo}: {output!r}")
    return int(parts[0]), int(parts[1])


def is_shallow(repo: Path, *, timeout: float) -> bool:
    """True for a shallow clone."""
    output = _require(
        run_git(repo, "rev-parse", "--is-shallow-repository", timeout=timeout)
    )
    return output == "true"


def uses_lfs(repo: Path, *, timeout: float, rev: str | None = None) -> bool:
    """True when a `.gitattributes` in `rev` (or the working tree) enables LFS."""
    args = ["grep", "-l", "-F", "-e", "filter=lfs"]
    if rev is not None:
        args.append(rev)
    args.extend(["--", "*.gitattributes"])
    result = run_git(repo, *args, timeout=timeout)
    return result.ok and bool(result.stdout.strip())


def has_submodules(repo: Path) -> bool:
    """True when the repository declares submodules."""
    return (repo / ".gitmodules").is_file()


def git_lfs_available() -> bool:
    """True when the `git-lfs` binary is installed."""
    return shutil.which("git-lfs") is not None


def git_lfs_version() -> str | None:
    """The installed `git-lfs` version line, or None."""
    binary = shutil.which("git-lfs")
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def git_lfs_enabled(repo: Path, *, timeout: float) -> bool:
    """True when the effective git config has the LFS filters.

    `git-lfs` being on PATH is not enough: `git lfs install` must also write
    `filter.lfs.clean` and `filter.lfs.smudge`. Checking the effective config in
    the repository covers system, global and local scopes.
    """
    result = run_git(
        repo,
        "config",
        "--get-regexp",
        r"^filter\.lfs\.",
        timeout=timeout,
    )
    if not result.ok:
        return False
    keys = {
        line.split(None, 1)[0]
        for line in result.stdout.splitlines()
        if line.strip()
    }
    return {"filter.lfs.clean", "filter.lfs.smudge"} <= keys


def git_lfs_enabled_global() -> bool:
    """True when the user or system git config has the LFS filters."""
    for scope in ("--system", "--global"):
        try:
            completed = subprocess.run(
                ["git", "config", scope, "--get", "filter.lfs.clean"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0 and completed.stdout.strip():
            return True
    return False


def fetch(
    repo: Path,
    *,
    timeout: float,
    cancel: Event | None = None,
) -> GitResult:
    """Fetch and prune `origin` without printing progress."""
    return run_git(
        repo,
        "fetch",
        "--prune",
        "--quiet",
        "--no-progress",
        "origin",
        timeout=timeout,
        cancel=cancel,
    )


def fast_forward(
    repo: Path,
    upstream: str,
    *,
    timeout: float,
    cancel: Event | None = None,
) -> GitResult:
    """Advance the current branch to `upstream`, refusing anything else."""
    return run_git(
        repo,
        "merge",
        "--ff-only",
        "--no-edit",
        upstream,
        timeout=timeout,
        cancel=cancel,
    )


def hard_reset(
    repo: Path,
    upstream: str,
    *,
    timeout: float,
    cancel: Event | None = None,
) -> GitResult:
    """Reset the current branch to `upstream`, discarding local commits."""
    return run_git(
        repo,
        "reset",
        "--hard",
        upstream,
        timeout=timeout,
        cancel=cancel,
    )


def update_submodules(
    repo: Path,
    *,
    timeout: float,
    cancel: Event | None = None,
) -> GitResult:
    """Initialise and update submodules recursively."""
    return run_git(
        repo,
        "submodule",
        "update",
        "--init",
        "--recursive",
        "--quiet",
        timeout=timeout,
        cancel=cancel,
    )
