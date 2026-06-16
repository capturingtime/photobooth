# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [v0.5.0] — 2026-06-16

User-experience and reliability release. Trims countdown to a flat 2 s,
parallelises the post-capture review screen with the LED reaction phrase,
re-targets the photo into the redrawn `last_capture.png` aperture, and
introduces three new runtime subsystems: a poll-based `HealthMonitor` that
waits for hardware on startup and self-heals on runtime failures, an
"unavailable" mode that parks the booth on a friendly screen during a
camera/printer outage and resumes the in-flight capture once the
component returns, and a persistent on-disk upload queue so a wifi outage
no longer blocks the capture-and-print flow. Series mode now overlays a
"Shot X of N" banner on the kiosk screens driven by a URL-query bridge
between `booth_main` and Django.

No deployment-model changes from v0.4.1; upgrade is a single
`pip install --force-reinstall` plus a one-time `/var/lib/photobooth`
directory created by provisioning.

### Added

- **`photobooth/health.py`** — `HealthMonitor` registers async probes for
  each booth component (web, neopixel, camera, printer, net_local,
  net_www) and tracks a per-component `ComponentHealth` record
  (`name`, `state`, `last_error`, `last_checked`).
  `wait_until_ready(name, *, timeout, interval)` polls a probe until it
  returns ready (or times out), logging a single `Waiting for <name>`
  line on the first failure so the journal records which dependency the
  service is blocked on. `recheck_loop(interval)` runs as a background
  task and re-probes any component in the `unavailable` state, flipping
  it back to `ready` when it self-heals. Every transition is published
  to a `state_changes` `asyncio.Queue` for downstream consumers.
- **Per-component probes** — `probe_camera_available(model)`
  (`camera.py`), `probe_printer_available(model)` (`printer.py`),
  `probe_neopixel_available(control)` (`neopixel.py`),
  `probe_web_available`, `probe_local_network`, `probe_internet_available`
  (all `booth.py`). Each is an async callable returning `bool`, never
  raises (exceptions are logged + treated as `False`), and is invoked
  through the `HealthMonitor` registry.
- **`photobooth/state_store.py`** — atomic JSON file storage:
  `load_json(path)` returns `{}` on a missing file (rather than raising),
  `save_json_atomic(path, data)` writes via `<path>.tmp` + `fsync` +
  `os.replace` plus a directory-fsync so a crash mid-write never leaves
  a half-written file. `delete_if_exists(path)` removes a state file
  silently on clean session completion.
- **`photobooth/upload_queue.py`** — `UploadQueue(state_path)` is a
  JSON-backed FIFO queue at `/var/lib/photobooth/upload_queue.json`
  (override with `BOOTH_UPLOAD_QUEUE_PATH`). Public API:
  `enqueue(key, image_path)`, `peek()`, `pop(key)`, `list()`,
  `mark_attempt(key, error)`. Each operation opens, mutates, and closes
  the file through `state_store` — no long-held handles, no in-memory
  authoritative copy. The on-disk shape is `{"items": [QueueItem, ...]}`
  to leave room for future top-level metadata without a migration. Per-
  item `attempts` / `last_error` / `last_attempted_at` survive reboots.
- **`Neopixel.scroll_for_duration(text, duration_s, color=...)`** — wraps
  `scroll()` and derives per-frame `speed` from the rendered text width
  so callers can specify wall-clock duration directly. Phase 1's
  countdown depends on this to land each label at the target time
  regardless of label length.
- **`Uploader.upload_with_timeout(image_path, key, timeout_s)`** —
  `asyncio.wait_for` wrapper around the existing executor-based
  `upload()`. The foreground awaitable returns on timeout even though
  the underlying boto3 thread keeps running, so the capture flow never
  blocks the user for more than 5 s on a slow link.
- **`PhotoBooth.display_url_with_context(url, **params)`** — single
  navigation helper that appends `?mode=...&total=...&shot=...` to a
  kiosk URL. All `display_url` calls now route through here so the
  in-frame series banner has a single source of truth. The supporting
  `_series_params(shot=...)` builder reads the active template's
  `shot_count` and the optional caller-supplied `shot` index.
