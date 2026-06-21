"""
This class written and tested with:
$ gphoto2 --version
gphoto2         2.5.27         gcc, popt(m), exif, no cdk, no aa, no jpeg, no readline
libgphoto2      2.5.22         all camlibs, gcc, ltdl, EXIF
libgphoto2_port 0.12.0         iolibs: disk ptpip serial usb1 usbdiskdirect usbscsi
"""

import asyncio
import logging
import os
import re
import subprocess

from datetime import datetime
from sys import platform

logger = logging.getLogger(__name__)

DEFAULT_CAPTURE_DIR = "/opt/captures"

# Below this byte count, a downloaded "capture" is almost certainly a stale
# buffer frame or empty wakeup artifact (a real Canon JPEG is >1 MB). The
# Phase 5 unavailable-mode path keys off the exception this triggers.
MIN_VALID_CAPTURE_BYTES = 100_000


class CameraCaptureError(RuntimeError):
    """Raised when gphoto2 returns without a valid image on disk.

    Bridges Phase 5: ``_take_one_shot`` catches this and enters
    unavailable mode (``"camera"`` / ``CAMERA_UNAVAILABLE_TEXT``), then
    waits for HealthMonitor recovery.
    """


def run_local_cmd(cmd: str):
    """Run a shell command synchronously. Used during init/config only."""
    try:
        return subprocess.run(cmd, shell=True, capture_output=True)
    except Exception as err:
        logger.error("run_local_cmd failed: %s", err)


def check_os():
    if not platform == "linux":
        raise RuntimeError(
            f"Linux is the only supported OS for this class. Detected: {platform}"
        )
    return True


def check_dir_rw_or_make(tgt_dir: str, mkdir_perms=0o766) -> bool:
    """Ensure target directory exists and is read/write accessible."""
    check_os()
    if tgt_dir.startswith("~"):
        tgt_dir = os.path.expanduser(tgt_dir)

    if os.path.exists(tgt_dir):
        if not os.access(tgt_dir, os.W_OK) and not os.access(tgt_dir, os.R_OK):
            status = os.stat(tgt_dir)
            p = oct(status.st_mode)[-3:]
            raise OSError(
                f"Target directory '{tgt_dir}' exists, but not RW. Permission: {p}"
            )
        return True
    else:
        os.mkdir(tgt_dir)
        os.chmod(tgt_dir, mkdir_perms)
        return check_dir_rw_or_make(tgt_dir)


def check_gphoto2() -> bool:
    check_os()
    result = subprocess.run("which gphoto2", shell=True, capture_output=True)
    check = result.stdout.decode("utf-8").strip("\n").split("/")[-1:]
    if "gphoto2" not in check:
        raise RuntimeError("GPhoto2 was not found on this system")
    return True


def supported_camera_list() -> list:
    check_gphoto2()
    cameras = subprocess.run("gphoto2 --list-cameras", shell=True, capture_output=True)
    cameras = cameras.stdout.decode("utf-8").split("\n\t")
    return [v.strip("\n").strip('"') for v in cameras][1:]


def get_cameras() -> list:
    check_gphoto2()
    cameras = subprocess.run("gphoto2 --auto-detect", shell=True, capture_output=True)
    cameras = cameras.stdout.decode("utf-8").strip(" \n").split("\n")[2:]
    detected_cameras = list()
    for c in cameras:
        model, addr = re.split(" {2,}", c)
        detected_cameras.append({"model": model, "addr": addr})
    return detected_cameras


async def probe_camera_available(model: str) -> bool:
    """Return True if gphoto2 sees ``model`` AND the camera answers a PTP query.

    Used by ``HealthMonitor`` (v0.5.0 Phase 4) to decide whether the
    booth can proceed past startup *or* resume capture after a failure.
    Never raises — any error during detection is treated as "not
    present" and the caller will retry.

    USB enumeration (``--auto-detect``) is necessary but not sufficient:
    the Canon T7i appears on the USB bus for several seconds after
    power-on before its PTP layer is ready to capture, and a failed
    camera mid-session can leave gphoto2 reporting "detected" while
    actual captures return phantom 0-byte files. ``--summary`` forces a
    real PTP roundtrip, which fails fast when the camera isn't truly
    captureable — gating recovery on it stops the unavailable-mode
    recovery from looping straight back into another failed capture.
    """
    loop = asyncio.get_running_loop()
    try:
        cameras = await loop.run_in_executor(None, get_cameras)
    except Exception as exc:
        logger.debug("probe_camera_available: detection error %s", exc)
        return False
    if not any(model in c.get("model", "") for c in cameras):
        return False
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                "gphoto2 --summary",
                shell=True,
                capture_output=True,
                timeout=5,
            ),
        )
    except Exception as exc:
        logger.debug("probe_camera_available: summary error %s", exc)
        return False
    return result.returncode == 0


