import io

import pytest
from PIL import Image

from app.sources import SourceError
from app.sources.public import PublicAlbum, base_url, parse_token


def test_parse_token_and_partition():
    assert parse_token("https://www.icloud.com/sharedalbum/#B0aGabcdefgh") == "B0aGabcdefgh"
    assert parse_token("B0aGabcdefgh") == "B0aGabcdefgh"
    with pytest.raises(SourceError):
        parse_token("")
    with pytest.raises(SourceError):
        parse_token("https://example.com/not-an-album!")
    # 'A' tokens: one base62 digit; otherwise two
    assert base_url("A5abcdefgh").startswith("https://p05-sharedstreams.icloud.com/")
    assert base_url("B0aGabcdefgh").startswith("https://p36-sharedstreams.icloud.com/B0aGabcdefgh/")


class Resp:
    def __init__(self, status=200, js=None, content=b""):
        self.status_code, self._js, self.content = status, js, content

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self):
        self.calls = []
        img = io.BytesIO()
        Image.new("RGB", (40, 30), "red").save(img, "JPEG")
        self.jpeg = img.getvalue()

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url))
        if "p00-" in url:  # first host redirects
            return Resp(330, {"X-Apple-MMe-Host": "p99-sharedstreams.icloud.com"})
        if url.endswith("webstream"):
            return Resp(200, {"streamName": "Holiday", "photos": [
                {"photoGuid": "old", "dateCreated": "2024-01-01T10:00:00Z",
                 "derivatives": {"1": {"checksum": "c-old-s", "width": "400", "height": "300"},
                                 "2": {"checksum": "c-old-l", "width": "4000", "height": "3000"}}},
                {"photoGuid": "new", "dateCreated": "2025-06-01T10:00:00Z",
                 "derivatives": {"1": {"checksum": "c-new-l", "width": "4000", "height": "3000"}}},
                {"photoGuid": "vid", "mediaAssetType": "video", "dateCreated": "2025-07-01T10:00:00Z",
                 "derivatives": {"PosterFrame": {"checksum": "c-vid", "width": "10", "height": "10"}}},
            ]})
        if url.endswith("webasseturls"):
            return Resp(200, {"items": {
                "c-old-s": {"url_location": "cdn.example", "url_path": "/old-s"},
                "c-old-l": {"url_location": "cdn.example", "url_path": "/old-l"},
                "c-new-l": {"url_location": "cdn.example", "url_path": "/new-l"}}})
        raise AssertionError(url)

    def get(self, url, timeout=None):
        self.calls.append(("GET", url))
        return Resp(200, content=self.jpeg + url.encode()[-1:])


def test_public_album_follows_redirect_orders_and_picks_largest():
    sess = FakeSession()
    album = PublicAlbum("A0abcdefgh", session=sess)  # partition 0 -> p00 -> redirect
    photos = album.photos()
    assert album.name == "Holiday"
    assert [p.id for p in photos] == ["new", "old"]  # newest first, video skipped
    assert photos[1].fetch("full").endswith(b"l")  # largest derivative
    assert photos[1].fetch("thumb")  # a smaller derivative exists for preview
    assert ("GET", "https://cdn.example/old-s") in sess.calls
    assert any("p99-sharedstreams" in u for _, u in sess.calls)


def test_public_album_not_found():
    class S(FakeSession):
        def post(self, url, json=None, timeout=None):
            return Resp(404, {})
    with pytest.raises(SourceError, match="not found"):
        PublicAlbum("B0abcdefgh", session=S()).photos()