- **`PhotoBooth._enter_unavailable(component, scroll_text)`** — parks
  the kiosk on `UNAVAILABLE_URL`, starts a red continuous-scroll on the
  neopixel, awaits `HealthMonitor.wait_until_ready(component)` with no
  timeout, then drains stale button events before returning. Camera
  capture failures and printer failures route through here via
  `_classify_error(exc, hint=...)`.
- **`PhotoBooth._resume_from(state)` + `_save_resume_state` /
  `_clear_resume_state`** — series-mode cross-process resume. Before each
  capture, a `resume_context` (mode, pending_step, series_shots,
  shot_index, total, template_name) is persisted to
  `/var/lib/photobooth/resume.json` (override with
  `BOOTH_RESUME_STATE_PATH`). On the next process start, the booth
  navigates to the between-shots page with the right
  `?shot=X&total=N&mode=series` and the next blue-button event re-enters
  `_run_series` with the already-captured paths intact.
- **`PhotoBooth._upload_or_enqueue(image_path)`** — sequential upload
  with the 5 s wall-clock cap and "Uploading..." continuous scroll. On
  `asyncio.TimeoutError` or any other `Uploader.upload` exception, the
  capture is enqueued via `UploadQueue.enqueue(key, image_path)` and a
  `pending_notice` is returned to the receipt-print path so the printed
  receipt explicitly tells the user their QR will work once the booth
  reconnects.
- **`PhotoBooth._upload_queue_worker()`** — background task started in
  `_startup`. Peeks the queue head, waits for `HealthMonitor` to report
  `net_www` ready, attempts `Uploader.upload`, pops on success, calls
  `mark_attempt` + flips `net_www` to `unavailable` on failure with
  exponential backoff (`UPLOAD_WORKER_BACKOFF_INITIAL=5s` doubling to
  `UPLOAD_WORKER_BACKOFF_CAP=300s`). A successful drain resets backoff
  so the next outage starts fresh from the short interval. Cancellable
  via `asyncio.CancelledError`.
- **`PhotoBooth._print_with_recovery(url, pending_notice)`** — wraps the
  thread-executor receipt print in try/except + `_enter_unavailable` so
  a printer fault drops the booth into unavailable mode, awaits printer
  recovery, then retries the print once.
- **Phase 4 startup-timeout constants in `booth_main.py`** —
  `HEALTH_TIMEOUT_WEB=30s`, `_NEOPIXEL=_CAMERA=_PRINTER=300s`,
  `_NET_LOCAL=_NET_WWW=5s`, `HEALTH_RECHECK_INTERVAL=10s`. Required
  components (web, neopixel, camera, receipt printer) raise on miss so
  systemd restarts the service; optional components (LAN, WWW) log +
  continue in degraded mode.
- **`photobooth_web/mainscreen/templates/unavailable.html`** + view + URL
  pattern + `static/img/unavailable.png` — full-screen image displayed
  when `_enter_unavailable` parks the kiosk during a hardware fault.
- **Series banner overlay** — shared
  `photobooth_web/mainscreen/static/css/series-banner.css` defines a
  `.series-banner` flex box driven by `--series-banner-*` CSS variables
  (max area `y∈[945,1075]`, `x∈[250,1675]`, MIN 10 px vertical padding,
  configurable font size / colour / shadow). The three affected
  templates (`attract.html`, `last_capture.html`, `series_capture.html`)
  link the stylesheet and render the banner conditionally on
  `{% if mode == "series" %}`. `attract.html` shows "N photos will be
  taken for the series", `series_capture.html` shows "Next shot: X of N",
  `last_capture.html` shows "Shot X of N".
- **`_series_context(request)` view helper** — pulls `mode`, `total`,
  `shot` off the request query string with int-coercion, used by
  `attract`, `last_capture`, and `series_capture` views.
