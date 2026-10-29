from app.frame import FrameTV, client_name


def test_client_name_unique_per_install_and_stable(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    na = client_name(a)
    assert na.startswith("FrameHAPhotosSync-") and len(na) == len("FrameHAPhotosSync-") + 6
    assert client_name(a) == na                       # stable across calls/restarts
    assert client_name(b) != na                       # unique per install
    assert FrameTV("10.0.0.2", a / "tv_token").name == na
