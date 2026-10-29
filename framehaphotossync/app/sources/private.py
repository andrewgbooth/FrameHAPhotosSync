"""Private (authenticated) shared albums via pyicloud.

Holds a single :class:`PyiCloudService` so the web UI can drive the 2FA
handshake across several HTTP requests. Session cookies are persisted in the
add-on's data volume so 2FA is only needed occasionally.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from . import Photo, SourceError, newest_first

log = logging.getLogger(__name__)
MAX_PHOTOS = 2000


def _import_pyicloud():
    try:
        from pyicloud import PyiCloudService
        from pyicloud import exceptions as pex
    except ImportError as exc:  # pragma: no cover
        raise SourceError("pyicloud is not installed.") from exc
    return PyiCloudService, pex


class PrivateICloud:
    def __init__(self, cookie_dir: Path) -> None:
        self.cookie_dir = cookie_dir
        self._api: Any = None
        self._lock = threading.RLock()
        self._apple_id = ""

    # -- authentication ----------------------------------------------------
    def login(self, apple_id: str, password: str) -> dict[str, Any]:
        """Start (or resume) a session. Returns the auth status."""
        if not apple_id or not password:
            raise SourceError("Enter your Apple ID and password.")
        PyiCloudService, pex = _import_pyicloud()
        with self._lock:
            self.cookie_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._api = PyiCloudService(
                    apple_id, password, cookie_directory=str(self.cookie_dir), pause_2fa=False
                )
            except pex.PyiCloudFailedLoginException as exc:
                self._api = None
                raise SourceError(f"iCloud login failed: {exc}") from exc
            except pex.PyiCloudException as exc:
                self._api = None
                raise SourceError(f"iCloud error: {exc}") from exc
            self._apple_id = apple_id
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            api = self._api
            if api is None:
                return {"logged_in": False, "needs_2fa": False}
            needs = bool(getattr(api, "requires_2fa", False) or getattr(api, "requires_2sa", False))
            return {"logged_in": not needs, "needs_2fa": needs, "apple_id": self._apple_id}

    def submit_2fa(self, code: str) -> dict[str, Any]:
        with self._lock:
            if self._api is None:
                raise SourceError("Log in first.")
            code = code.strip().replace(" ", "")
            if not code:
                raise SourceError("Enter the verification code.")
            try:
                ok = self._api.validate_2fa_code(code)
            except Exception as exc:  # pyicloud raises several exception types
                raise SourceError(f"Verification failed: {exc}") from exc
            if not ok:
                raise SourceError("That code was not accepted.")
            try:
                self._api.trust_session()
            except Exception:  # trusting is best-effort
                log.warning("Could not trust session", exc_info=True)
            return self.status()

    def ensure(self, apple_id: str, password: str) -> Any:
        """Return an authenticated API object, re-logging in from cached cookies."""
        with self._lock:
            if self._api is None or self._apple_id != apple_id:
                self.login(apple_id, password)
            st = self.status()
            if st["needs_2fa"]:
                raise SourceError(
                    "iCloud needs a new verification code. Open the add-on and re-enter it."
                )
            return self._api

    # -- albums ------------------------------------------------------------
    def _streams(self, api: Any):
        try:
            return list(api.photos.shared_streams)
        except Exception as exc:
            raise SourceError(f"Could not list shared albums: {exc}") from exc

    def list_albums(self, apple_id: str, password: str) -> list[dict[str, Any]]:
        api = self.ensure(apple_id, password)
        return [
            {
                "id": a.id,
                "name": a.name,
                "owned": getattr(a, "sharing_type", "") == "owned",
                "public": bool(getattr(a, "is_public", False)),
            }
            for a in self._streams(api)
        ]

    def photos(self, apple_id: str, password: str, album_id: str) -> list[Photo]:
        api = self.ensure(apple_id, password)
        album = next((a for a in self._streams(api) if a.id == album_id), None)
        if album is None:
            raise SourceError("The selected shared album was not found. Re-select it in settings.")
        photos: list[Photo] = []
        try:
            for asset in album.photos:
                if getattr(asset, "item_type", "image") not in ("image", None):
                    continue
                photos.append(_wrap_asset(asset))
                if len(photos) >= MAX_PHOTOS:
                    break
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(f"Could not read album: {exc}") from exc
        return newest_first(photos)


def _wrap_asset(asset: Any) -> Photo:
    def fetch(kind: str) -> bytes:
        order = ("thumb", "medium", "original") if kind == "thumb" else ("original", "medium")
        for version in order:
            try:
                data = asset.download(version)
            except Exception:
                data = None
            if data:
                return data
        raise SourceError("Photo download failed.")

    taken = None
    try:
        taken = asset.asset_date
    except Exception:
        pass
    return Photo(id=str(asset.id), taken=taken, fetch=fetch, caption=getattr(asset, "filename", "") or "")