- **8 new test files** (`test_neopixel_scroll_duration.py`,
  `test_capture_timing.py`, `test_parallel_display.py`,
  `test_health_monitor.py`, `test_startup_dependency_wait.py`,
  `test_state_store.py`, `test_unavailable_mode.py`,
  `test_resume_mid_series.py`, `test_upload_queue.py`,
  `test_upload_offline_flow.py`, `test_upload_queue_worker.py`,
  `test_series_overlay_views.py`, `test_display_url_with_context.py`)
  plus `mainscreen/tests.py` coverage of the photo-aperture HTML.

### Changed

- **Countdown timing (Phase 1).** `_take_one_shot()` no longer issues four
  fixed-speed `scroll` calls. `3.../2.../1...` each scroll for 0.4 s via
  `scroll_for_duration`, totalling 1.2 s. Capture is then dispatched
  (`asyncio.create_task(camera.capture_async())`) and `Smile! :D` scrolls
  for 0.8 s in parallel with the shutter. If gphoto2 takes longer than
  the Smile! scroll, `twinkle(count=30)` fills the gap until the capture
  task resolves. Total button-press → shutter is now ≈ 2.0 s (down from
  ~4 s).
- **Parallel review-screen navigation (Phase 2).** The post-capture
  reaction phrase is now launched as a background task
  (`self._phrase_task = asyncio.create_task(...)`) before the kiosk
  navigates to `REVIEW_URL`, so the photo appears on the main screen
  while the phrase is still scrolling. `_review_shot` cancels and awaits
  the phrase task before yielding control back to the main loop, so the
  panel is idle by the next state transition.
- **Photo aperture geometry (Phase 3).** `last_capture.html` and
  `single_final.html` now position the photo at
  `top:135px; left:352px; width:1215px; height:810px; object-fit:cover`
  to fill the redrawn 1215×810 aperture in the 1920×1080 overlay PNG.
  The browser does the framing; `_compress_image` does not letterbox.
- **`PhotoBooth._startup` rebuilt around `HealthMonitor` (Phase 4).** Each
  component goes through `register(name, probe)` →
  `wait_until_ready(name, timeout=...)` → factory init. Required misses
  raise so systemd restarts the service; optional misses log + continue.
  `recheck_loop(interval=HEALTH_RECHECK_INTERVAL)` and
  `_upload_queue_worker` are launched as background tasks at the end of
  `_startup`. A new `_init_with_retry(name, factory)` handles the rare
  case where init still raises between probe-pass and constructor call.
- **All kiosk navigations route through `display_url_with_context`
  (Phase 7).** The previous `self.rpi.display_url(URL)` calls are gone;
  the helper appends the query string built from `_series_params(shot=...)`
  so series-mode banners populate without any shared in-memory state.
- **`pyproject.toml`** — `version` bumped to `0.5.0`; `ctp-utilities` pin
  updated from `@v0.4.1` to `@v0.5.0`.

### Fixed

- **Cold-boot races on hardware that's slow to appear.** Pre-Phase-4
  startup raised on the first failed probe of camera / printer /
  neopixel; the unit would crash-loop until everything happened to be
  present at exactly the right millisecond. Each probe is now polled at
  1 s for up to 5 min, with a single "Waiting for ..." log line so the
  journal records what the service is waiting on.
- **Mid-capture hardware failure no longer kills the booth.** A
  camera-USB unplug mid-series used to raise out of
  `Camera.capture_async` and propagate to the asyncio top level. The
  Phase 5 catch-and-recover wraps capture in try/except, parks the
  kiosk on `unavailable.png`, scrolls the diagnosis text on the panel,
  and resumes at the failed step once the camera returns.
- **wifi outage no longer blocks the capture/print flow.** Pre-Phase-6
  the booth held the user on the final screen while `boto3` retried in
  the foreground. The new 5 s timeout + offline queue means the receipt
  prints with a working QR (the S3 key is deterministic client-side, so
  the queued upload eventually lands at the URL the QR already encoded)
  and a "* Photo upload pending" notice under the QR explains why.

### Upgrade

```sh
sudo pip3 install --upgrade --force-reinstall --no-deps \
    "git+https://github.com/capturingtime/photobooth.git@v0.5.0"
sudo systemctl restart booth.service
```

