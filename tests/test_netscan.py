import json

import requests

from app import ha, netscan

SSDP = (b"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nLOCATION: http://192.168.1.50:9197/dmr\r\n"
        b"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n")


class R:
    def __init__(self, status, js):
        self.status_code, self._js = status, js

    def json(self):
        if isinstance(self._js, Exception):
            raise self._js
        return self._js


def fake_get(table):
    def get(url, timeout=None):
        host = url.split("//")[1].split(":")[0]
        if host not in table:
            raise requests.ConnectTimeout()
        return table[host]
    return get


def test_parse_ssdp_and_subnet():
    assert netscan.parse_ssdp_response(SSDP) == "192.168.1.50"
    assert netscan.parse_ssdp_response(b"HTTP/1.1 200 OK\r\n\r\n") is None
    c = netscan.subnet_candidates("192.168.1.10")
    assert len(c) == 253 and "192.168.1.10" not in c and "192.168.1.254" in c
    assert netscan.subnet_candidates("127.0.0.1") == [] and netscan.subnet_candidates(None) == []


def test_probe_identifies_frame(monkeypatch):
    frame = {"name": "Living Room", "device": {"modelName": "QE55LS03B", "wifiMac": "AA:BB:CC:DD:EE:FF",
                                               "FrameTVSupport": "true", "PowerState": "standby"}}
    monkeypatch.setattr(requests, "get", fake_get({
        "10.0.0.2": R(200, frame), "10.0.0.3": R(404, {}), "10.0.0.4": R(200, ValueError()),
        "10.0.0.5": R(200, {"name": "Plain TV", "device": {"modelName": "UE50", "FrameTVSupport": "false"}})}))
    tv = netscan.probe("10.0.0.2")
    assert tv["frame"] and tv["mac"] == "aa:bb:cc:dd:ee:ff" and tv["model"] == "QE55LS03B"
    assert netscan.probe("10.0.0.3") is None and netscan.probe("10.0.0.4") is None
    assert netscan.probe("10.0.0.9") is None  # unreachable
    assert netscan.probe("10.0.0.5")["frame"] is False


def test_scan_combines_methods_and_orders_frames_first(monkeypatch):
    monkeypatch.setattr(netscan, "ssdp_hosts", lambda *a: {"10.0.0.2"})
    monkeypatch.setattr(netscan, "mdns_hosts", lambda *a: {"10.0.0.2", "10.0.0.5"})
    monkeypatch.setattr(netscan, "local_ip", lambda: "10.0.0.20")
    frame = {"name": "Frame", "device": {"modelName": "LS03", "FrameTVSupport": "true"}}
    plain = {"name": "Plain", "device": {"modelName": "UE", "FrameTVSupport": "false"}}
    monkeypatch.setattr(requests, "get", fake_get({"10.0.0.2": R(200, frame), "10.0.0.5": R(200, plain)}))
    tvs = netscan.scan()
    assert [t["host"] for t in tvs] == ["10.0.0.2", "10.0.0.5"]
    assert tvs[0]["found_by"] == ["mdns", "ssdp", "subnet"] and tvs[1]["found_by"] == ["mdns", "subnet"]


def test_ha_device_names_and_labels(tmp_path):
    s = tmp_path / ".storage"
    s.mkdir()
    (s / "core.device_registry").write_text(json.dumps({"data": {"devices": [
        {"name": "Frame TV", "name_by_user": "Lounge Frame", "model": "QE55LS03B",
         "identifiers": [["smartthings", "abc"]], "connections": [["mac", "AA:BB:CC:DD:EE:FF"]]},
        {"name": "Hue", "manufacturer": "Signify", "identifiers": [["hue", "x"]]}]}}))
    devs = ha.device_names(dirs=(tmp_path,))
    assert [d["name"] for d in devs] == ["Lounge Frame"]
    tvs = [{"mac": "aa:bb:cc:dd:ee:ff", "model": None}, {"mac": None, "model": "QE55LS03B"},
           {"mac": "11:22", "model": "OTHER"}]
    ha.label_scanned(tvs, devs)
    assert tvs[0]["ha_name"] == "Lounge Frame" and tvs[1]["ha_name"] == "Lounge Frame" and "ha_name" not in tvs[2]
    info = ha.discovery_info(dirs=(tmp_path,))
    assert info["ha_devices"][0]["name"] == "Lounge Frame"
