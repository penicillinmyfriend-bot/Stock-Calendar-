"""Persistence: the roadmap, the journal, and per-run state.

* ``ROADMAP.md`` -- the agent's persistent goal + plan (read each session).
* ``JOURNAL.md`` -- an append-only log; one summary block per session.
* ``state.json`` -- machine state kept in the (git-ignored) state dir:
  the commit HEAD was at when the session started (the rollback point) and the
  last commit that passed tests (the last-good commit).

Keeping these on disk is what lets progress -- and the ability to roll back --
carry across runs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

JOURNAL_SEPARATOR = "\n\n---\n\n"


@dataclass
class RunState:
    """Machine-readable state that survives between runs."""

    session_start_commit: Optional[str] = None
    last_good_commit: Optional[str] = None
    last_session: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunState":
        return cls(
            session_start_commit=data.get("session_start_commit"),
            last_good_commit=data.get("last_good_commit"),
            last_session=data.get("last_session", {}) or {},
        )


class Persistence:
    """Reads/writes the roadmap, journal, and run state."""

    def __init__(
        self,
        *,
        roadmap_path: Path | str,
        journal_path: Path | str,
        state_dir: Path | str,
    ) -> None:
        self.roadmap_path = Path(roadmap_path)
        self.journal_path = Path(journal_path)
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / "state.json"

    # --- roadmap ----------------------------------------------------------
    def read_roadmap(self) -> str:
        if self.roadmap_path.exists():
            return self.roadmap_path.read_text(encoding="utf-8")
        return "# Roadmap\n\n(empty)\n"

    def write_roadmap(self, text: str) -> None:
        self.roadmap_path.write_text(text, encoding="utf-8")

    # --- journal ----------------------------------------------------------
    def read_journal(self) -> str:
        if self.journal_path.exists():
            return self.journal_path.read_text(encoding="utf-8")
        return ""

    def append_journal(self, entry: str) -> None:
        existing = self.read_journal()
        sep = JOURNAL_SEPARATOR if existing.strip() else "\n"
        with self.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(sep + entry.rstrip() + "\n")

    def latest_journal_entry(self) -> str:
        text = self.read_journal()
        if not text.strip():
            return "(journal is empty)"
        return text.split(JOURNAL_SEPARATOR)[-1].strip()

    # --- state ------------------------------------------------------------
    def load_state(self) -> RunState:
        if self.state_path.exists():
            try:
                return RunState.from_dict(json.loads(self.state_path.read_text("utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return RunState()

    def save_state(self, state: RunState) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")

    def record_session_start(self, commit: Optional[str]) -> RunState:
        state = self.load_state()
        state.session_start_commit = commit
        self.save_state(state)
        return state

    def record_good_commit(self, commit: str) -> RunState:
        state = self.load_state()
        state.last_good_commit = commit
        self.save_state(state)
        return state

    def record_session_summary(self, summary: Dict[str, Any]) -> RunState:
        state = self.load_state()
        state.last_session = summary
        self.save_state(state)
        return state


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
