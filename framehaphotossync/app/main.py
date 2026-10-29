"""Add-on entry point."""

from __future__ import annotations

import logging
import threading

from waitress import serve

from . import ha
from .settings import SettingsStore
from .state import StateStore
from .sync import Syncer
from .web import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    syncer = Syncer(SettingsStore(), StateStore(), ha.timezone())
    threading.Thread(target=syncer.scheduler_loop, daemon=True, name="scheduler").start()
    serve(create_app(syncer), host="0.0.0.0", port=8099, threads=12)


if __name__ == "__main__":
    main()
