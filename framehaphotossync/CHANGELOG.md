# Changelog

## 0.5.2
- Every request to the TV now has a hard deadline, so a TV that ignores a request can no longer hang a
  sync forever; each final step reports what it is doing and failures become warnings.

## 0.5.1
- Faster syncs: old-photo cleanup no longer re-lists the TV's art library once per photo,
  photos download and prepare two at a time, and the album isn't listed twice in a row.
- Live progress while syncing, and a timing breakdown in the activity log.

## 0.5.0
- Add icon and logo.
- Tidy documentation.

## 0.4.1
- Album preview always shows the photos currently on the TV first.
- Much faster thumbnails (smaller, decoded cheaply, generated in parallel, pre-made during sync).

## 0.4.0
- Old photos are removed reliably: deletion is verified against the TV, retried, and remembered.
- New *Rotate through My Photos* setting (with shuffle) so the TV actually uses the photos.
- *Delete all My Photos from the TV* tidy-up button.

## 0.3.0
- Every photo is prepared as an exact 3840×2160 sRGB baseline JPEG under 4 MB (fixes TV error 40000).
- Separate fit setting for portrait photos; smart crop keeps the detailed part of the photo.

## 0.2.1
- Pair with the TV under a unique, persistent client name.

## 0.2.0
- Network scan for Samsung TVs (SSDP, mDNS, subnet probe), labelled with SmartThings names.

## 0.1.x
- First release: public and private iCloud shared albums, Samsung Frame upload, schedule, web UI.
