"""Persistent add-on settings, stored as JSON under the add-on's /data volume."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

SECRET_KEYS = ("icloud_password",)
SECRET_MASK = "********"

DEFAULTS: dict[str, Any] = {
    # Photo source
    "source_type": "public",  # "public" | "private"
    "public_url": "",
    "icloud_apple_id": "",
    "icloud_password": "",
    "private_album_id": "",
    "private_album_name": "",
    # TV
    "tv_host": "",
    "tv_name": "",
    "tv_port": 8002,
    # Schedule
    "schedule_enabled": True,
    "frequency": "daily",  # daily | weekly | monthly
    "time": "03:00",
    "weekday": 0,  # 0 = Monday
    "day_of_month": 1,
    # Sync behaviour
    "photo_count": 10,
    "selection": "newest",  # newest | random
    "replace_previous": True,
    "matte": "none",
    "image_fit": "crop",  # crop | blur | none
    "select_first": True,
    "enable_art_mode": False,
}

CHOICES = {
    "source_type": ("public", "private"),
    "frequency": ("daily", "weekly", "monthly"),
    "selection": ("newest", "random"),
    "image_fit": ("crop", "blur", "none"),
}


class SettingsError(ValueError):
    pass


def _coerce(key: str, value: Any) -> Any:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{key} must be a number") from None
    return "" if value is None else str(value).strip() if key != "icloud_password" else str(value)


def validate(values: dict[str, Any]) -> dict[str, Any]:
    for key, allowed in CHOICES.items():
        if values[key] not in allowed:
            raise SettingsError(f"{key} must be one of: {', '.join(allowed)}")
    hh, _, mm = values["time"].partition(":")
    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
        raise SettingsError("time must be HH:MM (24 hour)")
    values["time"] = f"{int(hh):02d}:{int(mm):02d}"
    if not 0 <= values["weekday"] <= 6:
        raise SettingsError("weekday must be 0-6")
    if not 1 <= values["day_of_month"] <= 31:
        raise SettingsError("day_of_month must be 1-31")
    if not 1 <= values["photo_count"] <= 100:
        raise SettingsError("photo_count must be 1-100")
    if not 1 <= values["tv_port"] <= 65535:
        raise SettingsError("tv_port must be 1-65535")
    return values


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "settings.json"
        self._lock = threading.Lock()
        self._values = self._load()

    def _load(self) -> dict[str, Any]:
        values = dict(DEFAULTS)
        try:
            stored = json.loads(self.path.read_text())
        except (OSError, ValueError):
            stored = {}
        for key in DEFAULTS:
            if key in stored:
                try:
                    values[key] = _coerce(key, stored[key])
                except SettingsError:
                    pass
        return values

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def public(self) -> dict[str, Any]:
        """Settings safe to send to the browser (secrets masked)."""
        values = self.get()
        for key in SECRET_KEYS:
            values[key] = SECRET_MASK if values[key] else ""
        return values

    def update(self, incoming: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            new = dict(self._values)
            for key, value in incoming.items():
                if key not in DEFAULTS:
                    continue
                if key in SECRET_KEYS and value == SECRET_MASK:
                    continue  # unchanged
                new[key] = _coerce(key, value)
            validate(new)
            self._values = new
            self._write(new)
            return dict(new)

    def _write(self, values: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(values, fh, indent=2)
        os.replace(tmp, self.path)
