import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from app.settings import SettingsStore
from app.sources import Photo, SourceError
from app.state import StateStore
from app.sync import Syncer
from app.web import create_app


def jpeg():
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "green").save(b, "JPEG")
    return b.getvalue()


def make_photos(n):
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [Photo(id=f"p{i}", taken=base + timedelta(days=i), fetch=lambda kind: jpeg())
            for i in reversed(range(n))]  # sources return newest first


class FakeTV:
    instances = []
    fail_delete = False
    fail_upload_after = None
    counter = 0

    def __init__(self, host, token_file, port=8002):
        if not host:
            raise SourceError("No TV selected.")
        self.host = host
        self.uploaded, self.deleted = [], []
        FakeTV.instances.append(self)

    def upload_all(self, images, matte, on_uploaded=None):
        ids = []
        for n, _ in enumerate(images):
            if FakeTV.fail_upload_after is not None and n >= FakeTV.fail_upload_after:
                raise SourceError("TV dropped the connection")
            FakeTV.counter += 1
            cid = f"MY_F{FakeTV.counter:04d}"
            ids.append(cid)
            if on_uploaded:
                on_uploaded(cid)
        self.uploaded.append((len(images), matte))
        return ids

    def delete(self, ids):
        self.deleted.append(list(ids))
        if FakeTV.fail_delete:
            return [], list(ids), "bulk delete: ResponseError"
        return list(ids), [], ""

    def clear_my_photos(self):
        return 3, [], ""

    def test(self):
        return {"ok": True, "api_version": "4.3.4.0", "artmode": "on", "client_name": "X"}

    def mattes(self):
        return ["none", "shadowbox_polar"]


@pytest.fixture
def syncer(tmp_path, monkeypatch):
    FakeTV.instances.clear()
    FakeTV.fail_delete, FakeTV.fail_upload_after, FakeTV.counter = False, None, 0
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update({"tv_host": "10.0.0.5", "tv_name": "Frame", "photo_count": 3,
                     "public_url": "B0abcdefgh", "matte": "shadowbox_polar"})
    s = Syncer(settings, StateStore(tmp_path / "state.json"), ZoneInfo("UTC"),
               data_dir=tmp_path, frame_factory=FakeTV)
    s.album = make_photos(6)
    monkeypatch.setattr(Syncer, "photos", lambda self, refresh=False, stale_ok=False, max_age=None: self.album)
    return s


def test_sync_uploads_newest_then_skips_when_unchanged_then_replaces(syncer):
    assert syncer.run("manual")
    st = syncer.state.snapshot()
    assert st["last_status"] == "ok" and [u["photo_id"] for u in st["uploaded"]] == ["p5", "p4", "p3"]
    tv = FakeTV.instances[-1]
    assert tv.uploaded == [(3, "shadowbox_polar")] and tv.deleted == []
    first_ids = [u["content_id"] for u in st["uploaded"]]

    syncer.run("schedule")  # nothing changed
    assert "No new photos" in syncer.state.snapshot()["last_message"]
    assert FakeTV.instances[-1].uploaded == []

    syncer.album = make_photos(7)  # a new photo arrives
    syncer.run("schedule")
    tv = FakeTV.instances[-1]
    assert tv.deleted == [first_ids]  # old ones deleted after the new upload
    st = syncer.state.snapshot()
    assert [u["photo_id"] for u in st["uploaded"]] == ["p6", "p5", "p4"]
    assert st["pending_delete"] == [] and "removed 3 old" in st["last_message"]


def test_failed_delete_is_reported_and_retried_next_sync(syncer):
    syncer.run("manual")
    first = [u["content_id"] for u in syncer.state.snapshot()["uploaded"]]
    FakeTV.fail_delete = True
    syncer.album = make_photos(8)
    assert syncer.run("schedule")  # the sync itself still succeeds
    st = syncer.state.snapshot()
    assert st["pending_delete"] == sorted(first) and "could not be removed" in st["last_message"]
    assert any(l["level"] == "warning" and "retry" in l["msg"] for l in st["log"])
    assert [u["photo_id"] for u in st["uploaded"]] == ["p7", "p6", "p5"]  # new set is tracked

    FakeTV.fail_delete = False
    syncer.album = make_photos(9)
    syncer.run("schedule")
    st = syncer.state.snapshot()
    third_batch_prev = FakeTV.instances[-1].deleted[0]
    assert set(first) <= set(third_batch_prev) and len(third_batch_prev) == 6  # old backlog + previous set
    assert st["pending_delete"] == []


def test_partial_upload_failure_is_remembered_for_cleanup(syncer):
    FakeTV.fail_upload_after = 2
    assert syncer.run("manual") is False
    st = syncer.state.snapshot()
    assert st["last_status"] == "error" and st["pending_delete"] == ["MY_F0001", "MY_F0002"]
    FakeTV.fail_upload_after = None
    syncer.run("manual")
    assert FakeTV.instances[-1].deleted == [["MY_F0001", "MY_F0002"]]
    assert syncer.state.snapshot()["pending_delete"] == []


