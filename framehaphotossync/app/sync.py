"""The sync engine: pick photos from the album, prepare them, push them to the TV."""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import imaging
from .frame import FrameTV
from .schedule import next_run
from .settings import DATA_DIR, SettingsStore
from .sources import Photo, SourceError
from .sources.private import PrivateICloud
from .sources.public import PublicAlbum
from .state import StateStore

log = logging.getLogger(__name__)

PHOTO_CACHE_TTL = 300
RETRY_DELAY = timedelta(hours=1)
MAX_RETRIES = 3


class Syncer:
    def __init__(self, settings: SettingsStore, state: StateStore, tz,
                 data_dir: Path = DATA_DIR,
                 frame_factory: Callable[..., FrameTV] = FrameTV) -> None:
        self.settings, self.state, self.tz = settings, state, tz
        self.data_dir = data_dir
        self.frame_factory = frame_factory
        self.private = PrivateICloud(data_dir / "icloud")
        self._run_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._photos: tuple[tuple, float, list[Photo]] | None = None
        self.next_run: datetime | None = None
        self._retries = 0
        self._wake = threading.Event()
        self.reschedule()

    # -- photos ------------------------------------------------------------
    def _source_key(self, s: dict[str, Any]) -> tuple:
        return (s["source_type"], s["public_url"], s["icloud_apple_id"], s["private_album_id"])

    def photos(self, refresh: bool = False) -> list[Photo]:
        s = self.settings.get()
        key = self._source_key(s)
        with self._cache_lock:
            c = self._photos
            if c and not refresh and c[0] == key and time.time() - c[1] < PHOTO_CACHE_TTL:
                return c[2]
            if s["source_type"] == "public":
                photos = PublicAlbum(s["public_url"]).photos()
            else:
                if not s["private_album_id"]:
                    raise SourceError("Choose a shared album in settings.")
                photos = self.private.photos(
                    s["icloud_apple_id"], s["icloud_password"], s["private_album_id"])
            self._photos = (key, time.time(), photos)
            return photos

    def thumb(self, photo_id: str) -> bytes:
        cache = self.data_dir / "cache" / "thumbs"
        cache.mkdir(parents=True, exist_ok=True)
        f = cache / (hashlib.sha256(photo_id.encode()).hexdigest()[:40] + ".jpg")
        if f.exists():
            return f.read_bytes()
        photo = next((p for p in self.photos() if p.id == photo_id), None)
        if photo is None:
            raise SourceError("Photo not found.")
        data = imaging.thumbnail(photo.fetch("thumb"))
        f.write_bytes(data)
        return data

    def invalidate(self) -> None:
        with self._cache_lock:
            self._photos = None

    # -- selection ---------------------------------------------------------
    def choose(self, photos: list[Photo], s: dict[str, Any]) -> list[Photo]:
        n = s["photo_count"]
        if s["selection"] == "newest":
            return photos[:n]
        shown = set(self.state.snapshot().get("shown_ids", []))
        pool = [p for p in photos if p.id not in shown]
        if len(pool) < min(n, len(photos)):  # everything has been shown: start over
            shown, pool = set(), list(photos)
        picked = random.sample(pool, min(n, len(pool)))
        self.state.set(shown_ids=sorted(shown | {p.id for p in picked}))
        return picked

    # -- running -----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._run_lock.locked()

    def start(self, trigger: str = "manual") -> bool:
        """Run a sync in the background. Returns False if one is already running."""
        if self._run_lock.locked():
            return False
        threading.Thread(target=self.run, args=(trigger,), daemon=True).start()
        return True

    def run(self, trigger: str = "manual") -> bool:
        if not self._run_lock.acquire(blocking=False):
            return False
        try:
            self.state.set(last_status="running", last_message=f"Sync started ({trigger}).")
            self.state.log(f"Sync started ({trigger}).")
            msg = self._sync(force=trigger == "manual")
            self.state.set(last_status="ok", last_message=msg,
                           last_run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            self.state.log(msg)
            self._retries = 0
            return True
        except SourceError as exc:
            self._fail(str(exc))
        except Exception as exc:  # never kill the scheduler thread
            log.exception("Sync crashed")
            self._fail(f"Unexpected error: {exc}")
        finally:
            self._run_lock.release()
            self.reschedule(failed=self.state.snapshot()["last_status"] == "error"
                            and trigger == "schedule")
        return False

    def _fail(self, message: str) -> None:
        self.state.set(last_status="error", last_message=message,
                       last_run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.state.log(message, "error")

    def _sync(self, force: bool) -> str:
        s = self.settings.get()
        tv = self.frame_factory(s["tv_host"], self.data_dir / "tv_token", s["tv_port"])
        photos = self.photos(refresh=True)
        if not photos:
            raise SourceError("The album has no photos.")
        chosen = self.choose(photos, s)
        prev = self.state.snapshot().get("uploaded", [])
        if (not force and s["selection"] == "newest"
                and [u["photo_id"] for u in prev] == [p.id for p in chosen]):
            return "No new photos; the TV is already up to date."

        images: list[tuple[bytes, bool]] = []
        ids: list[str] = []
        for p in chosen:
            try:
                images.append(imaging.prepare_for_tv(p.fetch("full"), s["image_fit"]))
                ids.append(p.id)
            except Exception as exc:
                self.state.log(f"Skipped a photo: {exc}", "warning")
        if not images:
            raise SourceError("None of the selected photos could be downloaded.")

        self.state.log(f"Uploading {len(images)} photo(s) to {s['tv_name'] or s['tv_host']}…")
        delete = [u["content_id"] for u in prev] if s["replace_previous"] else []
        new = tv.apply(images, s["matte"], delete, s["select_first"], s["enable_art_mode"])
        kept = [] if s["replace_previous"] else prev
        self.state.set(uploaded=kept + [{"photo_id": i, "content_id": c} for i, c in zip(ids, new)])
        return f"Uploaded {len(new)} photo(s)" + (f", removed {len(delete)} old." if delete else ".")

    # -- scheduling --------------------------------------------------------
    def reschedule(self, failed: bool = False) -> None:
        s = self.settings.get()
        now = datetime.now(self.tz)
        if failed and self._retries < MAX_RETRIES:
            self._retries += 1
            self.next_run = now + RETRY_DELAY
        elif s["schedule_enabled"]:
            self.next_run = next_run(s, now)
        else:
            self.next_run = None
        self._wake.set()

    def scheduler_loop(self, stop: threading.Event | None = None) -> None:
        while not (stop and stop.is_set()):
            self._wake.clear()
            if self.next_run and datetime.now(self.tz) >= self.next_run:
                self.run("schedule")
            self._wake.wait(20)
