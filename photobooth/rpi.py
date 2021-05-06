from photobooth.booth import Booth


import RPi.GPIO as GPIO
import time

#   (label, use, pin, io, init_state)
# if label=pin is passed as kwarg, it will be used as an override.
DEFAULT_PIN_MAP = [
    ("gpio_init", "led", 17, "out", False),
    ("net_local", "led", 27, "out", False),
    ("net_www", "led", 22, "out", False),
    ("camera_rdy", "led", 13, "out", False),
    ("print_rdy", "led", 19, "out", False),
    ("shutter_rdy", "led", 26, "out", False),
    ("printing", "led", 0, "out", False),
    ("print", "sw", 23, "in", None),
    ("last_shot", "sw", 24, "in", None),
    ("capture", "sw", 25, "in", None),
    ("pixel", "ctl", 18, "out", False)
]


class RPi(Booth):
    """ A Class to manage how a Raspberry Pi would be used in a booth.
        Currently built spcifically for a RPi 4B
        Could be extended to be model aware
    """
    # SBC Single Board Computer | MP Microprocessor | MCU Microcontroller
    compute_type = "SBC"
    family = "Raspberry Pi"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

        # Init Booth
        Booth.__init__(self)

        # init and setup GPIO
        self._init_gpio()

    def _init_gpio(self):
        """ Initialize the GPIO pins provided or use defaults
        """
        self.logger.info('Initializing GPIO')

        self.gpio = GPIO
        setattr(self.gpio, "init", False)
        setattr(self.gpio, "map", dict())
        setattr(self.gpio, "pins", dict())

        if not self.debug:
            self.gpio.setwarnings(False)

        self._configure_pins()

        mode = GPIO.BCM
        self.gpio.setmode(mode)

        for use in self.gpio.map.values():
            for label, values in use.items():
                pin = values['pin']
                io = values['io']
                state = values['init_state']

                if io == "in":
                    m = GPIO.IN
                elif io == "out":
                    m = GPIO.OUT
                else:
                    msg = f"Incorrect value for IO mode for {label} on pin: {pin}. "\
                          "Expecting one of ['in', 'out']"
                    self._reset_and_cleanup()
                    self.except_and_log(ex_msg=msg)

                self.gpio.setup(pin, m)

                if m == GPIO.OUT:
                    # Set default state for outputs
                    self.gpio.output(pin, state)

        self.gpio.init = True
        self.logger.info('Init Complete')

        # Illuminate the 'GPIO Init" LED'
        self.toggle_led(label="gpio_init", on=True)

    def _configure_pins(self):
        """ Handles setup of pins based on defaults and overrides passed in self.kwargs
        """
        # Set defaults
        for label, use, pin, io, init_state in DEFAULT_PIN_MAP:
            if not self.gpio.map.get(use, None):
                self.gpio.map[use] = dict()
            self.gpio.map[use][label] = {
                "pin": pin,
                "io": io,
                "init_state": init_state
            }
            self.gpio.pins[label] = pin

        # Override defaults from input
        for k, v in self.kwargs.items():
            for label, use, pin, io, init_state in DEFAULT_PIN_MAP:
                if k == label:
                    self.gpio.map[use][label]["pin"] = int(v)
                    self.gpio.pins[label] = int(v)
                    self.kwargs.pop(k, None)  # Remove from kwargs and throw away

        # check for duplicate/conflicting pins
        check = set(self.gpio.pins.values())
        if len(check) != len(self.gpio.pins):
            self._reset_and_cleanup()
            self.except_and_log(ex_msg=f"Duplicate pin configured: {self.gpio.pins}")

    def _reset_and_cleanup(self):
        """ Cleans up physical indicators and resets to basic state
        """
        self.gpio.init = False
        self._init_gpio()

        for led, values in self.gpio.map['led'].items():
            pin = values['pin']
            state = values['init_state']
            self.gpio.output(pin, state)

    def _get_pin_by_label(self, label: str = "") -> dict:
        """ Find the pin number based on the pin label
        """
        if not label:
            self.except_and_log(ex_msg="'label' is a required argument for _get_pin_by_label()")

        # Should only return 0 or 1 list items since label/k is unique
        pin = [v for k, v in self.gpio.pins.items() if label == k]
        if not pin:
            self.except_and_log(
                ex_msg=f"Unable to find a pin for {label} in gpio.pins: {self.gpio.pins}")
            return None
        return pin[0]

    def _check_pin_use(self, label: str = "", pin: int = 0, pintype: str = "led") -> bool:
        """ Check that the label or pin is the correct type (use) and return True/False
        """
        # Check that atleast one of [label, pin] is set to non defaults
        if not label and not pin:
            self.logger.warn("One of 'label' or 'pin' is required for _check_pin_use()")
            return None

        if label and pin:
            # Hard prefer label over pin when conflict
            pin = 0

        pins = self.gpio.map[pintype]

        if label and pins.get(label, None):
            return True
        elif pin:
            for label, values in pins.items():
                if pin == values["pin"]:
                    return True
        else:
            self.except_and_log(
                ex_msg=f'Pin: {pin} not found to be configured as {pintype} in {self.gpio.map}')
            return False  # Did not find a positive match for a {pintype}, assume False

    def blink_led(self, label: str = "", pin: int = 0, speed=1) -> bool:
        """ blink an led once per speed (n seconds)
        """
        if not self._check_pin_use(label=label, pin=pin):
            return False
        if label:
            # effectively an override of anything supplied in pin
            pin = self._get_pin_by_label(label)

        # max blinks = 10/sec
        speed = speed if speed >= 0.1 else 0.1
        on = speed * 0.25
        off = speed * 0.75

        # If LED is on, turn it off and pause for a moment
        if self.gpio.input(pin):
            self.gpio.output(pin, False)
            time.sleep(off)

        # Blink
        self.gpio.output(pin, True)
        time.sleep(on)
        self.gpio.output(pin, False)
        time.sleep(off)

        return True

    def toggle_led(self, label: str = "", pin: int = 0, on: bool = None):
        """ Toggle or set an LED to state
            On: on=True
            Off: on=False
            Toggle: on=None
        """
        if self._check_pin_use(label=label, pin=pin):
            if label:
                pin = self._get_pin_by_label(label)
            if pin:
                if on is None:
                    # Invert current LED state
                    on = not self.gpio.input(pin)
                self.gpio.output(pin, on)  # Set led to state
            return True
        else:
            return False

    def check_sw_input(self, label: str = "", pin: int = 0) -> bool:
        """ Checks the status of a button or switch, returns True/False accordingly
        """
        if self._check_pin_use(label=label, pin=pin, pintype="sw"):
            if label:
                pin = self._get_pin_by_label(label)
            if pin:
                return bool(self.gpio.input(pin))  # Set led to state

    def clear_leds(self):
        for label, data in self.gpio.map['led'].items():
            self.toggle_led(label=label, on=data['init_state'])

        return True
