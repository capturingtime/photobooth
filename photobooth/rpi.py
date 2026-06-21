import asyncio
import logging

from photobooth.booth import Booth

import RPi.GPIO as GPIO

logger = logging.getLogger(__name__)

#   (label, use, gpio_bcm_pin, io, init_state)
# Pass label=pin_number as a kwarg to RPi() to override any default pin.
DEFAULT_PIN_MAP = [
    ("gpio_init", "led", 17, "out", False),  # Pin 11
    ("net_local", "led", 27, "out", False),  # Pin 13
    ("net_www", "led", 22, "out", False),  # Pin 15
    ("camera_rdy", "led", 13, "out", False),  # Pin 33
    ("print_rdy", "led", 19, "out", False),  # Pin 35
    ("shutter_rdy", "led", 26, "out", False),  # Pin 37
    ("printing", "led", 0, "out", False),  # Pin TBD
    ("green", "sw", 23, "in", None),  # Pin 16 — keep / print / show last shot
    ("red", "sw", 24, "in", None),  # Pin 18 — redo / start over
    ("capture", "sw", 25, "in", None),  # Pin 22 — shutter / continue
    ("pixel", "ctl", 18, "out", False),  # Pin 12
]


class RPi(Booth):
    """Raspberry Pi 4B photobooth controller.

    Extends Booth with GPIO management and an asyncio event bridge.
    Call setup_gpio_events(loop) after the asyncio event loop is running to
    register GPIO interrupts that push button labels into self.event_queue.
    """

    compute_type = "SBC"
    family = "Raspberry Pi"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        Booth.__init__(self)
        self._init_gpio()

    def _init_gpio(self) -> None:
        """Initialize GPIO pins from DEFAULT_PIN_MAP with optional overrides."""
        logger.info("Initializing GPIO")

        self.gpio = GPIO
        setattr(self.gpio, "init", False)
        setattr(self.gpio, "map", dict())
        setattr(self.gpio, "pins", dict())

        if not self.debug:
            self.gpio.setwarnings(False)

        self._configure_pins()

        self.gpio.setmode(GPIO.BCM)

        for use in self.gpio.map.values():
            for label, values in use.items():
                pin = values["pin"]
                io = values["io"]
                state = values["init_state"]

                if io == "in":
                    m = GPIO.IN
                elif io == "out":
                    m = GPIO.OUT
                else:
                    self._reset_and_cleanup()
                    self.except_and_log(
                        ex_msg=f"Invalid IO mode '{io}' for {label} on pin {pin}. "
                        "Expected 'in' or 'out'."
                    )
                    continue

                self.gpio.setup(pin, m)
                if m == GPIO.OUT:
                    self.gpio.output(pin, state)

        self.gpio.init = True
        logger.info("GPIO init complete")
        self.toggle_led(label="gpio_init", on=True)

    def setup_gpio_events(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register GPIO falling-edge interrupts for all switch (button) pins.

        Bridges the GPIO interrupt thread to the asyncio event loop via
        call_soon_threadsafe, which is the only thread-safe way to schedule
        work on a running event loop from a non-async thread.

        bouncetime=200 ms provides hardware-level debounce.
        """

        def _on_press(channel, lbl=None, pin=None):
            # queue_depth_before is the forensic signal for the spurious-capture
            # investigation: if a single physical press produces multiple ISR
            # firings, the depth will climb past 0 on the second+ entry. A
            # clean press is always depth=0 (assuming the main loop is keeping
            # up). See BACKLOG.md → "Camera sleep triggers a spurious capture".
            logger.debug(
                "Button event: label=%s pin=%d queue_depth_before=%d",
                lbl,
                pin,
                self.event_queue.qsize(),
            )
            loop.call_soon_threadsafe(self.event_queue.put_nowait, lbl)

        for label, data in self.gpio.map.get("sw", {}).items():
            pin = data["pin"]
            GPIO.add_event_detect(
                pin,
                GPIO.FALLING,
                bouncetime=500,
                callback=lambda channel, lbl=label, pin=pin: _on_press(channel, lbl=lbl, pin=pin),
            )
        logger.info("GPIO event detection registered")

    def _configure_pins(self) -> None:
        """Populate gpio.map and gpio.pins from defaults, then apply kwargs overrides."""
        for label, use, pin, io, init_state in DEFAULT_PIN_MAP:
            if not self.gpio.map.get(use, None):
                self.gpio.map[use] = dict()
            self.gpio.map[use][label] = {"pin": pin, "io": io, "init_state": init_state}
            self.gpio.pins[label] = pin

        for k, v in list(self.kwargs.items()):
            for label, use, pin, io, init_state in DEFAULT_PIN_MAP:
                if k == label:
                    self.gpio.map[use][label]["pin"] = int(v)
                    self.gpio.pins[label] = int(v)
                    self.kwargs.pop(k, None)

        # Catch duplicate pins before hardware init causes silent failures
        if len(set(self.gpio.pins.values())) != len(self.gpio.pins):
            self._reset_and_cleanup()
            self.except_and_log(ex_msg=f"Duplicate pin configured: {self.gpio.pins}")

    def _reset_and_cleanup(self) -> None:
        self.gpio.init = False
        self._init_gpio()
        for led, values in self.gpio.map["led"].items():
            self.gpio.output(values["pin"], values["init_state"])

    def _get_pin_by_label(self, label: str = "") -> int:
        if not label:
            self.except_and_log(ex_msg="'label' is required for _get_pin_by_label()")
        pin = [v for k, v in self.gpio.pins.items() if label == k]
        if not pin:
            self.except_and_log(ex_msg=f"No pin found for '{label}' in gpio.pins: {self.gpio.pins}")
            return None
        return pin[0]

    def _check_pin_use(self, label: str = "", pin: int = 0, pintype: str = "led") -> bool:
        if not label and not pin:
            logger.warning("One of 'label' or 'pin' is required for _check_pin_use()")
            return None
        if label and pin:
            pin = 0  # label takes precedence
        pins = self.gpio.map[pintype]
        if label and pins.get(label, None):
            return True
        elif pin:
            for _, values in pins.items():
                if pin == values["pin"]:
                    return True
        self.except_and_log(
            ex_msg=f"Pin {pin or label!r} not configured as {pintype} in {self.gpio.map}"
        )
        return False

    async def blink_led(self, label: str = "", pin: int = 0, speed: float = 1) -> bool:
        """Blink an LED once at the given speed (seconds per cycle).

        Replaces the former time.sleep() version — yields to the event loop
        during the on/off intervals so other coroutines can run concurrently.
        """
        if not self._check_pin_use(label=label, pin=pin):
            return False
        if label:
            pin = self._get_pin_by_label(label)

        speed = max(speed, 0.1)  # cap at 10 blinks/sec
        on = speed * 0.25
        off = speed * 0.75

        if self.gpio.input(pin):
            self.gpio.output(pin, False)
            await asyncio.sleep(off)

        self.gpio.output(pin, True)
        await asyncio.sleep(on)
        self.gpio.output(pin, False)
        await asyncio.sleep(off)

        return True

    def toggle_led(self, label: str = "", pin: int = 0, on: bool = None) -> bool:
        """Set an LED on (True), off (False), or toggled (None)."""
        if self._check_pin_use(label=label, pin=pin):
            if label:
                pin = self._get_pin_by_label(label)
            if pin:
                if on is None:
                    on = not self.gpio.input(pin)
                self.gpio.output(pin, on)
            return True
        return False

    def check_sw_input(self, label: str = "", pin: int = 0) -> bool:
        """Directly read a switch pin state. Kept for diagnostic use.

        In normal async operation, button events arrive via the queue populated
        by setup_gpio_events(), so this method is rarely needed at runtime.
        """
        if self._check_pin_use(label=label, pin=pin, pintype="sw"):
            if label:
                pin = self._get_pin_by_label(label)
            if pin:
                return bool(self.gpio.input(pin))

    def clear_leds(self) -> bool:
        for label, data in self.gpio.map["led"].items():
            self.toggle_led(label=label, on=data["init_state"])
        return True
