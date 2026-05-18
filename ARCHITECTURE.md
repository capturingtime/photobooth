# Photobooth — Architecture Reference

Hardware target: **Raspberry Pi 4B** running Raspberry Pi OS (Buster/Bullseye).
Runtime: **Python 3.7+**, single asyncio process.

---

## Package Overview

```
photobooth/           ← installable Python package
  photobooth/
    __init__.py       ← public API; hardware deps guarded by try/except ImportError
    booth.py          ← Booth base class (web server, kiosk, CDP display helpers)
    rpi.py            ← RPi(Booth) — GPIO interrupt → asyncio event bridge
    camera.py         ← Camera — gphoto2 wrapper, async capture, per-camera startup config
    neopixel.py       ← Neopixel — ws281x panel animations (scroll, twinkle, rainbow…)
    printer.py        ← Printer — ESC/POS receipt printer (PBM-8350U)
    uploader.py       ← Uploader — S3 upload, presigned URL, randomised key paths
    strip.py          ← PhotoStrip — Pillow compositor; supports multi-column tiling
    template_loader.py← TemplateLoader ABC + LocalTemplateLoader
    resources/        ← static assets: kiosk.sh, strip_test_template PNG/JSON, fonts
  photobooth_web/     ← Django web app (kiosk browser target)
    mainscreen/       ← views: attract, last_capture, single_final, series_final,
                         series_capture
rpi_provisioning/
  booth_boot/
    resources/
      run_booth.py    ← asyncio entry point — all runtime logic lives here
```

---

## Component Map

```
PhotoBooth (run_booth.py)
│
├── RPi (rpi.py)                  ← extends Booth
│   ├── setup_gpio_events()       GPIO interrupt → call_soon_threadsafe → asyncio.Queue
│   ├── next_event()              await next GPIO event string from queue
│   ├── add_camera()              → Camera
│   ├── add_neopixel()            → Neopixel
│   └── add_printer()             → Printer
│
├── Camera (camera.py)
│   ├── __init__(model, startup_config=None)
│   │                             applies gphoto2 --set-config for each key in
│   │                             startup_config after base capturetarget config
│   ├── capture_async()           non-blocking gphoto2 capture via asyncio subprocess
│   └── copy_last_shot_to_dir()   cp last image to BOOTH_DIR archive
│
├── Uploader (uploader.py)
│   ├── upload(path)              → public S3 URL (key: booth/yyyy/mm/dd/<token>_name)
│   ├── make_key(path)            → S3 object key (same pattern as upload)
│   └── presign(key)              → time-limited presigned URL for QR code
│
├── PhotoStrip (strip.py)
│   ├── __init__(loader, name)    load template PNG + JSON sidecar once at startup
│   └── compose(shots, out)       center-crop shots into slots → overlay → optional
│                                 column tiling → JPEG at output path
│
└── LocalTemplateLoader (template_loader.py)
    └── load(name)                read <base>/<name>/template.{png,json}
```

---

## asyncio Architecture

The booth runs as a **single asyncio event loop** (`asyncio.run(PhotoBooth().run())`).

### GPIO → asyncio bridge

GPIO interrupts fire on a background thread (RPi.GPIO callback). Each interrupt calls
`loop.call_soon_threadsafe(queue.put_nowait, event_label)` to deliver a string event
into an `asyncio.Queue`. `await self.rpi.next_event()` drains the queue one event at a
time. GPIO bouncetime is 500 ms to suppress mechanical chatter.

### Event queue flushing

Every state transition that presents a new set of choices to the user calls
`await _flush_events()` after navigating to the new screen. This discards any button
presses queued during the previous state (countdown, animations, compositing). Flush
points: start of `_review_shot()`, start of `_series_capture_review()`, return to
`_series_capture_review()` after a re-review, and before the final-screen hold.

### Blocking I/O

| Operation | Mechanism |
|---|---|
| Pillow compositing (`PhotoStrip.compose`) | `loop.run_in_executor(None, fn, ...)` |
| Image compression (`_compress_image`) | `loop.run_in_executor(None, fn, ...)` |
| ESC/POS receipt printing (`_do_print`) | `loop.run_in_executor(None, fn, ...)` |
| gphoto2 capture (`capture_async`) | `asyncio.create_subprocess_exec` |

### Background tasks

- **Attract scroll** — runs as an `asyncio.Task`; cancelled on capture start, recreated
  when the booth returns to attract.
- **S3 upload** — runs as an `asyncio.Task` started immediately after the final screen
  is shown, so the user sees the result while the upload completes in parallel.

### Browser navigation (CDP)