def test_random_selection_avoids_repeats_until_exhausted(syncer):
    syncer.settings.update({"selection": "random", "photo_count": 3})
    seen = []
    for _ in range(2):
        syncer.run("manual")
        seen += [u["photo_id"] for u in syncer.state.snapshot()["uploaded"]]
    assert len(set(seen)) == 6


def test_failure_is_reported_and_retry_scheduled(syncer):
    syncer.settings.update({"tv_host": ""})
    syncer.state.set(last_status=None)
    assert syncer.run("schedule") is False
    st = syncer.state.snapshot()
    assert st["last_status"] == "error" and "No TV" in st["last_message"]
    assert syncer.next_run - datetime.now(ZoneInfo("UTC")) < timedelta(hours=1, minutes=1)


def test_only_one_run_at_a_time(syncer):
    assert syncer._run_lock.acquire()
    assert syncer.run("manual") is False and syncer.start("manual") is False
    syncer._run_lock.release()


@pytest.fixture
def client(syncer, monkeypatch):
    monkeypatch.setattr("app.sync.Syncer.thumb", lambda self, pid: jpeg())
    return create_app(syncer, restrict_to_ingress=False).test_client()


def test_api_settings_masks_password_and_validates(client):
    r = client.put("/api/settings", json={"icloud_password": "pw", "frequency": "weekly"})
    assert r.status_code == 200 and r.json["icloud_password"] == "********" and r.json["frequency"] == "weekly"
    assert client.put("/api/settings", json={"frequency": "hourly"}).status_code == 400


def test_api_status_sync_photos_tv(client, syncer):
    assert client.post("/api/sync").status_code == 202
    for _ in range(100):
        if not syncer.running and syncer.state.snapshot()["last_status"] == "ok":
            break
        import time; time.sleep(0.05)
    st = client.get("/api/status").json
    assert st["last_status"] == "ok" and st["uploaded"] == ["p5", "p4", "p3"] and st["next_run"]
    photos = client.get("/api/photos").json
    assert photos["total"] == 6 and photos["photos"][0]["id"] == "p5" and photos["photos"][0]["on_tv"]
    assert client.get("/api/thumb?id=p5").mimetype == "image/jpeg"
    assert client.post("/api/tv/test").json["ok"]
    assert client.get("/api/tv/mattes").json == ["none", "shadowbox_polar"]
    assert client.post("/api/tv/clear", json={}).status_code == 400
    assert client.post("/api/tv/clear", json={"confirm": True}).json["deleted"] == 3
    assert client.get("/").status_code == 200 and client.get("/static/app.js").status_code == 200


def test_ingress_restriction(syncer):
    app = create_app(syncer, restrict_to_ingress=True)
    c = app.test_client()
    assert c.get("/api/status", environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403
    assert c.get("/api/status", environ_overrides={"REMOTE_ADDR": "172.30.32.2"}).status_code == 200


def test_preview_always_includes_photos_on_the_tv_first(syncer, client):
    syncer.album = make_photos(60)  # newest first: p59 ... p0
    syncer.settings.update({"selection": "random", "photo_count": 3})
    syncer.state.set(uploaded=[{"photo_id": "p2", "content_id": "A"}, {"photo_id": "p40", "content_id": "B"},
                               {"photo_id": "gone", "content_id": "C"}])
    r = client.get("/api/photos").json
    ids = [p["id"] for p in r["photos"]]
    assert ids[:2] == ["p40", "p2"] and all(p["on_tv"] for p in r["photos"][:2])  # old photo p2 still shown
    assert ids[2] == "p59" and len(ids) == 2 + 24 and not any(p["on_tv"] for p in r["photos"][2:])
    assert r["total"] == 60 and r["on_tv"] == 2 and r["missing_on_tv"] == 1


def test_sync_precaches_thumbnails_for_what_it_sent(syncer):
    syncer.run("manual")
    for pid in ("p5", "p4", "p3"):
        assert syncer._thumb_path(pid).exists()
    assert max(Image.open(syncer._thumb_path("p5")).size) <= 240
    assert not syncer._thumb_path("p0").exists()


def test_thumb_is_generated_once_for_concurrent_requests(syncer):
    import threading
    calls = []
    def slow_fetch(kind):
        calls.append(kind)
        import time; time.sleep(0.2)
        return jpeg()
    syncer.album = [Photo(id="x", taken=None, fetch=slow_fetch)]
    out = []
    ts = [threading.Thread(target=lambda: out.append(syncer.thumb("x"))) for _ in range(5)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(out) == 5 and calls == ["thumb"]


def test_sync_logs_timing_and_reports_progress(syncer):
    syncer.run("manual")
    st = syncer.state.snapshot()
    timing = [l["msg"] for l in st["log"] if l["msg"].startswith("Timing:")]
    assert timing and all(k in timing[0] for k in ("album", "download+prepare", "upload"))


def test_photos_prepared_in_album_order_even_when_one_fails(syncer):
    def boom(kind):
        raise SourceError("download failed")
    syncer.album[1] = Photo(id="p4", taken=None, fetch=boom)  # second-newest
    syncer.run("manual")
    st = syncer.state.snapshot()
    assert [u["photo_id"] for u in st["uploaded"]] == ["p5", "p3"]  # p4 skipped, order kept
    assert any("Skipped a photo" in l["msg"] for l in st["log"])
