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
        self.calls.append(("select", cid, show))

    def set_artmode(self, v):
        self.calls.append(("artmode", v))

    current = {"content_id": "MY_F1"}
    artmode = "on"
    rotation_status = {"value": "off"}

    def get_auto_rotation_status(self):
        if isinstance(self.rotation_status, Exception):
            raise self.rotation_status
        return self.rotation_status

    def get_slideshow_status(self):
        return self.rotation_status

    def get_current(self):
        return self.current

    def get_artmode(self):
        return self.artmode


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


class ChattyConnection:
    """A TV that never answers our request but keeps sending unrelated events."""
    def recv(self):
        import time; time.sleep(0.01)
        return '{"event": "ms.channel.clientConnect", "data": {}}'


def test_ignored_request_times_out_instead_of_hanging(tmp_path):
    import time
    from samsungtvws import exceptions
    art = frame.bounded_art_class()("10.0.0.2", token_file=str(tmp_path / "t"))
    art.request_timeout = 0.3
    art.connection = ChattyConnection()
    art.send_command = lambda *a, **k: None  # pretend the request was sent
    start = time.monotonic()
    with pytest.raises(exceptions.ConnectionFailure, match="did not answer"):
        art.get_artmode()
    assert time.monotonic() - start < 3




def test_move_off_switches_a_single_photo_that_is_about_to_be_deleted(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt([]))  # slideshow off, showing MY_F1
    note = tv.move_off(["MY_F1", "MY_F2"], "MY_F9")
    assert note[0] == "info" and ("select", "MY_F9", True) in art.calls

    art2 = use(tv, monkeypatch, FakeArt([]))
    art2.current = {"content_id": "ART_STORE_7"}  # stock art the user chose: leave alone
    assert tv.move_off(["MY_F1"], "MY_F9") is None and not any(c[0] == "select" for c in art2.calls)


def test_move_off_never_ends_a_running_slideshow(tv, monkeypatch):
    for running in ({"value": "15"}, {"value": "3"}, {"value": "1440", "category_id": "MY-C0002"}):
        art = use(tv, monkeypatch, FakeArt([]))
        art.rotation_status = running
        note = tv.move_off(["MY_F1"], "MY_F9")
        assert note[0] == "info" and "slideshow" in note[1]
        assert not any(c[0] == "select" for c in art.calls)  # selecting would stop the slideshow


def test_move_off_leaves_display_alone_when_slideshow_state_is_unknown(tv, monkeypatch):
    for unknown in (RuntimeError("TV did not answer within 8s"), {"unexpected": True}):
        art = use(tv, monkeypatch, FakeArt([]))
        art.rotation_status = unknown
        note = tv.move_off(["MY_F1"], "MY_F9")
        assert note[0] == "warning" and "left alone" in note[1]
        assert not any(c[0] == "select" for c in art.calls)


def test_move_off_does_not_flip_a_tv_being_watched_to_art_mode(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt([]))
    art.artmode = "off"
    tv.move_off(["MY_F1"], "MY_F9")
    assert ("select", "MY_F9", False) in art.calls


def test_move_off_never_raises_and_warns(tv, monkeypatch):
    class Art(FakeArt):
        def get_current(self):
            raise RuntimeError("TV did not answer within 20s")
    use(tv, monkeypatch, Art([]))
    level, msg = tv.move_off(["MY_F1"], "MY_F9")
    assert level == "warning" and "may fall back" in msg
    assert tv.move_off([], "MY_F9") is None and tv.move_off(["MY_F1"], "") is None


class RotArt(FakeArt):
    """A TV whose slideshow is on, pointed at the Samsung store."""
    rotation_status = {"value": "60", "category_id": "MY-C0004", "type": "shuffleslideshow"}

    def set_auto_rotation_status(self, **kw):
        self.calls.append(("auto", kw))


def test_use_my_photos_keeps_the_tvs_own_interval_and_shuffle(tv, monkeypatch):
    art = use(tv, monkeypatch, RotArt([]))
    level, msg = tv.use_my_photos()
    assert level == "info" and "every 60 min, shuffled" in msg
    assert art.calls == [("auto", {"duration": 60, "type": True, "category_id": "MY-C0002"})]

    ordered = use(tv, monkeypatch, RotArt([]))
    ordered.rotation_status = {"value": "3", "category_id": "MY-C0004", "type": "slideshow"}
    tv.use_my_photos()
    assert ordered.calls == [("auto", {"duration": 3, "type": False, "category_id": "MY-C0002"})]


