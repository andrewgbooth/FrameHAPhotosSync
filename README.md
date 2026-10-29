# Frame Photos Sync (Home Assistant add-on)

Home Assistant add-on that syncs photos from an iCloud shared album (public link **or** private,
Apple ID–authenticated) to a Samsung Frame TV as Art Mode images, daily / weekly / monthly.

* Web UI (HA ingress): source, TV picker (from the HA Samsung integration), schedule, options,
  album preview with "On TV" markers, manual *Sync now*, activity log.
* "Photos of certain people": create a Smart Album on a Mac (*Person is …*) and add those photos to a
  shared album with an Apple Shortcut; this add-on then reads the shared album.

## Install

Home Assistant → Settings → Add-ons → Add-on Store → ⋮ → Repositories → add this repo's URL,
then install **Frame Photos Sync**. See [`framehaphotossync/DOCS.md`](framehaphotossync/DOCS.md).

## Development

```
python -m venv .venv && .venv/bin/pip install -r framehaphotossync/requirements.txt pytest
.venv/bin/python -m pytest tests
cd framehaphotossync && DATA_DIR=./data ALLOW_ANY_IP=1 python -m app.main   # UI on :8099
```
