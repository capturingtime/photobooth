"""
Photobooth shutdown helper — clears LEDs and neopixel panel.
Console entry point: ``photobooth-clear``. Invoked from booth.service ExecStopPost.
"""

import board

from photobooth import RPi


def main() -> None:
    booth = RPi()
    panel = booth.add_neopixel(name="main", control=board.D18)
    panel.clear()
    booth.clear_components()
    booth.clear_leds()


if __name__ == "__main__":
    main()