def test_use_my_photos_skips_when_already_set_off_or_unknown(tv, monkeypatch):
    already = use(tv, monkeypatch, RotArt([]))
    already.rotation_status = {"value": "15", "category_id": "MY-C0002", "type": "slideshow"}
    assert "already using My Photos" in tv.use_my_photos()[1] and not already.calls

    off = use(tv, monkeypatch, RotArt([]))
    off.rotation_status = {"value": "off"}
    level, msg = tv.use_my_photos()
    assert level == "info" and "left alone" in msg and not off.calls  # never invents an interval

    for unknown in (RuntimeError("TV did not answer within 8s"), {"nothing": 1}):
        art = use(tv, monkeypatch, RotArt([]))
        art.rotation_status = unknown
        level, msg = tv.use_my_photos()
        assert level == "warning" and "Couldn't read" in msg and not art.calls


def test_use_my_photos_never_raises_and_restores_the_request_timeout(tv, monkeypatch):
    class Art(RotArt):
        request_timeout = 20

        def set_auto_rotation_status(self, **kw):
            raise RuntimeError("TV did not answer within 8s")
    art = use(tv, monkeypatch, Art([]))
    level, msg = tv.use_my_photos()
    assert level == "warning" and "Choose My Photos" in msg and art.request_timeout == 20


def test_use_my_photos_defaults_off():
    from app.settings import DEFAULTS
    assert DEFAULTS["use_my_photos"] is False


def test_show_orders_steps_so_rotation_survives_selecting_a_photo(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt([]))
    steps = []
    notes = tv.show("MY_F1", 15, True, True, on_step=steps.append)
    kinds = [c[0] for c in art.calls]
    assert kinds == ["select", "artmode", "auto"]  # rotation last: choosing a photo would end it
    assert ("auto", {"duration": 15, "type": True, "category_id": "MY-C0002"}) in art.calls
    assert steps == ["Showing the newest photo…", "Switching the TV to Art Mode…",
                     "Setting the TV's photo rotation…"]
    assert any("every 15 min" in m for _, m in notes)


def test_show_only_does_what_was_asked(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt([]))
    assert tv.show(None, 0, True, False) == [] and art.calls == []
    tv.show("MY_F2", 0, False, False)
    assert art.calls == [("select", "MY_F2", True)]


def test_show_falls_back_to_slideshow_api_for_older_tvs(tv, monkeypatch):
    art = use(tv, monkeypatch, FakeArt([], rotation="slideshow"))
    notes = tv.show(None, 60, False, False)
    assert art.calls[-1][0] == "slideshow" and any("every 1 h" in m for _, m in notes)


def test_show_survives_a_tv_that_ignores_the_rotation_request(tv, monkeypatch):
    class Art(FakeArt):
        request_timeout = 20

        def set_auto_rotation_status(self, **kw):
            self.calls.append(("auto", self.request_timeout))
            raise RuntimeError("TV did not answer within 8s")

        def set_slideshow_status(self, **kw):
            self.calls.append(("slideshow", None))
    art = use(tv, monkeypatch, Art([]))
    notes = tv.show("MY_F1", 15, True, True)
    assert ("select", "MY_F1", True) in art.calls and ("artmode", True) in art.calls  # still done
    assert ("auto", frame.ROTATION_TIMEOUT) in art.calls and not any(c[0] == "slideshow" for c in art.calls)
    assert art.request_timeout == 20
    assert any(l == "warning" and "rotation" in m and "Set it on the TV instead" in m for l, m in notes)


def test_show_never_raises_when_the_tv_is_unreachable(tv, monkeypatch):
    def boom():
        raise OSError("tv off")
    monkeypatch.setattr(tv, "_art", boom)
    notes = tv.show("MY_F1", 15, True, True)
    assert len(notes) == 1 and notes[0][0] == "warning"


def test_display_options_default_to_off():
    from app.settings import DEFAULTS
    assert (DEFAULTS["slideshow_minutes"], DEFAULTS["select_first"], DEFAULTS["enable_art_mode"]) == (0, False, False)
