"""Run state and log, persisted so the UI survives add-on restarts."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import DATA_DIR

MAX_LOG = 100


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "state.json"
        self._lock = threading.Lock()
        self._s: dict[str, Any] = {
            "last_run_at": None, "last_status": None, "last_message": "",
            "uploaded": [], "log": [],
        }
        try:
            self._s.update(json.loads(self.path.read_text()))
        except (OSError, ValueError):
            pass
        if self._s.get("last_status") == "running":  # interrupted by a restart
            self._s["last_status"] = "error"
            self._s["last_message"] = "Interrupted by a restart."

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._s))

    def set(self, **kw: Any) -> None:
        with self._lock:
            self._s.update(kw)
            self._save()

    def log(self, message: str, level: str = "info") -> None:
        entry = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "level": level, "msg": message}
        with self._lock:
            self._s["log"] = (self._s["log"] + [entry])[-MAX_LOG:]
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._s))
        os.replace(tmp, self.path)
