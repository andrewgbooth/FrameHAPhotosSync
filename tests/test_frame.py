import pytest

from app import frame
from app.frame import FrameTV, client_name


def test_client_name_unique_per_install_and_stable(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    na = client_name(a)
    assert na.startswith("FrameHAPhotosSync-") and len(na) == len("FrameHAPhotosSync-") + 6
    assert client_name(a) == na
    assert client_name(b) != na
    assert FrameTV("10.0.0.2", a / "tv_token").name == na


class FakeArt:
    """Behaves like the TV: delete_list 'succeeds' but ignores the request, per-item works."""

    def __init__(self, ids, bulk_works=False, single_works=True, rotation="auto"):
        self.ids = set(ids)
        self.bulk_works, self.single_works, self.rotation = bulk_works, single_works, rotation
        self.calls = []
        self.listings = 0

    def available(self, category=None):
        self.listings += 1
        return [{"content_id": i} for i in sorted(self.ids)] + [{"content_id": "ART_STORE1"}]

    def delete_list(self, ids):
        self.calls.append(("bulk", list(ids)))
        if self.bulk_works:
            self.ids -= set(ids)
        return False  # the reply is unreliable; only the listing counts

    def delete(self, cid):
        self.calls.append(("one", cid))
        if self.single_works:
            self.ids.discard(cid)
        return True

    def set_auto_rotation_status(self, **kw):
        self.calls.append(("auto", kw))
        if self.rotation != "auto":
            raise RuntimeError("unsupported")

    def set_slideshow_status(self, **kw):
        self.calls.append(("slideshow", kw))

    def select_image(self, cid, show=True):
        self.calls.append(("select", cid))

    def set_artmode(self, v):
        self.calls.append(("artmode", v))


@pytest.fixture
def tv(tmp_path, monkeypatch):
    monkeypatch.setattr(frame, "SETTLE_SECONDS", 0)
    t = FrameTV("10.0.0.2", tmp_path / "tv_token")
    return t


def use(tv, monkeypatch, art):
    monkeypatch.setattr(tv, "_art", lambda: art)
    return art


def test_delete_verifies_by_listing_and_falls_back_to_one_by_one(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt(["MY_F1", "MY_F2"]))
    deleted, left, err = tv.delete(["MY_F1", "MY_F2", "MY_F9"])  # F9 is already gone
    assert sorted(deleted) == ["MY_F1", "MY_F2", "MY_F9"] and left == []
    assert [c[0] for c in art.calls] == ["bulk", "one", "one"]
    assert "ART_STORE1" in {i["content_id"] for i in art.available()}  # store art untouched


def test_delete_reports_survivors(tv, monkeypatch):
    use(tv, monkeypatch, FakeArt(["MY_F1"], single_works=False))
    deleted, left, _ = tv.delete(["MY_F1"])
    assert deleted == [] and left == ["MY_F1"]


def test_delete_never_raises(tv, monkeypatch):
    def boom():
        raise OSError("tv off")
    monkeypatch.setattr(tv, "_art", boom)
    assert tv.delete(["MY_F1"]) == ([], ["MY_F1"], "OSError: tv off")


def test_show_sets_rotation_selects_and_art_mode(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt([]))
    notes = tv.show("MY_F1", 15, True, True)
    assert ("auto", {"duration": 15, "type": True, "category_id": "MY-C0002"}) in art.calls
    assert ("select", "MY_F1") in art.calls and ("artmode", True) in art.calls
    assert any("every 15 min" in m for _, m in notes)


def test_show_falls_back_to_slideshow_api_for_older_tvs(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt([], rotation="slideshow"))
    notes = tv.show(None, 60, False, False)
    assert art.calls[-1][0] == "slideshow" and any("every 1 h" in m for _, m in notes)
    assert not any(c[0] in ("select", "artmode") for c in art.calls)


def test_clear_only_touches_my_photos(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt(["MY_F1", "MY_F2"], bulk_works=True))
    assert tv.clear_my_photos() == (2, [], "")
    assert {i["content_id"] for i in art.available()} == {"ART_STORE1"}


def test_delete_lists_the_tv_library_a_constant_number_of_times(tv, monkeypatch):
    ids = [f"MY_F{i}" for i in range(12)]
    art = use(tv, monkeypatch, FakeArt(ids))  # bulk delete ignored -> per-item fallback
    deleted, left, _ = tv.delete(ids)
    assert len(deleted) == 12 and left == []
    assert art.listings <= 3  # was ~one listing per photo per check
