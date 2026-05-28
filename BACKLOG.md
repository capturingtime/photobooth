# Backlog

Future-feature notes that are scoped but not yet implemented. Promote an
entry to a workstream when it's time to build; remove when shipped.

---

## Smoke test for booth auto-QA

After every code change to the photobooth runtime, a smoke test should be
runnable on the booth (or against a booth running in test mode) to confirm
the capture → review → upload → print flow behaves end-to-end and that
nothing sensitive is leaking into logs or URLs.

### Behavior

- **Stage-by-stage trigger**: with the booth process running, the smoke
  test can advance through each stage of the capture flow (idle → capture
  start → shot N → review → keep/redo → final → print/timeout → back to
  idle, including series-mode variants).
- **Baked-in sleeps**: each stage pauses long enough to simulate the user
  loading / decision delay the booth normally sees (countdown, camera
  capture, compositing, upload, print) so timing-dependent code paths
  (e.g. event queue flushing, final-screen timeout, kiosk navigation) are
  exercised realistically.
- **Log and URL inspection**:
  - Read `/var/log/photobooth.log` after each stage and verify the
    expected semantic events fired (see `booth_main.py` event mapping).
  - Capture every URL the run emits (presigned or plain) and every QR
    payload sent to the receipt printer.
  - Pattern-match URLs and log lines for credential material:
    - `AKIA[A-Z0-9]{16}` (AWS Access Key ID)
    - `X-Amz-Signature=`, `X-Amz-Credential=`, `X-Amz-Security-Token=`
      (presigned URL params)
    - Any string starting with `AWS4-HMAC-SHA256`
    - Long base64-ish opaque strings inside query parameters
  - Any match emits a `CRITICAL` log entry naming the offending line and
    the matched pattern. CRITICAL routes through the existing
    `photobooth.logging_config` setup (file + journald), so a leak shows
    up in normal operator monitoring too.

### Open design questions when picking this up

- **Triggering mechanism**: a `BOOTH_SMOKE=1` env var that wraps
  `booth_main.main()` with a stage-driver that injects fake button events
  into `RPi.event_queue` directly? Or a separate `photobooth-smoke`
  console-script entry point that runs the smoke loop in-process and
  bypasses GPIO? In-process is simpler; an out-of-process IPC harness is
  more realistic (exercises GPIO) but requires a control socket.
- **Hardware mocks**: does the smoke run hit the real camera and printer
  or a mock layer? Mocks are necessary to run on CI; real hardware is
  necessary to catch hardware-edge-case regressions. Probably both modes,
  selected by env var.
- **Pass/fail surface**: exit code? A summary JSON written next to the
  log? A `journalctl -u booth-smoke` stream?

### Why

Workstream E gave us observable events but no automated way to verify they
fire correctly after a change. Today the only verification is the human
"press the blue button" loop we've been doing — slow, easy to forget edge
cases (redo, max-prints, upload failure paths), and impossible to run
unattended after a deploy.

The credential-material check exists because v0.4.0/F caught two
presigned URLs in plain-text logs that would otherwise have shipped to
customer-facing receipts. A smoke test that fails LOUD on key material
prevents regression on that surface.

---

## Spurious capture — EMI on GPIO signal line (root cause identified, hardware fix in progress)

### History

This entry was originally filed as "Camera sleep triggers a spurious
capture" — the symptom looked like the camera waking up was queuing a
phantom capture. After adding the diagnostic logging table below and
catching one reproduction in the wild (2026-05-23), the actual mechanism
turned out to be two stacked failures that together produced the
observed symptom.

### What it actually was

1. **EMI-induced falling edge on the GPIO signal line.** The original
   button wiring left the GPIO signal line idle LOW (pulled to GND via
   a 10 kΩ resistor) on a long unshielded cat5e run that shared a
   jacket with a 12 V LED-supply pair. Capacitive coupling from nearby
   switching loads (receipt printer inrush, neopixel PWM, USB to the
   camera) injected positive-going spikes onto the signal line. Each
   spike briefly pulled the line HIGH; as the spike dissipated through
   the 10 kΩ pull-down, the line settled back to LOW — producing a
   falling edge that looked indistinguishable from a real press to the
   ISR.
