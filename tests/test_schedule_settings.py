from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.schedule import next_run
from app.settings import DEFAULTS, SECRET_MASK, SettingsError, SettingsStore

TZ = ZoneInfo("Europe/London")


def s(**kw):
    return {**DEFAULTS, **kw}


def test_daily_later_today_and_tomorrow():
    now = datetime(2026, 10, 29, 1, 0, tzinfo=TZ)
    assert next_run(s(time="03:00"), now) == datetime(2026, 10, 29, 3, 0, tzinfo=TZ)
    now = datetime(2026, 10, 29, 3, 0, tzinfo=TZ)  # exactly now -> tomorrow
    assert next_run(s(time="03:00"), now) == datetime(2026, 10, 30, 3, 0, tzinfo=TZ)


def test_weekly():
    now = datetime(2026, 10, 29, 12, 0, tzinfo=TZ)  # Thursday
    assert next_run(s(frequency="weekly", weekday=0, time="08:00"), now) == datetime(2026, 11, 2, 8, 0, tzinfo=TZ)
    assert next_run(s(frequency="weekly", weekday=3, time="13:00"), now) == datetime(2026, 10, 29, 13, 0, tzinfo=TZ)
    assert next_run(s(frequency="weekly", weekday=3, time="11:00"), now) == datetime(2026, 11, 5, 11, 0, tzinfo=TZ)


def test_monthly_clamps_short_months_and_rolls_year():
    now = datetime(2026, 1, 31, 12, 0, tzinfo=TZ)
    assert next_run(s(frequency="monthly", day_of_month=31, time="09:00"), now) == datetime(2026, 2, 28, 9, 0, tzinfo=TZ)
    now = datetime(2026, 12, 15, 12, 0, tzinfo=TZ)
    assert next_run(s(frequency="monthly", day_of_month=1, time="09:00"), now) == datetime(2027, 1, 1, 9, 0, tzinfo=TZ)
    now = datetime(2026, 10, 29, 12, 0, tzinfo=TZ)
    assert next_run(s(frequency="monthly", day_of_month=29, time="18:00"), now) == datetime(2026, 10, 29, 18, 0, tzinfo=TZ)


def test_settings_roundtrip_mask_and_validation(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    store.update({"icloud_password": "hunter2", "photo_count": "5", "time": "7:05"})
    assert store.get()["icloud_password"] == "hunter2"
    assert store.get()["time"] == "07:05" and store.get()["photo_count"] == 5
    assert store.public()["icloud_password"] == SECRET_MASK
    store.update({"icloud_password": SECRET_MASK})  # masked value leaves it untouched
    assert store.get()["icloud_password"] == "hunter2"
    assert SettingsStore(tmp_path / "s.json").get()["photo_count"] == 5  # persisted
    assert oct((tmp_path / "s.json").stat().st_mode & 0o777) == "0o600"
    for bad in ({"frequency": "hourly"}, {"time": "25:00"}, {"photo_count": 0}, {"photo_count": "x"}):
        with pytest.raises(SettingsError):
            store.update(bad)


def test_removed_fit_mode_is_migrated(tmp_path):
    import json
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"image_fit": "none", "photo_count": 4}))
    s = SettingsStore(f).get()
    assert s["image_fit"] == "crop" and s["portrait_fit"] == "blur" and s["photo_count"] == 4


def test_display_settings_validate(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    store.update({"slideshow_minutes": "60", "select_first": "true"})
    assert store.get()["slideshow_minutes"] == 60 and store.get()["select_first"] is True
    with pytest.raises(SettingsError):
        store.update({"slideshow_minutes": 20000})
