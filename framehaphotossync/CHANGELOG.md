# Changelog

## 0.7.0
- New optional setting: after each sync, point the TV's slideshow at all of My Photos. It keeps the
  interval and shuffle already set on the TV, and skips (with the reason in the log) if the TV won't
  report them or has no slideshow running. Off by default.

## 0.6.2
- Fix: the TV could end up stuck on one photo. Moving the TV off a photo that is about to be deleted
  also turns a running slideshow off, so it is now only done when the TV positively reports that no
  slideshow is running. A running (or unknown) slideshow is left alone.

## 0.6.1
- Before removing old photos, if the TV is displaying one of them it is switched to the newest new
  photo first, so the TV doesn't fall back to stock art. Anything else on screen is left alone.

## 0.6.0
- Removed the options the TV can manage itself: rotation, shuffle, showing the newest photo and
  switching to Art Mode. Set them once on the TV (Art Mode → My Photos); the TV remembers them.
  Matte stays, because the TV applies it per picture at upload.

## 0.5.3
- *Rotate through My Photos* is now off by default (set it once on the TV, or opt in here). Some TVs
  never answer the request; it now gives up after 8 seconds and doesn't try the fallback call.

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