2. **Camera was asleep** when the phantom capture fired. gphoto2's
   `--capture-image-and-download` exited successfully (returncode 0)
   without producing a file: `size=-1, elapsed=0.13s` in the logs.
   The booth then crashed when downstream code tried to open the
   nonexistent JPEG.

Each failure on its own would have been noticeable but recoverable;
together they produced a complete process exit triggered by no human
action, which is why it looked so mysterious.

### Hardware fix (validated 2026-05-25 on the capture button)

Rewired GPIO 25 / pin 22 (capture button) to active-low topology:
- Pull-up: 10 kΩ from SIG → 3.3V at the Pi end (was: pull-down from
  SIG → GND at the Pi end)
- Button: shorts SIG → GND when pressed (was: shorts SIG → 3.3V)
- Series protection: 1 kΩ between SIG and GPIO 25 (unchanged)
- Low-pass: 100 nF (0.1 µF) from SIG → GND at the Pi end (new)
- Cable: cat5e pair carries SIG + signal-GND on one twisted pair
  (was: SIG + 3.3V supply, which defeated twisted-pair noise rejection)

Why this works:
- Idle state is now HIGH (3.3V). Positive-going EMI spikes can only
  push the line slightly higher, clipped by the Pi input clamp diodes;
  the spike's dissipation back to 3.3V produces no falling edge → no
  phantom ISR.
- The 100 nF + 10 kΩ low-pass adds a ~1 ms filter cutoff. Real presses
  (≥ 50 ms) pass; sub-millisecond EMI is rejected regardless of polarity.
- Twisted pair common-mode rejection now works because both wires of
  the pair carry a related signal pair (SIG + its return).

Validation: 3.5-hour idle test on the rewired capture button produced
zero phantom triggers. Red and green buttons (still on original wiring)
serve as the control group; if they continue to misbehave over longer
windows, the diagnosis is conclusive.

### Status (2026-05-25)

- **Capture button**: rewired, validated, in production on the live
  booth. See `rpi_provisioning/HARDWARE.md` for the topology and the
  cat5e pair assignment.
- **Red and green buttons**: still on the defective v0.2.0 wiring.
  See "Apply rewire to red and green buttons" below.
- **Software-side resilience layer**: not yet shipped — even after
  the rewire, gphoto2 can still return success-with-no-file when the
  camera is asleep. See "File-size guard in `Camera.capture_async`"
  below for the catch-and-recover plan.
- **Release-bounce as a side effect**: discovered during validation,
  documented separately below.

### Diagnostic logging (kept; still useful for future GPIO triage)

Three log lines bracket every capture. Enable the high-frequency
events with `BOOTH_LOG_LEVEL=DEBUG` in `/etc/ctp/booth.env`:

| Layer | Level | Line | What to look for |
|---|---|---|---|
| GPIO ISR (`rpi._on_press`) | DEBUG | `Button event: label=X pin=N queue_depth_before=Q` | `queue_depth_before > 0` on consecutive presses of the same button ⇒ ISR firing multiple times for one physical press (bounce/EMI). Phantom event with depth=0 = a single noise-induced edge made it through. |
| Main loop (`booth_main.run`) | DEBUG | `Main loop event: X` | An entry here with no matching `Button event` ⇒ event-bridge bug (very unlikely). Pair timestamps to measure GPIO→dispatch latency. |
| Camera result (`camera.capture_async`) | INFO | `Camera capture: model=... file=... size=N elapsed=Ts exif_dt=...` | `size < ~100 KB` or `size = -1` ⇒ junk/empty frame. `exif_dt` significantly older than wall-clock ⇒ stale buffered frame (note: only useful if the camera body clock has been set). |

When the next suspicious capture occurs, grep `/var/log/photobooth.log`:

```sh
grep -B 30 -A 5 "Capture started" /var/log/photobooth.log | less
```

---

## Apply rewire to red and green buttons

Apply the same active-low circuit shipped on the capture button
(see "Spurious capture — EMI on GPIO signal line") to GPIO 23
(green / pin 16) and GPIO 24 (red / pin 18). Same parts per button
(10 kΩ + 1 kΩ + 100 nF), same cat5e pair assignment.

