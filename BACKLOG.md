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
