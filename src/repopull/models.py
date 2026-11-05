"""Shared, dependency-free data types for repopull."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class Outcome(str, Enum):
    """Terminal state of one repository in a run."""

    UPDATED = "updated"
    UP_TO_DATE = "up-to-date"
    BEHIND = "behind"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RepoRef:
    """A discovered repository and the label used to address it."""

    path: Path
    label: str

    @property
    def name(self) -> str:
        """Basename, useful for glob matching."""
        return self.path.name


@dataclass(frozen=True, slots=True)
class RepoState:
    """A repository's local state at one instant."""

    ref: RepoRef
    branch: str | None
    upstream: str | None
    dirty: bool
    ahead: int
    behind: int
    shallow: bool
    uses_lfs: bool
    has_submodules: bool
    lfs_enabled: bool = False
    error: str | None = None

    @property
    def has_upstream(self) -> bool:
        """True when a tracking ref could be resolved."""
        return self.upstream is not None

    @property
    def is_detached(self) -> bool:
        """True when HEAD is not on a branch."""
        return self.branch is None


@dataclass(frozen=True, slots=True)
class Row:
    """One line of a report."""

    label: str
    branch: str
    outcome: Outcome
    commits: int
    detail: str


@dataclass(frozen=True, slots=True)
class Report:
    """The brief produced by a status or sync run."""

    mode: str
    started_at: datetime
    elapsed_s: float
    rows: tuple[Row, ...]
    log_path: Path | None = None

    def count(self, outcome: Outcome) -> int:
        """Number of rows with `outcome`."""
        return sum(1 for row in self.rows if row.outcome is outcome)

    @property
    def totals(self) -> dict[Outcome, int]:
        """Count per outcome, including zeroes."""
        return {outcome: self.count(outcome) for outcome in Outcome}

    @property
    def has_errors(self) -> bool:
        """True when at least one repo errored."""
        return self.count(Outcome.ERROR) > 0