Provisioning prerequisite (one-time, per booth Pi):

```sh
sudo install -d -o pi -g pi /var/lib/photobooth
```

`rpi_provisioning/booth_boot/init_setup.sh` creates the directory at
provision time, so a freshly imaged Pi gets it automatically. Existing
booths need the one-liner above before the first v0.5.0 start; missing
the directory makes `state_store.save_json_atomic` raise on the first
`resume.json` or `upload_queue.json` write.

## [v0.4.1] — 2026-05-27

Investigation-and-resilience release: diagnosed the long-standing
"spurious capture" bug (EMI-induced falling edges on the idle-LOW GPIO
signal line, compounded by camera-asleep returning success-with-no-file),
validated the hardware fix on the live booth, hardened the series-capture
flow's between-shots state machine, and added meaningful unit-test
coverage to ~60% of the runtime. No deployment-model changes from v0.4.0;
upgrade is a single `pip install --force-reinstall`.

### Added
- **Diagnostic logging** across the GPIO → main-loop → gphoto2 chain.
  Enable the high-frequency lines by setting `BOOTH_LOG_LEVEL=DEBUG` in
  `/etc/ctp/booth.env`:
  - `rpi._on_press`: `Button event: label=X pin=N queue_depth_before=Q` (DEBUG).
    Queue depth > 0 on consecutive presses signals bounce or EMI.
  - `booth_main.run`: `Main loop event: X` (DEBUG). Pair with the ISR line
    by timestamp to measure GPIO → dispatch latency.
  - `camera.capture_async`: file size + EXIF `DateTimeOriginal` alongside
    the existing model/file/elapsed line (INFO, always on). `size <= 0`
    indicates gphoto2 returned success without a file.
- **`PhotoStrip.expand_for_print(input_path, output_path)`** — column
  duplication for physical print, called separately from `compose()`. The
  digital path (S3 upload + kiosk display) gets the single-strip form
  from `compose()`; the print path calls `expand_for_print()` when a
  physical-print integration ships.
- **"Press the big blue button to continue!  " scroll** on the series_capture
  page. Continuous loop (count=999) while waiting, cancelled on transition.
- **Show-last undo** in the series flow: GREEN on the series_capture page
  now re-reviews the just-decided shot (was: only the last-kept shot, which
  was a dead button when the just-redone shot was shot 1). The re-review's
  decision can flip the original (keep ↔ redo), mutating `shots` in place.
- **`BACKLOG.md` follow-up entries**: apply rewire to red/green buttons,
  release-bounce mitigation, file-size guard in `Camera.capture_async`.
- **9 new test files** (65 new tests; suite grew from 31 → 96):
  - `test_uploader.py` — `make_key` token uniqueness (reprint-bug regression),
    `public_url` shape, `upload()` returns public URL not presigned.
  - `test_logging_no_credentials.py` — scans every log record for `AKIA` /
    `X-Amz-Signature` / `Signature=` / etc. across upload + presign paths.
    Hard-blocks the v0.4.0/F credential-leak class of regression.
  - `test_logging_config.py` — `setup_logging` idempotency, env handling,
    unwritable-file fallback.
  - `test_booth_main_env.py` — defaults + overrides for all 6 `BOOTH_*`
    constants in `booth_main`.
  - `test_env_example_consistency.py` — cross-repo check that every key in
    `rpi_provisioning/booth_boot/resources/booth.env.example` is consumed by
    `booth_main` / `logging_config`, and vice versa.
  - `test_camera.py` — `run_local_cmd`, `_build_filename`, `check_gphoto2`,
    `check_dir_rw_or_make`, plus the new `_read_exif_datetime` helper.
  - `test_printer.py` — `PRINTER_MAP` resolution + escpos passthroughs.
  - `test_series_flow.py` — all six scenarios of `_series_capture_review`
    (continue, start_over, undo-redo, undo-keep, re-affirm-keep,
    re-affirm-redo). Pins the buffer-after-re-review contract that today's
    `keep → show-last → redo` bug fix introduces.

