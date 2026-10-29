# Changelog

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
