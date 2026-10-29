"""Samsung Frame TV Art Mode client."""

from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Any

from .sources import SourceError

log = logging.getLogger(__name__)

FALLBACK_MATTES = ["none", "modernthin_black", "modernthin_neutral", "modern_black",
                   "shadowbox_black", "shadowbox_polar", "flexible_polar"]


class FrameTV:
    def __init__(self, host: str, token_file: Path, port: int = 8002, timeout: int = 30) -> None:
        if not host:
            raise SourceError("No TV selected. Choose a TV or enter its IP address in settings.")
        self.host = host
        self.port = port
        self.token_file = token_file
        self.timeout = timeout

    def _art(self):
        from samsungtvws import SamsungTVWS  # noqa: F401  (ensures package present)
        from samsungtvws.art import SamsungTVArt

        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        return SamsungTVArt(
            host=self.host, port=self.port, token_file=str(self.token_file),
            timeout=self.timeout, name="FrameHAPhotosSync",
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
                    "artmode": str(art.get_artmode())}
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
            return {i["content_id"] for i in self._art().available() if "content_id" in i}
        except Exception as exc:
            raise self._wrap(exc) from exc

    def apply(self, images: list[tuple[bytes, bool]], matte: str, delete_ids: list[str],
              select_first: bool, enable_art_mode: bool) -> list[str]:
        """Upload ``images`` (jpeg bytes, is_portrait); returns the new content ids."""
        try:
            art = self._art()
            new_ids: list[str] = []
            for data, portrait in images:
                m = matte or "none"
                new_ids.append(art.upload(data, matte=m, portrait_matte=m, file_type="jpg"))
            if delete_ids:
                existing = {i["content_id"] for i in art.available() if "content_id" in i}
                stale = [c for c in delete_ids if c in existing]
                if stale:
                    art.delete_list(stale)
            if select_first and new_ids:
                art.select_image(new_ids[0], show=True)
            if enable_art_mode:
                art.set_artmode(True)
            return new_ids
        except SourceError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc
