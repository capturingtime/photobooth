# Photobooth

Raspberry Pi 4B photobooth framework for Capturing Time Photography. Supports
single-shot and multi-shot strip modes with per-shot review, S3 upload, and ESC/POS
receipt printing.

![Raspberry Pi Circuit Diagram](./img/RPi-4B-circuit-diagram.png "Raspberry Pi 4B")

## Hardware

- Raspberry Pi 4B (Raspberry Pi OS, Python 3.7+)
- Canon EOS DSLR via USB / gphoto2
- NeoPixel (ws281x) LED panel — 8×32
- PBM-8350U thermal receipt printer (ESC/POS)
- Three momentary buttons on GPIO 23 (green), 24 (red), 25 (blue)

## Package Structure

```
photobooth/           ← installable Python package
photobooth_web/       ← Django kiosk web app
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for a full component map, asyncio design,
template system reference, capture flow diagrams, and GPIO wiring.

## Running the Booth

The booth runs as a systemd service on the Pi:

```bash
sudo systemctl start booth
sudo systemctl status booth
sudo journalctl -u booth -f          # or: tail -f /var/log/booth_stdout.log
```

The entry point is the `photobooth-run` console script (installed at
`/usr/local/bin/photobooth-run` by `pip install`). It's defined as a
`[project.scripts]` entry in `pyproject.toml` and maps to `photobooth.booth_main:main`.
Top-of-file constants in `photobooth/booth_main.py` control the active camera,
template, and S3 bucket — no code changes needed for routine configuration.

`photobooth-clear` (mapped to `photobooth.booth_clear:main`) is invoked from
`ExecStopPost=` to dark the NeoPixel and LEDs on service stop.

## Installing on a Pi

```bash
sudo pip3 install "git+https://github.com/capturingtime/photobooth.git@vX.Y.Z"
```

Pulls `ctp-utilities` as a transitive dependency from its matching git tag. The
ESC/POS printer, NeoPixel, and GPIO deps are listed under `[project.optional-dependencies.rpi]`
and aren't installed by default — `pip install ".[rpi]"` for hardware setups (the
Pi already has the apt versions of `RPi.GPIO` and `Adafruit-Blinka` so this is
rarely needed in practice).

## Development

### Install (non-Pi, for tests only)

```bash
cd photobooth
python3 -m venv env
env/bin/pip install -e ".[dev]"
env/bin/pytest tests/ -v
```

Hardware-dependent imports (`RPi.GPIO`, `neopixel`, `board`, `boto3`) are wrapped in
`try/except ImportError` in `__init__.py` and are not required for running tests.

### Django tests

```bash
cd photobooth/photobooth_web
python3 manage.py test mainscreen
```

## Templates

Compositor templates (PNG + JSON sidecar) live at `/opt/photobooth/templates/` on the
Pi. Screen overlay PNGs live at `photobooth_web/mainscreen/static/img/`. See
[ARCHITECTURE.md § Template System](./ARCHITECTURE.md) for the full schema and
compositing pipeline.
