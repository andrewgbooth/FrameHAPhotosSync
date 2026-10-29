"""Client for public iCloud shared albums ("Public Website" links).

Uses the same unauthenticated ``sharedstreams`` web endpoints the
icloud.com/sharedalbum page uses; no Apple ID is required.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from . import Photo, SourceError, newest_first

_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_TOKEN_RE = re.compile(r"^[0-9A-Za-z]{8,}$")
_ASSET_BATCH = 25
TIMEOUT = 30


def parse_token(url_or_token: str) -> str:
    """Extract the album token from a share URL (``https://www.icloud.com/sharedalbum/#TOKEN``)."""
    value = url_or_token.strip()
    if not value:
        raise SourceError("Enter the public shared album link.")
    if "://" in value or "/" in value or "#" in value:
        parsed = urlparse(value if "://" in value else "https://" + value)
        value = parsed.fragment or parsed.path.rstrip("/").rsplit("/", 1)[-1]
        value = value.lstrip("#")
    if not _TOKEN_RE.match(value):
        raise SourceError("That doesn't look like an iCloud shared album link.")
    return value


def base_url(token: str) -> str:
    try:
        if token[0] == "A":
            partition = _B62.index(token[1])
        else:
            partition = _B62.index(token[1]) * 62 + _B62.index(token[2])
    except (ValueError, IndexError):
        raise SourceError("Invalid shared album token.") from None
    return f"https://p{partition:02d}-sharedstreams.icloud.com/{token}/sharedstreams/"


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class PublicAlbum:
    def __init__(self, url_or_token: str, session: requests.Session | None = None) -> None:
        self.token = parse_token(url_or_token)
        self.base = base_url(self.token)
        self.session = session or requests.Session()
        self.name = ""

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self.session.post(self.base + endpoint, json=payload, timeout=TIMEOUT)
            if resp.status_code == 330:  # partition redirect
                host = resp.json().get("X-Apple-MMe-Host")
                if not host:
                    raise SourceError("iCloud redirected without a host.")
                self.base = f"https://{host}/{self.token}/sharedstreams/"
                resp = self.session.post(self.base + endpoint, json=payload, timeout=TIMEOUT)
            if resp.status_code in (401, 403, 404):
                raise SourceError("Album not found. Is the link correct and 'Public Website' enabled?")
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise SourceError(f"Could not reach iCloud: {exc}") from exc
        except ValueError as exc:
            raise SourceError("iCloud returned an unexpected response.") from exc

    def photos(self) -> list[Photo]:
        stream = self._post("webstream", {"streamCtag": None})
        self.name = stream.get("streamName", "")
        entries = [
            p for p in stream.get("photos", [])
            if p.get("mediaAssetType", "photo") != "video" and p.get("derivatives")
        ]
        urls = self._asset_urls([p["photoGuid"] for p in entries])

        photos: list[Photo] = []
        for entry in entries:
            derivs = entry["derivatives"]
            sized = sorted(
                ((int(d.get("width") or 0) * int(d.get("height") or 0), d["checksum"])
                 for d in derivs.values() if d.get("checksum")),
            )
            if not sized:
                continue
            checksums = {"thumb": _pick_thumb(sized), "full": sized[-1][1]}
            photos.append(Photo(
                id=entry["photoGuid"],
                taken=_parse_date(entry.get("dateCreated") or entry.get("batchDateCreated")),
                fetch=self._make_fetch(checksums, urls),
                caption=entry.get("caption", "") or "",
            ))
        return newest_first(photos)

    def _asset_urls(self, guids: list[str]) -> dict[str, str]:
        urls: dict[str, str] = {}
        for i in range(0, len(guids), _ASSET_BATCH):
            data = self._post("webasseturls", {"photoGuids": guids[i:i + _ASSET_BATCH]})
            for checksum, item in data.get("items", {}).items():
                urls[checksum] = f"https://{item['url_location']}{item['url_path']}"
        return urls

    def _make_fetch(self, checksums: dict[str, str], urls: dict[str, str]):
        def fetch(kind: str) -> bytes:
            url = urls.get(checksums["full" if kind == "full" else "thumb"])
            if not url:
                raise SourceError("Photo download link unavailable.")
            try:
                resp = self.session.get(url, timeout=TIMEOUT * 4)
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise SourceError(f"Photo download failed: {exc}") from exc
            return resp.content
        return fetch


def _pick_thumb(sized: list[tuple[int, str]]) -> str:
    """Smallest derivative that is still decent for a preview (>= ~300px wide area)."""
    for area, checksum in sized:
        if area >= 300 * 200:
            return checksum
    return sized[-1][1]