Until this is done, expect occasional phantom red/green events
under EMI load. The booth handles them more gracefully than a
phantom capture (red is just "back to attract", green is reprint
or "keep" depending on context), but cosmetic at minimum.

Promote the wiring topology in `rpi_provisioning/HARDWARE.md` from
"in progress" to "current" once all three buttons are on the new
design.

---

## Release-bounce on long-hold-release produces a spurious event

### Symptom

With the new active-low wiring, holding a button for longer than the
500 ms GPIO `bouncetime` window and then releasing produces an extra
`Button event` log line on release.

Observed 2026-05-25 during wiring validation: capture press at
`13:59:21`, held through the capture flow, released at `~13:59:30` —
a second `Button event: label=capture pin=25 queue_depth_before=0`
fired at 13:59:30.

### Mechanism

Mechanical switch contacts physically bounce when they OPEN, not just
when they close. With the active-low circuit, releasing a held button
ramps the line from 0V → 3.3V via the pull-up; contact bounce briefly
re-makes the closed state, pulling the line back to 0V momentarily.
Each re-make is a falling edge. The `bouncetime=500` parameter only
suppresses events within 500 ms of the **previous registered event**;
if the original press was longer than 500 ms ago, the first
bounce-induced falling edge gets through.

This did not occur with the old (idle-LOW) wiring because the ISR
fired on the natural release transition (the only falling edge
available); there was no "second falling edge" to bounce.

### Impact

Cosmetic if it happens at the final-screen hold (gets flushed by
`_flush_events()`), potentially functional if it happens mid-flow
where a queued event could be picked up by `_review_shot` and
interpreted as a decision the user didn't make. Has not been observed
to cause a misbehavior in normal use yet — operators typically tap
rather than hold.

### Fix options

- **Software flush after `_take_one_shot`**: drain the event queue
  immediately after each capture, before `_review_shot` polls. Cheap;
  consistent with the existing `_flush_events()` pattern.
- **Asyncio-side debounce in `RPi.next_event`**: track the last event
  timestamp per label and discard duplicates within a configurable
  window (e.g. 1 s). More general but adds state.
- **Switch to RISING-edge detection** (release-detect, like the
  defective old wiring): works but is unintuitive and re-introduces
  the noise susceptibility we just fixed.

The flush-after-capture is the lightest touch and matches the existing
discipline. Slot when next worth touching `booth_main.run`.

---

## File-size guard in `Camera.capture_async`

### Why

Even with the GPIO line fixed, gphoto2 can still return success
without producing a file when the camera is in an unusual state
(asleep, USB hiccup, battery brown-out). Today the booth treats any
non-raising return as a real shot and crashes downstream when
something tries to open the nonexistent JPEG.

### Behavior

In `photobooth/camera.py:Camera.capture_async()`, after the existing
log line:

- If `not os.path.exists(pic)` or `os.path.getsize(pic) <= 0` or
  `< ~100 KB`: raise a new `CaptureFailed("gphoto2 returned success
  but no file on disk")` exception. Do not append to `_captures`;
  reset `_ready = True` so the next press can try again.

In `photobooth/booth_main.py:_run_single` / `_run_series`:

- Wrap the `await self._take_one_shot()` call in
  `try / except CaptureFailed`.
- On exception: cancel the attract task, scroll a short "Camera not
  ready, try again" message on the neopixel, navigate back to the
  attract URL, drop back into the main event loop.

### Why this is independent of the wiring fix

The wiring fix prevents the phantom capture from being triggered in
the first place. This guard prevents the booth from crashing when a
capture is triggered (legitimately or otherwise) but the camera
fails to produce a file. Both are wanted; they cover different
failure modes.

### Optional follow-up

If the camera-sleep root cause turns out to be the dominant one even
with the rewire complete, the simplest fix is one line of additional
camera startup config in `booth_main.py`:

```python
CAMERA_STARTUP_CONFIG = {
    "autoexposuremode": 3,
    "autopoweroff": 0,  # never sleep
}
```

Trade-off: sensor stays warm during long idle days; potentially
shortens shutter life on a multi-day event. Worth measuring before
committing.
