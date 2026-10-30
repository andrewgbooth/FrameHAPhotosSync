"""The sync engine: pick photos from the album, prepare them, push them to the TV."""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
PREPARE_WORKERS = 2  # photos downloaded/prepared at once (each needs ~100 MB while decoding)
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
        self._cache_lock = threading.RLock()
        self._thumb_locks: dict[str, threading.Lock] = {}
        self._warm_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="thumbs")
        self._photos: tuple[tuple, float, list[Photo]] | None = None
        self.next_run: datetime | None = None
        self._retries = 0
        self._wake = threading.Event()
        self.reschedule()

    # -- photos ------------------------------------------------------------
    def _source_key(self, s: dict[str, Any]) -> tuple:
        return (s["source_type"], s["public_url"], s["icloud_apple_id"], s["private_album_id"])

    def photos(self, refresh: bool = False, stale_ok: bool = False,
               max_age: float | None = None) -> list[Photo]:
        """The album, newest first. ``stale_ok`` accepts an expired cache (for thumbnails,
        which only need the download links and shouldn't re-list a big album); ``max_age``
        accepts a listing no older than that many seconds even when ``refresh`` is set."""
        s = self.settings.get()
        key = self._source_key(s)
        with self._cache_lock:
            c = self._photos
            if c and c[0] == key and max_age and time.time() - c[1] < max_age:
                return c[2]  # listed moments ago (e.g. by the preview): don't list again
            if c and not refresh and c[0] == key and (
                    stale_ok or time.time() - c[1] < PHOTO_CACHE_TTL):
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

    def _thumb_path(self, photo_id: str) -> Path:
        d = self.data_dir / "cache" / "thumbs"
        d.mkdir(parents=True, exist_ok=True)
        return d / (hashlib.sha256(photo_id.encode()).hexdigest()[:40] + ".jpg")

    def _thumb_lock(self, photo_id: str) -> threading.Lock:
        with self._cache_lock:
            return self._thumb_locks.setdefault(photo_id, threading.Lock())

    def thumb(self, photo_id: str) -> bytes:
        f = self._thumb_path(photo_id)
        if f.exists():
            return f.read_bytes()
        with self._thumb_lock(photo_id):  # concurrent requests for one photo share the work
            if f.exists():
                return f.read_bytes()
            photo = next((p for p in self.photos(stale_ok=True) if p.id == photo_id), None)
            if photo is None:
                raise SourceError("Photo not found.")
            data = imaging.thumbnail(photo.fetch("thumb"))
            f.write_bytes(data)
            return data

    def store_thumb(self, photo_id: str, full_image: bytes) -> None:
        """Make a preview from an image we already have (no extra network traffic)."""
        try:
            self._thumb_path(photo_id).write_bytes(imaging.thumbnail(full_image))
        except Exception:
            log.debug("Could not store thumbnail", exc_info=True)

    def warm_thumbs(self, photo_ids: list[str]) -> None:
        """Generate missing thumbnails in the background, several at a time."""
        def one(pid: str) -> None:
            try:
                self.thumb(pid)
            except Exception:
                log.debug("thumb warm-up failed for %s", pid, exc_info=True)

        todo = [i for i in photo_ids if not self._thumb_path(i).exists()]
        if todo:
            threading.Thread(target=lambda: list(self._warm_pool.map(one, todo)),
                             daemon=True).start()

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
        timings: dict[str, float] = {}
        t0 = time.monotonic()
        self.state.set(last_message="Reading the album…")
        photos = self.photos(refresh=True, max_age=60)
        timings["album"] = time.monotonic() - t0
        if not photos:
            raise SourceError("The album has no photos.")
        chosen = self.choose(photos, s)
        prev = self.state.snapshot().get("uploaded", [])
        if (not force and s["selection"] == "newest"
                and [u["photo_id"] for u in prev] == [p.id for p in chosen]):
            return "No new photos; the TV is already up to date."

        t0 = time.monotonic()
        total, done = len(chosen), [0]

        def prepare(p: Photo):
            try:
                image = imaging.prepare_for_tv(p.fetch("full"), s["image_fit"], s["portrait_fit"])
                self.store_thumb(p.id, image)  # preview of exactly what goes on the TV
                return p.id, image
            except Exception as exc:
                self.state.log(f"Skipped a photo: {exc}", "warning")
                return None
            finally:
                done[0] += 1
                self.state.set(last_message=f"Downloading and preparing photos… {done[0]}/{total}")

        with ThreadPoolExecutor(max_workers=PREPARE_WORKERS, thread_name_prefix="prepare") as pool:
            prepared = [r for r in pool.map(prepare, chosen) if r]  # keeps album order
        ids = [i for i, _ in prepared]
        images = [im for _, im in prepared]
        timings["download+prepare"] = time.monotonic() - t0
        if not images:
            raise SourceError("None of the selected photos could be downloaded.")

        self.state.log(f"Uploading {len(images)} photo(s) to {s['tv_name'] or s['tv_host']}…")
        snap = self.state.snapshot()
        prev_ids = [u["content_id"] for u in snap.get("uploaded", [])]
        pending = list(snap.get("pending_delete", []))
        fresh: list[str] = []

        def uploaded_one(cid: str) -> None:
            fresh.append(cid)
            self.state.set(last_message=f"Uploading to the TV… {len(fresh)}/{len(images)}")

        t0 = time.monotonic()
        self.state.set(last_message=f"Uploading to the TV… 0/{len(images)}")
        try:
            new = tv.upload_all(images, s["matte"], on_uploaded=uploaded_one)
        except Exception:
            # remember anything that did get onto the TV so it is cleaned up next time
            self.state.set(pending_delete=sorted(set(pending) | set(fresh)))
            raise
        timings["upload"] = time.monotonic() - t0
        uploaded = [{"photo_id": i, "content_id": c} for i, c in zip(ids, new)]
        replace = s["replace_previous"]
        # save progress straight away so a later failure can never lose track of anything
        self.state.set(
            uploaded=uploaded if replace else snap.get("uploaded", []) + uploaded,
            pending_delete=sorted(set(pending) | (set(prev_ids) if replace else set())),
        )

        removed_msg = ""
        if replace:
            doomed = self.state.snapshot().get("pending_delete", [])
            if doomed:
                self.state.set(last_message=f"Removing {len(doomed)} old photo(s)…")
                t0 = time.monotonic()
                note = tv.move_off(doomed, new[0])  # don't delete the picture on screen
                if note:
                    self.state.log(note[1], note[0])
                deleted, remaining, err = tv.delete(doomed)
                timings["cleanup"] = time.monotonic() - t0
                self.state.set(pending_delete=remaining)
                if deleted:
                    removed_msg = f", removed {len(deleted)} old"
                if remaining:
                    self.state.log(
                        f"Couldn't remove {len(remaining)} old photo(s) from the TV"
                        f"{' (' + err + ')' if err else ''}; will retry next sync.", "warning")
                    removed_msg += f", {len(remaining)} old photo(s) could not be removed"

        if s["select_first"] or s["enable_art_mode"] or s["slideshow_minutes"] > 0:
            t0 = time.monotonic()
            for level, note in tv.show(new[0] if new and s["select_first"] else None,
                                       s["slideshow_minutes"], s["slideshow_shuffle"],
                                       s["enable_art_mode"],
                                       on_step=lambda m: self.state.set(last_message=m)):
                self.state.log(note, level)
            timings["display"] = time.monotonic() - t0

        if s["use_my_photos"] and s["slideshow_minutes"] > 0:
            self.state.log("A rotation interval is set above, so it already uses My Photos; "
                           "skipped \"point the slideshow at My Photos\".")
        elif s["use_my_photos"]:
            self.state.set(last_message="Pointing the TV's slideshow at My Photos…")
            t0 = time.monotonic()
            level, note = tv.use_my_photos()
            self.state.log(note, level)
            timings["slideshow"] = time.monotonic() - t0

        self.state.log("Timing: " + ", ".join(f"{k} {v:.1f}s" for k, v in timings.items())
                       + f" (total {sum(timings.values()):.1f}s).")
        return f"Uploaded {len(new)} photo(s){removed_msg}."

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
