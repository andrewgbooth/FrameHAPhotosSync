"""Flask app: settings UI + JSON API (served via Home Assistant ingress)."""

from __future__ import annotations

import ipaddress
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import ha
from .frame import FrameTV
from .settings import SettingsError
from .sources import SourceError
from .sources.public import PublicAlbum
from .sync import Syncer

STATIC = Path(__file__).parent / "static"
INGRESS_GATEWAY = "172.30.32.2"
PREVIEW_COUNT = 24


def create_app(syncer: Syncer, restrict_to_ingress: bool | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    if restrict_to_ingress is None:
        restrict_to_ingress = os.environ.get("ALLOW_ANY_IP") != "1"

    @app.before_request
    def only_ingress():
        if not restrict_to_ingress:
            return
        addr = request.remote_addr or ""
        if addr != INGRESS_GATEWAY and not ipaddress.ip_address(addr).is_loopback:
            abort(403)

    @app.errorhandler(SourceError)
    def source_error(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(SettingsError)
    def settings_error(exc):
        return jsonify(error=str(exc)), 400

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC, name)

    # -- settings ----------------------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        return jsonify(syncer.settings.public())

    @app.put("/api/settings")
    def put_settings():
        syncer.settings.update(request.get_json(force=True) or {})
        syncer.invalidate()
        syncer.reschedule()
        return jsonify(syncer.settings.public())

    # -- status ------------------------------------------------------------
    @app.get("/api/status")
    def status():
        st = syncer.state.snapshot()
        nxt = syncer.next_run
        return jsonify(
            running=syncer.running,
            last_run_at=st["last_run_at"],
            last_status=st["last_status"],
            last_message=st["last_message"],
            next_run=nxt.isoformat() if nxt else None,
            uploaded=[u["photo_id"] for u in st.get("uploaded", [])],
            log=st["log"][-30:],
            now=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    @app.post("/api/sync")
    def sync_now():
        if not syncer.start("manual"):
            return jsonify(error="A sync is already running."), 409
        return jsonify(started=True), 202

    # -- home assistant ----------------------------------------------------
    @app.get("/api/ha/tvs")
    def ha_tvs():
        return jsonify(ha.discover_tvs())

    # -- TV ----------------------------------------------------------------
    def _tv() -> FrameTV:
        s = syncer.settings.get()
        return syncer.frame_factory(s["tv_host"], syncer.data_dir / "tv_token", s["tv_port"])

    @app.post("/api/tv/test")
    def tv_test():
        return jsonify(_tv().test())

    @app.get("/api/tv/mattes")
    def tv_mattes():
        return jsonify(_tv().mattes())

    # -- iCloud ------------------------------------------------------------
    @app.post("/api/public/test")
    def public_test():
        body = request.get_json(force=True) or {}
        album = PublicAlbum(body.get("url") or syncer.settings.get()["public_url"])
        photos = album.photos()
        return jsonify(name=album.name, count=len(photos))

    @app.post("/api/icloud/login")
    def icloud_login():
        body = request.get_json(force=True) or {}
        s = syncer.settings.get()
        apple_id = body.get("apple_id") or s["icloud_apple_id"]
        password = body.get("password")
        if not password or password == "********":
            password = s["icloud_password"]
        return jsonify(syncer.private.login(apple_id, password))

    @app.post("/api/icloud/2fa")
    def icloud_2fa():
        body = request.get_json(force=True) or {}
        return jsonify(syncer.private.submit_2fa(body.get("code", "")))

    @app.get("/api/icloud/status")
    def icloud_status():
        return jsonify(syncer.private.status())

    @app.get("/api/icloud/albums")
    def icloud_albums():
        s = syncer.settings.get()
        return jsonify(syncer.private.list_albums(s["icloud_apple_id"], s["icloud_password"]))

    # -- preview -----------------------------------------------------------
    @app.get("/api/photos")
    def photos():
        refresh = request.args.get("refresh") == "1"
        items = syncer.photos(refresh=refresh)
        on_tv = {u["photo_id"] for u in syncer.state.snapshot().get("uploaded", [])}
        return jsonify(
            total=len(items),
            photos=[{"id": p.id, "taken": p.taken.isoformat() if p.taken else None,
                     "caption": p.caption, "on_tv": p.id in on_tv}
                    for p in items[:PREVIEW_COUNT]],
        )

    @app.get("/api/thumb")
    def thumb():
        data = syncer.thumb(request.args.get("id", ""))
        return Response(data, mimetype="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})

    return app
