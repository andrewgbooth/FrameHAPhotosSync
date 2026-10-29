import json

from app.ha import discover_tvs


def test_discover_tvs(tmp_path):
    p = tmp_path / "core.config_entries"
    p.write_text(json.dumps({"data": {"entries": [
        {"domain": "samsungtv", "title": "Living Room Frame", "data": {"host": "192.168.1.50", "mac": "AA", "model": "QE55LS03"}},
        {"domain": "samsungtv", "title": "No host", "data": {}},
        {"domain": "hue", "title": "Bridge", "data": {"host": "1.2.3.4"}},
    ]}}))
    tvs = discover_tvs(p)
    assert [t["host"] for t in tvs] == ["192.168.1.50"] and tvs[0]["name"] == "Living Room Frame"
    assert discover_tvs(tmp_path / "missing") == []


def test_discovery_reasons(tmp_path):
    from app.ha import discovery_info
    missing = discovery_info(dirs=(tmp_path / "nope",))
    assert missing["tvs"] == [] and "isn't visible" in missing["reason"]
    p = tmp_path / ".storage"
    p.mkdir()
    (p / "core.config_entries").write_text(json.dumps({"data": {"entries": [
        {"domain": "hue", "title": "Bridge", "data": {"host": "1.2.3.4"}}]}}))
    none = discovery_info(dirs=(tmp_path,))
    assert none["tvs"] == [] and "hue" in none["reason"]
    (p / "core.config_entries").write_text("not json")
    assert "Couldn't read" in discovery_info(dirs=(tmp_path,))["reason"]