def capture_and_download(download_dir: str, camera: str, port: str) -> str:
    """Synchronous gphoto2 capture. Kept for non-async callers / testing."""
    filename = _build_filename(download_dir)
    result = subprocess.run(
        f"gphoto2 --capture-image-and-download --keep-raw "
        f"--filename '{filename}' "
        f"--camera '{camera}' "
        f"--port '{port}'",
        capture_output=True,
        shell=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gphoto2 capture failed.\n"
            f"stdout: {result.stdout.decode()}\n"
            f"stderr: {result.stderr.decode()}"
        )
    return filename


async def capture_and_download_async(download_dir: str, camera: str, port: str) -> str:
    """Async gphoto2 capture — does not block the event loop during image download."""
    filename = _build_filename(download_dir)
    proc = await asyncio.create_subprocess_shell(
        f"gphoto2 --capture-image-and-download --keep-raw "
        f"--filename '{filename}' "
        f"--camera '{camera}' "
        f"--port '{port}'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"gphoto2 capture failed.\n"
            f"stdout: {stdout.decode()}\n"
            f"stderr: {stderr.decode()}"
        )
    return filename


def _build_filename(download_dir: str) -> str:
    ds = datetime.now().strftime("%Y%m%d-%Hh%Mm%Ss-%f")
    return f"{download_dir}/{ds}.jpg"


def config_gphoto2(*args, **kwargs) -> bool:
    args_str = " ".join(str(v) for v in args)
    kwargs_str = " ".join(f"{k}={v}" for k, v in kwargs.items())
    result = subprocess.run(
        f"gphoto2 --set-config {args_str} {kwargs_str}",
        shell=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gphoto2 config failed.\n"
            f"stdout: {result.stdout.decode()}\n"
            f"stderr: {result.stderr.decode()}"
        )
    return True


