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

CONFIG_DIRS = (Path("/homeassistant"), Path("/config"), Path("/homeassistant_config"))
TV_DOMAINS = ("samsungtv", "samsungtvws", "smartthings")
SUPERVISOR = "http://supervisor"


def config_entries_path(dirs=CONFIG_DIRS) -> Path | None:
    for d in dirs:
        p = d / ".storage" / "core.config_entries"
        if p.exists():
            return p
    return None


def _entries(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())["data"]["entries"]


def _host_of(data: dict[str, Any]) -> str | None:
    return data.get("host") or data.get("ip_address") or data.get("ip")


def device_names(path: Path | None = None, dirs=CONFIG_DIRS) -> list[dict[str, Any]]:
    """Samsung / SmartThings devices known to HA's device registry (no IPs, but names + MACs).

    SmartThings is cloud-based, so HA never learns the TV's IP; these names are used to label
    TVs found by a network scan.
    """
    if path is None:
        for d in dirs:
            if (d / ".storage" / "core.device_registry").exists():
                path = d / ".storage" / "core.device_registry"
                break
    if not path:
        return []
    try:
        devices = json.loads(path.read_text())["data"]["devices"]
    except (OSError, ValueError, KeyError):
        return []
    out = []
    for dev in devices:
        domains = {i[0] for i in dev.get("identifiers", []) if i}
        maker = (dev.get("manufacturer") or "").lower()
        if not (domains & set(TV_DOMAINS)) and "samsung" not in maker:
            continue
        macs = [c[1].lower() for c in dev.get("connections", []) if c and c[0] == "mac"]
        name = dev.get("name_by_user") or dev.get("name")
        if name:
            out.append({"name": name, "model": dev.get("model"), "macs": macs,
                        "integration": sorted(domains & set(TV_DOMAINS))})
    return out


def label_scanned(tvs: list[dict[str, Any]], devices: list[dict[str, Any]]) -> None:
    """Add ``ha_name`` to scanned TVs matching an HA device by MAC, else by a unique model."""
    for tv in tvs:
        mac = (tv.get("mac") or "").replace("-", ":").lower()
        match = next((d for d in devices if mac and mac in d["macs"]), None)
        if match is None and tv.get("model"):
            same = [d for d in devices if d.get("model") == tv["model"]]
            match = same[0] if len(same) == 1 else None
        if match:
            tv["ha_name"] = match["name"]


def discover_tvs(path: Path | None = None) -> list[dict[str, Any]]:
    return discovery_info(path)["tvs"]


def discovery_info(path: Path | None = None, dirs=CONFIG_DIRS) -> dict[str, Any]:
    """TVs found in HA's config entries, plus a human-readable reason if none."""
    info: dict[str, Any] = {"tvs": [], "reason": "", "ha_devices": []}
    path = path or config_entries_path(dirs)
    if not path:
        checked = ", ".join(f"{d} ({'exists' if d.exists() else 'missing'})" for d in dirs)
        info["ha_devices"] = device_names(dirs=dirs)
        info["reason"] = ("Home Assistant's config folder isn't visible to the add-on "
                          f"(looked in: {checked}). Reinstall/rebuild the add-on so the "
                          "'homeassistant_config' mapping is applied.")
        return info
    try:
        entries = _entries(path)
    except (OSError, ValueError, KeyError) as exc:
        log.warning("Could not read Home Assistant config entries", exc_info=True)
        info["reason"] = f"Couldn't read {path}: {exc}"
        return info
    for e in entries:
        data = e.get("data") or {}
        host = _host_of(data)
        if e.get("domain") not in TV_DOMAINS or not host:
            continue
        info["tvs"].append({
            "name": e.get("title") or data.get("name") or host,
            "host": host,
            "mac": data.get("mac"),
            "model": data.get("model"),
            "port": data.get("port"),
            "integration": e.get("domain"),
        })
    info["ha_devices"] = device_names(dirs=dirs)
    if not info["tvs"]:
        domains = sorted({e.get("domain", "?") for e in entries})
        has_domain = [e for e in entries if e.get("domain") in TV_DOMAINS]
        info["reason"] = (
            f"Read {len(entries)} integrations but none were a Samsung TV with an IP address "
            + (f"({len(has_domain)} Samsung entries had no host)." if has_domain else
               f"(integrations present: {', '.join(domains)}).")
        )
    return info


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
