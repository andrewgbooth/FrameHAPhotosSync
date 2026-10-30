# Frame Photos Sync

Copies photos from an iCloud **shared album** to your Samsung Frame TV's Art Mode on a schedule.
Open **Frame Photos** in the Home Assistant sidebar to configure it.

## Photo source

**Public album link** – In the Photos app open the shared album → *People* → enable
*Public Website* → copy the link. No Apple ID needed. Anyone with the link can see the album.

**Private shared album** – Enter your Apple ID and password, press *Connect*, enter the 2FA
code Apple sends, then pick the album (albums you own *and* ones shared with you are listed).
The session is cached so a code is only needed occasionally; if Apple expires it, the sync log
will say so and you re-enter a code in the UI. Accounts with *Advanced Data Protection* may not
work. The password is stored in the add-on's private `/data` volume.

## Samsung Frame TV

TVs set up with the Home Assistant *Samsung Smart TV* integration appear in the drop-down
automatically. If your Frame is only in SmartThings (cloud-based, so HA never learns its IP), press
**Scan network**: the add-on looks for Samsung TVs via UPnP/DLNA (SSDP), mDNS (AirPlay) and a probe
of your local /24, confirms each one on the TV's own `:8001` API, marks Frames, and labels them with the
name SmartThings/HA uses. The add-on runs in host-network mode so these multicast scans work.
Otherwise enter the IP manually. On the first
connection accept the pairing prompt on the TV. The TV must be on or in Art Mode, not fully off.

## Options

| Option | Meaning |
|---|---|
| Schedule | Daily, weekly or monthly at a chosen time (Home Assistant's time zone). Failed runs retry hourly, up to 3 times. |
| Photos per sync | How many photos to upload each run. |
| Choose | *Newest first*, or *Random* (no repeats until the whole album has been shown). |
| Landscape / Portrait photos | *Fill screen (smart crop)* or *Fit with blurred edges*. Every photo is output at 16:9 whatever you choose. |
| Point the slideshow at My Photos | Optional, off by default. After each sync, tells the TV to use all of My Photos as its slideshow source, keeping the interval and shuffle you set on the TV. Skipped (and logged) if the TV won't report its slideshow settings or has no slideshow running. |
| Matte | The Frame's matte style; *Load from TV* lists what your TV supports. Kept here (unlike the settings below) because the TV applies a matte per picture, so one set on the TV would be lost when the add-on replaces the photos. |
| Remove previous | Deletes only photos this add-on uploaded earlier, never your other art. Anything the TV fails to delete is retried next sync. |

## One-time setup on the TV

The add-on only puts photos on the TV and removes the old ones. Everything the TV can do itself is left
to the TV, and it remembers it between syncs. On the Frame, open **Art Mode** and, in the art/photo
settings, choose **My Photos** as the source and pick a slideshow interval and shuffle if you want
rotation. The exact menu names differ between models and software versions.

Old photos are only removed after every new photo has been uploaded, so if the TV is off or a
sync fails part-way, your current photos stay in place.

The one exception to "the TV is in charge": if the TV is showing a *single* photo (no slideshow running)
and that photo is about to be removed, the add-on first moves the TV to the newest new photo, because
otherwise the TV falls back to other art. A running slideshow is never touched.

*Sync now* always re-uploads. Scheduled runs skip when the newest selection hasn't changed.

*Delete all My Photos from the TV* removes every photo in the TV's My Photos (not Samsung's art
collection), after confirmation.