class Camera:
    """Manages image capture via gphoto2.

    Single-process asyncio design: state is plain instance variables.
    Use capture_async() in async contexts; capture() remains for sync callers.
    """

    def __init__(
        self,
        model: str,
        output_dir: str = DEFAULT_CAPTURE_DIR,
        name: str = "",
        leave_raw: bool = True,
        startup_config: dict = None,
    ):
        if not name:
            name = f"camera-{id(self)}"
        self.name = name
        self.model = model
        self.output_dir = (
            output_dir
            if not output_dir.startswith("~")
            else os.path.expanduser(output_dir)
        )

        # Plain state — no Manager() proxies needed in a single-process asyncio app
        self._ready: bool = False
        self._last_shot: str = ""
        self._captures: list = []

        check_dir_rw_or_make(output_dir)

        self.detected_cameras = get_cameras()
        self.addr = str()

        supported_cameras = supported_camera_list()
        if self.model not in supported_cameras:
            match = False
            for a_model in supported_cameras:
                if self.model.lower() in a_model.lower():
                    match = True
                    self.model = a_model
            if not match:
                raise ValueError(
                    f"Provided model ({self.model}) not in supported list. "
                    "Call supported_camera_list() for a full list."
                )

        for camera in self.detected_cameras:
            if self.model in camera["model"]:
                self.addr = camera["addr"]

        if not self.addr:
            raise RuntimeError(
                f"Requested camera ({self.model}) is not detected.\n"
                f"Detected: {self.detected_cameras}"
            )

        config_gphoto2(capturetarget=int(leave_raw))
        if startup_config:
            config_gphoto2(**startup_config)
        self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    def refresh_address(self) -> bool:
        """Re-detect the camera USB port and update ``self.addr``.

        Power-cycling a USB camera re-enumerates the device and frequently
        assigns a new bus/dev address (the ``usb:NNN,NNN`` token passed
        to ``gphoto2 --port``). The Camera object captured the address at
        ``__init__`` time, so after a recovery from unavailable mode the
        next capture would target the dead port and gphoto2 returns
        success with no file on disk (the phantom-file failure mode that
        breaks Phase 5 recovery).

        Returns True when a matching camera was re-detected; False
        otherwise (the caller is already in a failure path and will
        treat False as "still unavailable").
        """
        try:
            detected = get_cameras()
        except Exception as exc:
            logger.warning("refresh_address: detection failed: %s", exc)
            return False
        for camera in detected:
            if self.model in camera["model"]:
                if camera["addr"] != self.addr:
                    logger.info(
                        "Camera USB address changed: %s -> %s",
                        self.addr,
                        camera["addr"],
                    )
                    self.addr = camera["addr"]
                self.detected_cameras = detected
                return True
        logger.warning("refresh_address: model %s not in detected list", self.model)
        return False

    def captures(self) -> list:
        return list(self._captures)

    def last_shot(self) -> str:
        return self._last_shot

    def copy_last_shot_to_dir(self, dir: str) -> bool:
        rw = check_dir_rw_or_make(tgt_dir=dir)
        if rw:
            run_local_cmd(f"cp {self._last_shot} {dir}")
            return True
        return False

    def capture(self) -> str:
        """Synchronous capture — blocks until image is downloaded. Prefer capture_async()."""
        if not self._ready:
            raise RuntimeError("Camera is not ready")
        self._ready = False
        pic = capture_and_download(
            download_dir=self.output_dir, camera=self.model, port=self.addr
        )
        self._captures.append(pic)
        self._last_shot = pic
        self._ready = True
        return pic

    async def capture_async(self) -> str:
        """Async capture — does not block the event loop during gphoto2 execution."""
        if not self._ready:
            raise RuntimeError("Camera is not ready")
        self._ready = False
        loop = asyncio.get_running_loop()
        start = loop.time()
        pic = await capture_and_download_async(
            download_dir=self.output_dir, camera=self.model, port=self.addr
        )
        elapsed = loop.time() - start

        # Forensic detail for the spurious-capture investigation:
        # * ``size`` < ~100 KB or -1 ⇒ gphoto2 returned 0 but no real image
        #   landed on disk (likely camera-buffer or wakeup-frame artifact).
        # * ``exif_dt`` significantly older than wall-clock ⇒ stale frame
        #   pulled from the camera buffer rather than a fresh shutter.
        # See BACKLOG.md → "Camera sleep triggers a spurious capture".
        size = os.path.getsize(pic) if os.path.exists(pic) else -1
        exif_dt = _read_exif_datetime(pic) if size > 0 else None
        logger.info(
            "Camera capture: model=%s file=%s size=%d elapsed=%.2fs exif_dt=%s",
            self.model,
            pic,
            size,
            elapsed,
            exif_dt,
        )

        # Phantom-file guard: when the camera is unpowered mid-session,
        # gphoto2 silently downloads a 0-byte (or size=-1) "frame" and
        # returns success. Raising here lets Phase 5 unavailable mode
        # take over instead of the strip composer choking downstream.
        if size < MIN_VALID_CAPTURE_BYTES:
            self._ready = True
            raise CameraCaptureError(
                f"Empty/short capture from {self.model}: path={pic} size={size} "
                f"elapsed={elapsed:.2f}s exif_dt={exif_dt}"
            )

        self._captures.append(pic)
        self._last_shot = pic
        self._ready = True
        return pic


def _read_exif_datetime(path: str):
    """Return EXIF DateTimeOriginal as a string, or None on any failure.

    Used only for diagnostic logging — must never raise, never block, and
    never affect the capture return value. PIL is imported lazily so the
    module remains importable on systems without Pillow.
    """
    try:
        from PIL import ExifTags, Image

        with Image.open(path) as img:
            exif = img._getexif() or {}
        tag_id = next(
            (k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal"),
            None,
        )
        return exif.get(tag_id) if tag_id is not None else None
    except Exception:
        return None
