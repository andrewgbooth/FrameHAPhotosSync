"""Samsung Frame TV Art Mode client."""

from __future__ import annotations

import logging
import secrets
import socket
import time
from pathlib import Path
from typing import Any, Callable

from .sources import SourceError

log = logging.getLogger(__name__)

SETTLE_SECONDS = 2

FALLBACK_MATTES = ["none", "modernthin_black", "modernthin_neutral", "modern_black",
                   "shadowbox_black", "shadowbox_polar", "flexible_polar"]


REQUEST_TIMEOUT = 20    # seconds a single TV request may take
UPLOAD_TIMEOUT = 120    # seconds for one photo upload (the TV generates thumbnails afterwards)


def bounded_art_class():
    """SamsungTVArt with a hard deadline per request.

    The stock client waits for a reply in a loop and only gives up if the TV is silent for the
    whole socket timeout. A TV that ignores one request but keeps sending other events (some
    firmwares do for rotation/slideshow calls) would therefore hang the sync forever.
    """
    from samsungtvws import exceptions
    from samsungtvws.art import SamsungTVArt

    class BoundedArt(SamsungTVArt):
        request_timeout = REQUEST_TIMEOUT
        _deadline = None

        def _send_art_request(self, request_data, *args, **kwargs):
            self._deadline = time.monotonic() + self.request_timeout
            try:
                return super()._send_art_request(request_data, *args, **kwargs)
            finally:
                self._deadline = None

        def _recv_frame(self):
            if self._deadline is not None:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise exceptions.ConnectionFailure(
                        f"TV did not answer within {self.request_timeout:.0f}s")
                if hasattr(self.connection, "settimeout"):  # don't sit in recv() past the deadline
                    self.connection.settimeout(max(0.5, remaining))
            return super()._recv_frame()

        def upload(self, *args, **kwargs):
            old, self.request_timeout = self.request_timeout, UPLOAD_TIMEOUT
            try:
                return super().upload(*args, **kwargs)
            finally:
                self.request_timeout = old
                self._deadline = None

    return BoundedArt


def client_name(directory: Path) -> str:
    """Unique, stable name this add-on pairs with TVs under (generated once per install).

    The TV stores paired remotes by name and ties the saved token to it, so it must be
    unique across installs and must not change between runs.
    """
    f = directory / "client_name"
    try:
        name = f.read_text().strip()
        if name:
            return name
    except OSError:
        pass
    name = f"FrameHAPhotosSync-{secrets.token_hex(3)}"
    directory.mkdir(parents=True, exist_ok=True)
    f.write_text(name)
    return name


class FrameTV:
    def __init__(self, host: str, token_file: Path, port: int = 8002, timeout: int = 30) -> None:
        if not host:
            raise SourceError("No TV selected. Choose a TV or enter its IP address in settings.")
        self.host = host
        self.port = port
        self.token_file = token_file
        self.timeout = timeout
        self.name = client_name(token_file.parent)

    def _art(self):
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        return bounded_art_class()(
            host=self.host, port=self.port, token_file=str(self.token_file),
            timeout=self.timeout, name=self.name,
        )

    def reachable(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=5):
                return True
        except OSError:
            return False

    def _wrap(self, exc: Exception) -> SourceError:
        return SourceError(
            f"TV error ({type(exc).__name__}: {exc}). If this is the first connection, "
            "accept the pairing prompt on the TV, then try again."
        )

    def test(self) -> dict[str, Any]:
        if not self.reachable():
            raise SourceError(
                f"Can't reach {self.host}:{self.port}. The TV must be on or in Art Mode "
                "(not fully powered off) and on the same network."
            )
        try:
            art = self._art()
            supported = art.supported()
            if not supported:
                raise SourceError("This TV doesn't report Frame Art Mode support.")
            return {"ok": True, "api_version": art.get_api_version(),
                    "artmode": str(art.get_artmode()), "client_name": self.name}
        except SourceError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc

    def mattes(self) -> list[str]:
        try:
            data = self._art().get_matte_list()
        except Exception:
            return FALLBACK_MATTES
        types = [t.get("matte_type") for t in data.get("matte_types", []) if isinstance(t, dict)]
        colors = [c.get("color") for c in data.get("matte_colors", []) if isinstance(c, dict)]
        ids = ["none"] + [f"{t}_{c}" for t in types if t for c in colors if c]
        return ids if len(ids) > 1 else FALLBACK_MATTES

    def uploaded_ids(self) -> set[str]:
        try:
            return _ids(self._art())
        except Exception as exc:
            raise self._wrap(exc) from exc

    def upload_all(self, images: list[bytes], matte: str,
                   on_uploaded: Callable[[str], None] | None = None) -> list[str]:
        """Upload 3840x2160 JPEGs; returns the new content ids.

        ``on_uploaded`` is called with each id as soon as it exists so a failure part-way
        through doesn't lose track of what is already on the TV.
        """
        try:
            art = self._art()
            ids: list[str] = []
            for data in images:
                m = matte or "none"
                cid = art.upload(data, matte=m, portrait_matte=m, file_type="jpg")
                ids.append(cid)
                if on_uploaded:
                    on_uploaded(cid)
            return ids
        except SourceError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc

    def delete(self, content_ids: list[str]) -> tuple[list[str], list[str], str]:
        """Delete photos; returns (deleted, still_on_tv, error_text).

        Never raises. Success is judged by re-listing the TV, not by the delete reply
        (which differs between firmwares).
        """
        ids = list(dict.fromkeys(content_ids))
        if not ids:
            return [], [], ""
        errors: list[str] = []
        try:
            art = self._art()
            time.sleep(SETTLE_SECONDS)
            existing = _ids(art)  # one listing per check, not one per photo
            present = [i for i in ids if i in existing]
            if present:
                try:
                    art.delete_list(present)
                except Exception as exc:
                    errors.append(f"bulk delete: {type(exc).__name__}: {exc}")
                existing = _ids(art)
                present = [i for i in present if i in existing]
            for cid in list(present):  # one at a time for anything that survived
                try:
                    art.delete(cid)
                except Exception as exc:
                    errors.append(f"{cid}: {type(exc).__name__}: {exc}")
            if present:
                existing = _ids(art)
                present = [i for i in present if i in existing]
        except Exception as exc:
            return [], ids, f"{type(exc).__name__}: {exc}"
        return [i for i in ids if i not in present], present, "; ".join(errors[:3])

    def clear_my_photos(self) -> tuple[int, list[str], str]:
        """Delete every user-uploaded photo ("MY_F…") from the TV. Returns (deleted, left, error)."""
        try:
            mine = sorted(i for i in _ids(self._art()) if i.startswith("MY_F"))
        except Exception as exc:
            raise self._wrap(exc) from exc
        deleted, left, err = self.delete(mine)
        return len(deleted), left, err


def _ids(art) -> set[str]:
    return {i["content_id"] for i in art.available() if isinstance(i, dict) and "content_id" in i}
