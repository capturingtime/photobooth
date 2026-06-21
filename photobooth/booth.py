import asyncio
import logging
import os
import pathlib
import shutil
import urllib.request
import subprocess

from photobooth.printer import Printer
from photobooth.neopixel import Neopixel
from photobooth.camera import Camera

logger = logging.getLogger(__name__)


def connect(host: str = "http://google.com") -> bool:
    """Synchronous HTTP connectivity probe — used during startup polling."""
    try:
        urllib.request.urlopen(host)
        return True
    except Exception:
        return False


def arp_list(broadcast_ip: str = "255.255.255.255") -> list:
    """Gets a list of hosts responding to arp."""
    subprocess.run(f"ping -c2 {broadcast_ip} -b", shell=True, capture_output=True)
    arp_raw = subprocess.run("arp | grep ether", shell=True, capture_output=True)
    arp_raw = arp_raw.stdout.decode("utf-8").strip("\n").split("\n")
    result = list()
    for a in arp_raw:
        p, t, m, f, i = a.split()
        result.append({"ip": p, "mac": m, "interface": i})
    return result


async def probe_internet_available(host: str = "http://google.com") -> bool:
    """Async wrapper around ``connect`` for ``HealthMonitor`` use (v0.5.0 Phase 4)."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, connect, host)
    except Exception as exc:
        logger.debug("probe_internet_available: %s", exc)
        return False


async def probe_local_network() -> bool:
    """Return True when ARP discovers any neighbor on the LAN."""
    loop = asyncio.get_running_loop()
    try:
        neighbors = await loop.run_in_executor(None, arp_list)
    except Exception as exc:
        logger.debug("probe_local_network: %s", exc)
        return False
    return bool(neighbors)


async def probe_web_available(
    url: str = "http://127.0.0.1:8000/main/",
) -> bool:
    """Return True when the local Django server responds to ``url``."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, connect, url)
    except Exception as exc:
        logger.debug("probe_web_available: %s", exc)
        return False