`Booth.display_url(url)` navigates the kiosk Chromium instance via the Chrome DevTools
Protocol WebSocket at `localhost:9222` — no process respawn needed. Falls back to
spawning a new Chromium process if the debugging port is unavailable (first boot).
`kiosk.sh` starts Chromium with `--remote-debugging-port=9222`.

---

## Camera Startup Config

Each camera model can require specific gphoto2 settings at startup. These are defined
alongside `CAMERA_MODEL` in `run_booth.py` as a plain dict:

```python
CAMERA_MODEL = "Canon EOS 800D"
CAMERA_STARTUP_CONFIG = {
    "autoexposuremode": 3,  # Manual — prevents built-in flash from auto-firing
}
```

`Camera.__init__` applies each key via `gphoto2 --set-config key=value` after the base
`capturetarget` config. To support a different camera, update both constants; no other
code changes are required.

---

## Template System

### Screen overlays (`photobooth_web/mainscreen/static/img/`)

Full-screen PNG images displayed as overlays in the kiosk browser. Each HTML template
layers a `last.jpg` photo beneath the PNG using `position: absolute` / `object-fit:
contain`. The frame stays `visibility: hidden` until both images have loaded, preventing
a bare-photo flash. `Date.now()` cache-busting on `last.jpg` ensures each navigation
shows the latest capture.

| File | Screen |
|---|---|
| `attract_static.png` | Attract / idle |
| `last_capture.png` | Per-shot review overlay |
| `series_capture.png` | Between-shots instruction page (series mode) |
| `series_final.png` | Composited strip displayed before upload |
| `single_final.png` | Final single-shot overlay before upload |
| `nolast.jpg` | Fallback placeholder when no shot exists |

### Compositor templates (`/opt/photobooth/templates/`)

RGBA PNG + JSON sidecar pairs consumed by `PhotoStrip.compose()`. Stored outside the
repo so templates can be swapped without a code deploy.

```
/opt/photobooth/templates/
  strip_test_template/
    template.png    ← RGBA PNG; transparent slots reveal photos beneath
    template.json   ← sidecar — canvas, shot count, slot coordinates, columns
  strip_classic/
    template.png
    template.json
  …
```

### Sidecar JSON schema

```json
{
  "name": "Human-readable name",
  "shot_count": 3,
  "columns": 2,
  "canvas": { "width": 600, "height": 1800 },
  "slots": [
    { "x": 31, "y":  91, "width": 538, "height": 358 },
    { "x": 31, "y": 511, "width": 538, "height": 358 },
    { "x": 31, "y": 931, "width": 538, "height": 358 }
  ]
}
```

`shot_count` must equal `len(slots)`. `columns` defaults to 1; set to 2 for a 2×6 strip
that tiles side-by-side to fill a 4×6 print (e.g. 600×1800 canvas → 1200×1800 output
at 300 DPI).

### Compositor (`PhotoStrip.compose`)

1. Create a blank RGB canvas at canvas size.
2. For each slot: open the corresponding shot, `_center_crop` it to slot dimensions
   (scale-to-fill + center-crop — no letterboxing), paste at `(slot["x"], slot["y"])`.
3. Alpha-composite the RGBA template on top.
4. If `columns > 1`, tile the finished strip horizontally into a wider canvas.
5. Save as JPEG (quality 95) and return the path.

Template PNG is loaded once in `__init__` and reused across all `compose()` calls.

### Mode selection (`run_booth.py` constants)

| `ACTIVE_TEMPLATE` | `shot_count` | Mode |
|---|---|---|
| `None` | — | Single shot, plain photo uploaded |
| `"single_4x6"` | 1 | Single shot + final overlay composite |
| `"strip_test_template"` | > 1 | Series / photo-strip mode |

---

## Capture Flow

### Button roles by context

| Context | GPIO 23 green | GPIO 24 red | GPIO 25 blue |
|---|---|---|---|
| Attract / idle | Reprint last receipt | — | Start capture |
| Review (`last_capture`) | **Keep** → proceed | **Redo** → series_capture / attract | **Keep** → same as green |
| `series_capture` between-shots | **Show Last Shot** | **Start Over** → attract | **Continue** → next shot |
| Re-review from `series_capture` | **Keep** → series_capture | **Redo** → retake that slot | **Keep** → same as green |
| Final screen (60 s hold) | **Print receipt** | — → attract | **Print receipt** |

Blue and green are interchangeable wherever green means "keep" or "print". Red is always
the cancel / redo / start-over action. Constants `KEEP_BUTTON` and `REDO_BUTTON` in
`run_booth.py` map logical roles to GPIO labels so wiring can be remapped without
touching flow logic.

### Image compression

After every capture, `_compress_image` runs in the thread executor: the image is resized
to a maximum dimension of 2048 px on the longest side and recompressed at JPEG quality
85 (via Pillow `thumbnail` + `save(optimize=True)`). Typical output: ~300 KB vs 6–7 MB
raw. Compression runs before the review screen is shown.

