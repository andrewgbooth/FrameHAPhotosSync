"""Discover Samsung TVs already set up in Home Assistant.

The add-on mounts the HA config read-only and reads the ``samsungtv`` config
entries, which hold each TV's host and MAC, so users can pick a TV from a list
instead of typing an IP address.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

log = logging.getLogger(__name__)

CONFIG_DIRS = (Path("/homeassistant"), Path("/config"))
SUPERVISOR = "http://supervisor"


def config_entries_path(dirs=CONFIG_DIRS) -> Path | None:
    for d in dirs:
        p = d / ".storage" / "core.config_entries"
        if p.exists():
            return p
    return None


def discover_tvs(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or config_entries_path()
    if not path:
        return []
    try:
        entries = json.loads(path.read_text())["data"]["entries"]
    except (OSError, ValueError, KeyError):
        log.warning("Could not read Home Assistant config entries", exc_info=True)
        return []
    tvs = []
    for e in entries:
        if e.get("domain") != "samsungtv":
            continue
        data = e.get("data") or {}
        host = data.get("host")
        if not host:
            continue
        tvs.append({
            "name": e.get("title") or data.get("name") or host,
            "host": host,
            "mac": data.get("mac"),
            "model": data.get("model"),
            "port": data.get("port"),
        })
    return tvs


def timezone():
    """Home Assistant's configured time zone (falls back to $TZ / UTC)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    name = None
    if token:
        try:
            r = requests.get(f"{SUPERVISOR}/core/api/config",
                             headers={"Authorization": f"Bearer {token}"}, timeout=5)
            name = r.json().get("time_zone")
        except (requests.RequestException, ValueError):
            pass
    for candidate in (name, os.environ.get("TZ"), "UTC"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    return ZoneInfo("UTC")