class Booth:
    """Orchestrates photobooth components and owns the asyncio event queue.

    Hardware-agnostic: GPIO and platform specifics live in the RPi subclass.
    """

    def __init__(self, web_root: str = None, debug: bool = False):
        self.abspath = os.path.dirname(__file__)
        self.debug = debug

        if not web_root:
            parent_dir = str(pathlib.Path(__file__).resolve().parents[1])
            self.web_root = f"{parent_dir}/photobooth_web"
        else:
            self.web_root = web_root

        # Single-process asyncio: shared state is plain Python, no IPC proxies needed
        self.event_queue: asyncio.Queue = asyncio.Queue()

    async def next_event(self) -> str:
        """Await the next button/hardware event from the queue.

        GPIO interrupt callbacks push into this queue via call_soon_threadsafe.
        The main loop awaits here cheaply (no busy-wait).
        """
        return await self.event_queue.get()

    @staticmethod
    def create_task(coro) -> asyncio.Task:
        """Wrap a coroutine in an asyncio Task (replaces the old Thread/Process wrapper)."""
        return asyncio.create_task(coro)

    async def start_web(self) -> asyncio.subprocess.Process:
        """Launch Django as a background subprocess."""
        self._web_process = await asyncio.create_subprocess_exec(
            "python3",
            f"{self.web_root}/manage.py",
            "runserver",
            "0.0.0.0:8000",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return self._web_process

    async def stop_web(self) -> None:
        proc = getattr(self, "_web_process", None)
        if proc:
            proc.terminate()
            await proc.wait()

    async def start_kiosk(self) -> asyncio.subprocess.Process:
        """Launch the X11 kiosk session as a background subprocess.

        Uses create_subprocess_shell because the command relies on $(fgconsole) shell substitution.
        """
        cmd = f"xinit {self.abspath}/resources/kiosk.sh -- vt$(fgconsole)"
        self._kiosk_process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return self._kiosk_process

    def copy_to_last_shot(self, last_shot: str) -> bool:
        """Copy the captured image to the path Django serves as last.html background."""
        if not getattr(self, "_last_shot_tgt", None):
            self._init_last_shot()
        try:
            shutil.copy(last_shot, self._last_shot_tgt)
        except Exception as err:
            logger.error("copy_to_last_shot failed: %s", err)
            return False
        return True

    async def display_url(self, url: str) -> None:
        """Navigate the kiosk browser to the given URL via CDP (fast, no respawn).

        Falls back to spawning a new Chromium process if the debugging port
        is not yet available (e.g. during initial startup).
        """
        import json
        import urllib.request
        import websockets

        try:
            with urllib.request.urlopen(
                "http://localhost:9222/json", timeout=1
            ) as resp:
                tabs = json.loads(resp.read())
            ws_url = tabs[0]["webSocketDebuggerUrl"]
            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"id": 1, "method": "Page.navigate", "params": {"url": url}}
                    )
                )
                await ws.recv()
        except Exception:
            await asyncio.create_subprocess_shell(
                f"chromium-browser --kiosk --no-sandbox --display=:0.0 --incognito {url}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

    async def display_last_shot(self) -> None:
        """Navigate the kiosk browser to the last-shot display page."""
        await self.display_url("http://127.0.0.1:8000/main/last/")

    def reset_last_shot(self) -> bool:
        """Reset last.jpg to the placeholder image."""
        if not getattr(self, "_last_shot_tgt", None):
            self._init_last_shot()
        img_dir = f"{self.web_root}/mainscreen/static/img"
        shutil.copy(f"{img_dir}/nolast.jpg", f"{img_dir}/last.jpg")
        return True

    def _init_last_shot(self) -> None:
        self._last_shot_tgt = f"{self.web_root}/mainscreen/static/img/last.jpg"

    def except_and_log(self, ex_type=ValueError, ex_msg: str = "", log: str = ""):
        if not ex_msg:
            ex_msg = "An unspecified exception occurred"
        try:
            raise ex_type(ex_msg)
        except Exception:
            logger.exception(log)

    @staticmethod
    def _init_printer(model: str = None, name: str = None, **kwargs):
        return Printer(model=model, name=name, **kwargs)

    def add_printer(self, name: str = None, model: str = None, **kwargs):
        if not getattr(self, "printers", None):
            self.printers = list()
        if not name:
            name = f"printer-{len(self.printers) + 1}"
        printer = self._init_printer(name=name, model=model, **kwargs)
        self.printers.append(printer)
        return printer

    @staticmethod
    def _init_neopixel(**kwargs):
        return Neopixel(**kwargs)

    def add_neopixel(
        self, name: str = None, control=None, rows: int = 8, cols: int = 32, **kwargs
    ):
        if not getattr(self, "neopixels", None):
            self.neopixels = list()
        if not name:
            name = f"neopixel-{len(self.neopixels) + 1}"
        update = {"name": name, "control": control, "rows": rows, "cols": cols}
        kwargs.update({k: v for k, v in update.items() if v})
        neopixel = self._init_neopixel(**kwargs)
        self.neopixels.append(neopixel)
        return neopixel

    @staticmethod
    def _init_camera(**kwargs):
        return Camera(**kwargs)

    def add_camera(self, name: str = None, model: str = None, **kwargs):
        if not model:
            raise ValueError(
                "model is a required field. Use supported_camera_list() "
                "from photobooth.camera for a list of supported camera models"
            )
        if not getattr(self, "cameras", None):
            self.cameras = list()
        if not name:
            name = f"camera-{len(self.cameras) + 1}"
        camera = self._init_camera(name=name, model=model, **kwargs)
        self.cameras.append(camera)
        return camera

    @staticmethod
    def net_check_local():
        return arp_list()

    @staticmethod
    def net_check_www():
        return connect()

    @staticmethod
    def check_web():
        return connect("http://127.0.0.1:8000/main/")

    def clear_components(self) -> bool:
        if getattr(self, "neopixels", None):
            for np in self.neopixels:
                np.clear()
            delattr(self, "neopixels")
        if getattr(self, "cameras", None):
            delattr(self, "cameras")
        if getattr(self, "printers", None):
            delattr(self, "printers")
        return True
