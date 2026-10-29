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

    def __init__(self, host, token_file, port=8002):
        if not host:
            raise SourceError("No TV selected.")
        self.host = host
        self.applied = []
        FakeTV.instances.append(self)

    def apply(self, images, matte, delete_ids, select_first, enable_art_mode):
        self.applied.append((len(images), matte, list(delete_ids), select_first, enable_art_mode))
        n = sum(len(i.applied) for i in FakeTV.instances)
        return [f"MY_F{n}_{i}" for i in range(len(images))]

    def test(self):
        return {"ok": True, "api_version": "4.3.4.0", "artmode": "on"}

    def mattes(self):
        return ["none", "shadowbox_polar"]


@pytest.fixture
def syncer(tmp_path, monkeypatch):
    FakeTV.instances.clear()
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update({"tv_host": "10.0.0.5", "tv_name": "Frame", "photo_count": 3,
                     "public_url": "B0abcdefgh", "matte": "shadowbox_polar"})
    s = Syncer(settings, StateStore(tmp_path / "state.json"), ZoneInfo("UTC"),
               data_dir=tmp_path, frame_factory=FakeTV)
    s.album = make_photos(6)
    monkeypatch.setattr(Syncer, "photos", lambda self, refresh=False: self.album)
    return s


def test_sync_uploads_newest_then_skips_when_unchanged_then_replaces(syncer):
    assert syncer.run("manual")
    st = syncer.state.snapshot()
    assert st["last_status"] == "ok" and [u["photo_id"] for u in st["uploaded"]] == ["p5", "p4", "p3"]
    assert FakeTV.instances[-1].applied[0][:2] == (3, "shadowbox_polar")

    syncer.run("schedule")  # nothing changed
    assert "No new photos" in syncer.state.snapshot()["last_message"]
    assert len(FakeTV.instances[-1].applied) == 0  # new TV instance made, nothing applied

    syncer.album = make_photos(7)  # a new photo arrives
    syncer.run("schedule")
    tv = FakeTV.instances[-1]
    assert tv.applied[0][2] == [u["content_id"] for u in st["uploaded"]]  # old ones deleted
    assert [u["photo_id"] for u in syncer.state.snapshot()["uploaded"]] == ["p6", "p5", "p4"]


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
    assert client.get("/").status_code == 200 and client.get("/static/app.js").status_code == 200


def test_ingress_restriction(syncer):
    app = create_app(syncer, restrict_to_ingress=True)
    c = app.test_client()
    assert c.get("/api/status", environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403
    assert c.get("/api/status", environ_overrides={"REMOTE_ADDR": "172.30.32.2"}).status_code == 200
