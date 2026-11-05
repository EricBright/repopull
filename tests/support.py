"""Helpers for building throwaway git repositories in tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_ISOLATED = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(*args: str, cwd: Path) -> str:
    """Run git in `cwd` with an isolated config and fail loudly."""
    env = dict(os.environ)
    env.update(_ISOLATED)
    completed = subprocess.run(
        ("git", *args),
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed in {cwd}:\n{completed.stderr}"
        )
    return completed.stdout


def make_pair(base: Path, name: str = "repo") -> tuple[Path, Path, Path]:
    """Create a bare remote, a seed clone, and a watched clone.

    Returns `(remote, seed, watched)`. All three contain one commit named
    "one" on branch `main`.
    """
    remote = base / "remotes" / f"{name}.git"
    seed = base / "seed" / name
    watched = base / "watched" / name

    remote.parent.mkdir(parents=True, exist_ok=True)
    git("init", "--bare", "--initial-branch=main", str(remote), cwd=base)
    git("clone", str(remote), str(seed), cwd=base)

    (seed / "file.txt").write_text("one\n", encoding="utf-8")
    git("add", "file.txt", cwd=seed)
    git("commit", "-m", "one", cwd=seed)
    git("push", "origin", "main", cwd=seed)

    git("clone", str(remote), str(watched), cwd=base)
    return remote, seed, watched


def commit_upstream(seed: Path, content: str, message: str) -> None:
    """Commit `content` to `file.txt` in the seed clone and push."""
    (seed / "file.txt").write_text(content, encoding="utf-8")
    git("add", "file.txt", cwd=seed)
    git("commit", "-m", message, cwd=seed)
    git("push", "origin", "main", cwd=seed)
