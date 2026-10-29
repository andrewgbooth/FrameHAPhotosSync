"""Find Samsung Frame TVs on the local network.

Candidates come from SSDP/UPnP (DLNA), mDNS (AirPlay / Samsung MSF) and a probe of
the local /24. Every candidate is then confirmed against the TV's own REST endpoint
(``http://<ip>:8001/api/v2/``), which reports the model, MAC and whether it is a Frame.
"""

from __future__ import annotations

import logging
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

log = logging.getLogger(__name__)

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_TARGETS = (
    "urn:samsung.com:device:RemoteControlReceiver:1",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "upnp:rootdevice",
)
MDNS_TYPES = ("_airplay._tcp.local.", "_samsungmsf._tcp.local.", "_raop._tcp.local.")
PROBE_TIMEOUT = 1.5


def parse_ssdp_response(data: bytes) -> str | None:
    """Return the host in an SSDP response's LOCATION header."""
    m = re.search(rb"(?im)^location:\s*https?://([^:/\s]+)", data)
    return m.group(1).decode() if m else None


def ssdp_hosts(timeout: float = 3.0) -> set[str]:
    hosts: set[str] = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        for st in SSDP_TARGETS:
            msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
                   f'MAN: "ssdp:discover"\r\nMX: 2\r\nST: {st}\r\n\r\n').encode()
            sock.sendto(msg, SSDP_ADDR)
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            host = parse_ssdp_response(data)
            if host:
                hosts.add(host)
    except OSError as exc:
        log.info("SSDP scan unavailable: %s", exc)
    finally:
        sock.close()
    return hosts


def mdns_hosts(timeout: float = 3.0) -> set[str]:
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:  # pragma: no cover
        return set()
    hosts: set[str] = set()

    class Listener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=1500)
            if info:
                hosts.update(a for a in info.parsed_addresses() if "." in a)

        def update_service(self, *a): ...
        def remove_service(self, *a): ...

    try:
        zc = Zeroconf()
    except Exception as exc:
        log.info("mDNS scan unavailable: %s", exc)
        return hosts
    try:
        browsers = [ServiceBrowser(zc, t, Listener()) for t in MDNS_TYPES]
        time.sleep(timeout)
        for b in browsers:
            b.cancel()
    finally:
        zc.close()
    return hosts


def local_ip() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packets are sent
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def subnet_candidates(ip: str | None) -> list[str]:
    """Every other address in the /24 containing ``ip``."""
    if not ip or ip.startswith("127."):
        return []
    prefix = ip.rsplit(".", 1)[0]
    return [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != ip]


def probe(host: str, session: requests.Session | None = None) -> dict[str, Any] | None:
    """Return TV details if ``host`` answers like a Samsung smart TV, else None."""
    try:
        r = (session or requests).get(f"http://{host}:8001/api/v2/", timeout=PROBE_TIMEOUT)
        if r.status_code != 200:
            return None
        info = r.json()
        dev = info.get("device") or {}
    except (requests.RequestException, ValueError, AttributeError):
        return None
    if not dev and "Samsung" not in str(info.get("type", "")):
        return None
    return {
        "host": host,
        "name": info.get("name") or dev.get("name") or host,
        "model": dev.get("modelName") or info.get("model"),
        "mac": (dev.get("wifiMac") or "").lower() or None,
        "frame": str(dev.get("FrameTVSupport", "")).lower() == "true",
        "powered": dev.get("PowerState"),
    }


def scan(use_subnet: bool = True) -> list[dict[str, Any]]:
    """Run all discovery methods; return confirmed Samsung TVs (Frames first)."""
    found_by: dict[str, set[str]] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {"ssdp": pool.submit(ssdp_hosts), "mdns": pool.submit(mdns_hosts)}
        for method, fut in futures.items():
            try:
                for h in fut.result():
                    found_by.setdefault(h, set()).add(method)
            except Exception:
                log.exception("%s discovery failed", method)
    if use_subnet:
        for h in subnet_candidates(local_ip()):
            found_by.setdefault(h, set()).add("subnet")

    def check(host: str):
        return probe(host)

    tvs: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for host, result in zip(found_by, pool.map(check, list(found_by))):
            if result:
                result["found_by"] = sorted(found_by[host])
                tvs.append(result)
    return sorted(tvs, key=lambda t: (not t["frame"], t["name"]))
