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