### Single mode

```mermaid
flowchart TD
    ATTRACT(["Attract Mode"])
    ATTRACT -->|"blue btn"| COUNTDOWN

    COUNTDOWN["Countdown 3…2…1…Smile!\n+ NeoPixel twinkle\n+ reaction phrase scroll"]
    COUNTDOWN --> CAPTURE["Camera Capture\n+ compress in-place"]
    CAPTURE --> REVIEW

    REVIEW["Review\nlast_capture overlay\nphoto behind PNG frame"]
    REVIEW -->|"red btn — redo"| ATTRACT
    REVIEW -->|"blue / green btn — keep"| KEEP_GATE{Active\ntemplate?}

    KEEP_GATE -->|"None"| FINAL
    KEEP_GATE -->|"shot_count = 1"| COMPOSE["Compose single_final\n(run_in_executor)"]
    COMPOSE --> FINAL

    FINAL["single_final screen\n60 s hold"]
    FINAL -->|"blue / green — print"| PRINT["Upload S3 + Print receipt + QR"]
    FINAL -->|"red / timeout"| UPLOAD_ONLY["Upload S3 only"]
    PRINT --> ATTRACT
    UPLOAD_ONLY --> ATTRACT
```

### Series mode

```mermaid
flowchart TD
    ATTRACT(["Attract Mode"])
    ATTRACT -->|"blue btn"| COUNTDOWN

    COUNTDOWN["Countdown 3…2…1…Smile!\n+ NeoPixel twinkle\n+ reaction phrase scroll"]
    COUNTDOWN --> CAPTURE["Camera Capture\n+ compress in-place"]
    CAPTURE --> REVIEW

    REVIEW["Review\nlast_capture overlay"]
    REVIEW -->|"red btn — redo"| SERIES_PAGE
    REVIEW -->|"blue / green btn — keep"| APPEND["Append shot to list"]

    APPEND --> NEXT_OR_DONE{All shots\ncollected?}
    NEXT_OR_DONE -->|"Yes"| COMPOSE
    NEXT_OR_DONE -->|"No"| SERIES_PAGE

    SERIES_PAGE["series_capture page\n(between-shots instructions)\nflush queued presses"]
    SERIES_PAGE -->|"blue — continue"| COUNTDOWN
    SERIES_PAGE -->|"red — start over"| ATTRACT
    SERIES_PAGE -->|"green — show last shot"| RESHOW

    RESHOW["Re-review last kept shot\nlast_capture overlay\nflush queued presses"]
    RESHOW -->|"blue / green — keep"| SERIES_PAGE
    RESHOW -->|"red — redo that slot"| POP["Pop last shot from list"]
    POP --> COUNTDOWN

    COMPOSE["Compose strip\n(run_in_executor)\ncolumn-tile if columns > 1"]
    COMPOSE --> FINAL["series_final screen\n60 s hold"]
    FINAL -->|"blue / green — print"| PRINT["Upload S3 + Print receipt + QR"]
    FINAL -->|"red / timeout"| UPLOAD_ONLY["Upload S3 only"]
    PRINT --> ATTRACT
    UPLOAD_ONLY --> ATTRACT
```

---

## Button Wiring (GPIO)

| Button | GPIO | Pin | Event label |
|---|---|---|---|
| Shutter (blue) | 25 | 22 | `"capture"` |
| Green | 23 | 16 | `"green"` |
| Red | 24 | 18 | `"red"` |

Bouncetime: 500 ms. GPIO events fire on `RISING` edge and are delivered to the asyncio
queue via `call_soon_threadsafe`.

---

## Extending the Template Loader

`TemplateLoader` is an abstract base class. Implement `load(template_name) -> dict`
returning `{"template_path": str, "config": dict}`. `LocalTemplateLoader` is the
reference implementation. Possible alternatives:

- `USBTemplateLoader` — scan mounted USB drives for template folders
- `RemoteTemplateLoader` — fetch template assets from a URL

Pass the loader instance to `PhotoStrip(loader=..., template_name=...)`.

---

## Running Tests

### photobooth package (strip / template loader / compositor)

```bash
cd photobooth
env/bin/pytest tests/ -v
```

Uses `tmp_path` fixtures and symlinks to real template resources in `photobooth/resources/`.
No Pi hardware required; hardware deps (`RPi.GPIO`, `neopixel`, `board`) are guarded by
`try/except ImportError` in `__init__.py`.

### Django web app (views / URLs)

```bash
cd photobooth/photobooth_web
python3 manage.py test mainscreen
```

Tests in `mainscreen/tests.py` cover: HTTP 200, correct template rendered, expected
static image filename present. No database or Pi hardware required.