### Changed
- **`PhotoStrip.compose()` produces single-strip output only** (one template
  application). The column-duplication step it used to do is now in the
  new `expand_for_print()` method. Customers download the single strip
  from S3; physical print gets the duplicated form when that path is wired.
- **`series_final.html` template**: composite renders on top of the
  background image (was: behind a transparency window in the template).
  Background uses `object-fit: cover` so the viewport fills regardless
  of composite size. `series_final.png` regenerated as a full-coverage
  background.
- **`_series_capture_review` rewritten** as a single function that owns
  the between-shots page loop. GREEN re-reviews `last_decided` (the shot
  whose decision brought us here), and after any re-review the function
  loops back to re-display the series_capture page — this is the buffer
  that fixes the `keep → show-last → redo` bug (used to skip the buffer
  and start countdown immediately). The function now mutates `shots` in
  place; `_run_series` was simplified accordingly (no more `redo_last`
  return handling).
- **`pyproject.toml`**: `ctp-utilities` pin updated from `@v0.4.0` to `@v0.4.1`.
- **`ARCHITECTURE.md`**: fixed pre-existing `RISING` → `FALLING` typo in
  Button Wiring; added "Electrical expectations" subsection (cross-linked
  to the new `rpi_provisioning/HARDWARE.md`). Compositor section and
  Running Tests section updated for the new shape.
- **`BACKLOG.md`**: restructured the original "Camera sleep triggers a
  spurious capture" entry into the actual post-mortem ("Spurious capture
  — EMI on GPIO signal line") with the validated hardware fix.

### Fixed
- **Series flow: `keep → show-last → redo` no longer skips the countdown
  buffer.** After any re-review on the show-last page, the user is brought
  back to the series_capture page and must press BLUE to start the next
  countdown (matching the buffer that the normal redo flow has always had).
- **Series flow: `show-last` on a redone first shot was a dead button.**
  When `shots` was empty (because shot 1 was redone), the GREEN branch
  did `if not shots: continue` — silently no-op. Now reviews the
  just-decided shot via the all-cases `last_decided` parameter; accepting
  it undoes the redo and appends to `shots`.
- **Hardware: spurious-capture root cause.** Active-low rewire of the
  capture-button signal line on the live booth (10 kΩ pull-up + 1 kΩ
  series protection + 100 nF low-pass, cat5e pair carries signal +
  signal-GND on a separate pair from the 12V LED supply). Validated
  2026-05-25 with 3.5 h idle: zero phantom triggers. Topology
  documented in `rpi_provisioning/HARDWARE.md`. Red and green buttons
  remain on the defective v0.2.0 wiring as the control group + migration
  backlog.
- **`tests/test_strip.py::test_compose_output_dimensions`** asserted the
  wrong dimensions (1200×1800 vs the actual 600×1800 single-strip output).
  Now matches the new `compose()` contract.

### Documentation
- `rpi_provisioning/HARDWARE.md` (new file in that repo) — wiring topology,
  cat5e pair assignment, per-button validation status, ATX dummy-load
  in-progress notes.
- `BACKLOG.md` table mapping each diagnostic-log field to which hypothesis
  it supports/rejects, for future GPIO triage.

### Upgrade

```sh
sudo pip3 install --upgrade --force-reinstall --no-deps \
    "git+https://github.com/capturingtime/photobooth.git@v0.4.1"
sudo systemctl restart booth.service
```

`--no-deps` is safe because `ctp-utilities` v0.4.1 has no runtime behavior
change (CHANGELOG + tests only); the photobooth dependency pin update to
`@v0.4.1` is for version coupling, not for behavior.

To enable the new diagnostic logging:

```sh
sudo sed -i 's/^#BOOTH_LOG_LEVEL=.*/BOOTH_LOG_LEVEL=DEBUG/' /etc/ctp/booth.env
sudo systemctl restart booth.service
```

The `Camera capture: ...size=N ... exif_dt=...` line is INFO-level and
fires regardless of `BOOTH_LOG_LEVEL`; only the GPIO ISR and main-loop
event lines require DEBUG.

