"""Checkpointing so a long scrape can be interrupted and resumed later.

Each pipeline stage owns a small JSON checkpoint file that records which
units of work (URLs, post ids, video ids, ...) have already been processed.
Re-running the stage skips anything already marked done.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import CHECKPOINT_DIR


class Checkpoint:
    """A resumable set of "done" keys plus arbitrary stage state."""

    def __init__(self, company: str, stage: str):
        from slugify import slugify

        self.path = Path(CHECKPOINT_DIR) / f"{slugify(company)}__{stage}.json"
        self._data: dict[str, Any] = {"done": [], "state": {}}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {"done": [], "state": {}}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def done(self) -> set:
        return set(self._data.get("done", []))

    def mark_done(self, key: str) -> None:
        done = self._data.setdefault("done", [])
        if key not in done:
            done.append(key)
        self.save()

    def is_done(self, key: str) -> bool:
        return key in self.done

    def get_state(self, key: str, default: Any = None) -> Any:
        return self._data.get("state", {}).get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        self._data.setdefault("state", {})[key] = value
        self.save()

    def reset(self) -> None:
        self._data = {"done": [], "state": {}}
        self.save()
