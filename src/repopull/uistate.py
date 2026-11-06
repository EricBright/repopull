"""Small, non-critical UI state remembered across GUI launches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

UI_STATE_FILE = "ui-state.json"
_PAGES = frozenset({"library", "settings", "detail"})
_FILTERS = frozenset({"all", "behind", "skipped", "errors"})


@dataclass(frozen=True, slots=True)
class UiState:
    """The page, filter, and detail selection from the last session."""

    page: str = "library"
    filter: str = "all"
    repo: str = ""


def _state_path(config_path: Path) -> Path:
    return config_path.with_name(UI_STATE_FILE)


def load_ui_state(config_path: Path | None) -> UiState | None:
    """Read UI state next to the config, or None when absent/malformed."""
    if config_path is None:
        return None
    try:
        data = json.loads(_state_path(config_path).read_text(encoding="utf-8"))
        page = str(data.get("page", "library"))
        filter_name = str(data.get("filter", "all"))
        repo = str(data.get("repo", ""))
    except (OSError, TypeError, ValueError):
        return None
    if page not in _PAGES or filter_name not in _FILTERS:
        return None
    return UiState(page=page, filter=filter_name, repo=repo)


def save_ui_state(config_path: Path | None, state: UiState) -> None:
    """Best-effort atomic write; UI state is never worth failing a run over."""
    if config_path is None:
        return
    path = _state_path(config_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "page": state.page,
                    "filter": state.filter,
                    "repo": state.repo,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        return