## [v0.4.0] — 2026-05-20

First pip-distributable release of the booth runtime. The application is no
longer SFTP'd as loose `.py` files into `/opt/`; it is installed from a public
git tag and exposed as console scripts. Per-booth configuration moves out of
source code and into environment variables, and logging is consolidated onto
one tree with file + journald routing.

### Added
- `photobooth-run` and `photobooth-clear` `[project.scripts]` entry points
  (`photobooth.booth_main:main`, `photobooth.booth_clear:main`).
- `photobooth.logging_config.setup_logging()` — idempotent root-logger setup that
  wires a `RotatingFileHandler` at `/var/log/photobooth.log` (DEBUG+,
  5 × 10 MB backups) and a stderr handler at WARNING+. The stderr handler is
  what systemd captures into `journalctl -u booth.service`.
- Seven `BOOTH_*` environment variables consumed at startup in
  `booth_main.py`: `BOOTH_S3_BUCKET`, `BOOTH_IMAGE_DIR`, `BOOTH_CAMERA_MODEL`,
  `BOOTH_MAX_PRINTS`, `BOOTH_TEMPLATE_BASE_DIR`, `BOOTH_ACTIVE_TEMPLATE`,
  `BOOTH_LOG_LEVEL`. Each has a code-level default if unset.
- Semantic operational events throughout the runtime: component online/offline,
  template-load result, capture-lifecycle (started / shot captured /
  compressed / review decision / strip composed / completed), S3 upload start
  & finish, receipt print start & finish, network checks, button-press at the
  GPIO callback level.
- `Uploader.public_url(key)` — plain `http://<bucket>/<key>` URL built from the
  bucket name as CNAME. `upload()` now returns this instead of a presigned URL.
- `BACKLOG.md` — spec for a future smoke-test auto-QA harness.
- `.jpg` / `.gif` / `.ico` to the `photobooth_web` package data manifest so
  `nolast.jpg` and friends ship inside the wheel.
- `[project.optional-dependencies.rpi]` extra grouping the Pi-only hardware
  deps (`RPi.GPIO`, `Adafruit-Blinka`, `adafruit-circuitpython-neopixel`).
- `[project.optional-dependencies.dev]` extra for `black`, `pytest`,
  `pytest-asyncio`, `pytest-mock`.

### Changed
- Runtime is now imported from the installed package (no more
  `/opt/run_booth.py`). The old `run_booth.py` / `clear_booth.py` were moved
  into `photobooth/` as `booth_main.py` / `booth_clear.py`.
- `ctp-utilities` dependency is now a PEP 440 direct-URL reference pinned to
  `@v0.4.0`.
- `setup.py` removed; build moved to `pyproject.toml` with
  `setuptools.build_meta` and `requires-python = ">=3.7"` to keep the booth's
  Buster / Python 3.7.3 environment in support.
- `booth.py`, `rpi.py`, `camera.py`, `printer.py`, `uploader.py` all use a
  module-level `logger = logging.getLogger(__name__)` and emit through the
  `photobooth.*` logger tree. The legacy `self.logger = logging` shim and
  `Booth._init_logger()` were removed; the bare `print(err)` in
  `camera.run_local_cmd` is now a `logger.warning` call.
- Receipt QR codes encode the new plain CNAME URL — shorter URL → smaller,
  simpler QR code.

### Removed
- `setup.py` (replaced by `pyproject.toml`).
- `Booth._init_logger()` and `DEFAULT_LOG_LEVEL` / `DEFAULT_LOG_PATH`
  constants (replaced by `setup_logging()` called from `main()`).
- Legacy hand-copied entry scripts at `/opt/run_booth.py` / `/opt/clear_booth.py`
  are no longer the runtime — `init_setup.sh` in `rpi_provisioning` v0.4.0 stops
  copying them. The files still exist as rollback artifacts on previously
  provisioned booths until manually deleted in the v0.4.1 cleanup.

### Fixed
- **Reprint key bug.** `make_key()` generated a new random token on every call,
  so reprint QR codes pointed at S3 objects that did not exist. Fixed by
  stashing the original key as `_last_uploaded_key` at upload time and reusing
  it for reprints via `Uploader.public_url(key)`.
