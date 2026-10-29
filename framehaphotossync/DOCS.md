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
| Schedule | Daily, weekly or monthly at a chosen time (HA's time zone). Failed runs retry hourly up to 3 times. |
| Photos per sync | How many photos to upload each run. |
| Choose | *Newest first*, or *Random* (no repeats until the whole album has been shown). |
| Fit | Crop to fill 16:9, fit over a blurred background, or keep original shape (the matte frames it). Portrait photos are never cropped. |
| Matte | Frame matte; *Load from TV* lists what your TV supports. |
| Remove previous | Deletes only photos this add-on uploaded earlier, never your other art. |

*Sync now* always re-uploads. Scheduled runs skip when the newest selection hasn't changed.
