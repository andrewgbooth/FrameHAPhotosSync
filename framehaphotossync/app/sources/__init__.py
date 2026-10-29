"""Photo sources: public and private iCloud shared albums."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable


class SourceError(Exception):
    """A user-presentable problem talking to iCloud."""


@dataclass
class Photo:
    id: str
    taken: datetime | None
    # fetch(kind) -> JPEG/HEIC/PNG bytes; kind is "thumb" or "full"
    fetch: Callable[[str], bytes]
    caption: str = ""


def newest_first(photos: list[Photo]) -> list[Photo]:
    epoch = datetime.fromtimestamp(0).astimezone()

    def key(p: Photo) -> datetime:
        t = p.taken or epoch
        return t if t.tzinfo else t.astimezone()

    return sorted(photos, key=key, reverse=True)