- **Reprint UX — double-scrolling neopixel.** The reprint path now cancels the
  attract scroll task before drawing the "Printing…" text, then recreates the
  attract task after the print completes.
- **Reprint UX — spammable green button.** The rate-limit cooldown is now
  anchored at print-end (`loop.time()` after `_do_print` returns) instead of
  print-start, so the next press is rejected until the printer is actually
  free.
- **Logging hijacked stderr from journald.** The previous
  `StandardError=append:` directive bypassed journald. The unit in
  `rpi_provisioning` v0.4.0 sets `StandardError=journal` so WARN+ from the
  Python logger reaches `journalctl -u booth.service`.

### Security
- **No more presigned-URL leakage in logs.** Earlier the receipt URL — a
  signed S3 GET URL containing `AWSAccessKeyId` and `Signature` query
  parameters — was being written verbatim to `/var/log/photobooth.log` and the
  systemd stdout log. v0.4.0 (a) switches to plain CNAME URLs that contain no
  credentials, and (b) drops `url=…` from the upload-complete and print log
  lines, leaving only the S3 key (which is unguessable and is itself the
  capability). A docstring on `Booth._do_print` warns future maintainers off
  re-introducing the URL into log calls.

### Upgrade

On a booth that was already running an earlier pre-v0.4.0 build:

```sh
sudo pip3 install --upgrade pip setuptools wheel           # only on Buster pip 18.x
sudo pip3 install --ignore-installed psutil                # if psutil is apt-installed
sudo pip3 install --upgrade --force-reinstall \
    "git+https://github.com/capturingtime/photobooth.git@v0.4.0"
sudo systemctl daemon-reload && sudo systemctl restart booth.service
```

The matching `booth.service` unit + `/etc/ctp/booth.env` scaffold come from
`rpi_provisioning` v0.4.0 — see that repo's CHANGELOG for the migration.

### Known limitations
- Receipt URLs are HTTP only — HTTPS to a dotted bucket name (e.g.
  `public.capturingtimephoto.net`) requires CloudFront in front of the bucket.
  Deferred to v0.4.1+.
- No `rawpy` wheel exists for armv7 + Python 3.7, so the photobooth Pi cannot
  install `ctp-utilities[raw]`. The booth doesn't need it; the RAW Archive
  workflow on the desktop machine does.

## Pre-v0.4.0 history (untagged)

No releases were tagged before v0.4.0. The repo has carried code in three
distinct eras:

- **2021-04 to 2021-08 — initial POC.** `fcd4668` introduced the package layout
  with `photobooth/{booth,neopixel,printer,rpi}.py`, a test harness, and a
  `setup.py`. `f9c052b` ("Extending framework", merged via PR #2) added
  `camera.py`, the Django-based `photobooth_web` kiosk UI, a `kiosk.sh`
  launcher, and a gphoto2 compile script. These commits established what was
  shipped to and ran on the existing v0.2.0 production booth (the booth the
  user maintains an image clone of, for rollback safety).
- **2024 to early 2026 — abandoned v0.3.0 work.** Notes from this period
  identified compatibility constraints in `rawpy` / `boto3` / Django /
  `python-escpos` / Pillow, but the action plan was abandoned. The useful
  discoveries were lifted into [project_modernization.md](../../.claude/projects/-home-ian-git-ctp/memory/project_modernization.md);
  the rest was discarded.
- **2026-05-16 to 2026-05-19 — v0.4.0 nextgen rewrite.** `60aa23d` ("major
  revisions for nextgen of booth, claude assisted") rewrote `booth.py` around
  `asyncio`, added `strip.py` and `template_loader.py` for compositor support,
  added `uploader.py` for S3, replaced the Django page set with mode-specific
  templates, added `ARCHITECTURE.md`, and introduced `pyproject.toml` + a
  `tests/test_strip.py` suite. The remaining v0.4.0 commits layered on the
  packaging / env-var / logging / security work captured under
  [v0.4.0] above.
