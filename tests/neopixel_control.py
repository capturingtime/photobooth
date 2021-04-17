# https://learn.adafruit.com/adafruit-neopixel-uberguide/python-circuitpython#python-installation-of-neopixel-library-17-9

import time
import neopixel


def wheel(np, pos):
    # Input a value 0 to 255 to get a color value.
    # The colours are a transition r - g - b - back to r.
    if pos < 0 or pos > 255:
        r = g = b = 0
    elif pos < 85:
        r = int(pos * 3)
        g = int(255 - pos * 3)
        b = 0
    elif pos < 170:
        pos -= 85
        r = int(255 - pos * 3)
        g = 0
        b = int(pos * 3)
    else:
        pos -= 170
        r = 0
        g = int(pos * 3)
        b = int(255 - pos * 3)
    return (r, g, b) if np.byteorder in (neopixel.RGB, neopixel.GRB) else (r, g, b, 0)


def rainbow(np, wait_ms=1, iterations=1):
    """Draw rainbow that fades across all pixels at once."""
    for j in range(255*iterations):
        for i in range(np.n):
            pixel_index = i + j
            np[i] = wheel(np, pixel_index & 255)
        np.show()
        time.sleep(wait_ms/1000.0)


def rainbow_cycle(np, wait_ms=1, iterations=1):
    """Draw rainbow that uniformly distributes itself across all pixels."""
    for j in range(255*iterations):
        for i in range(np.n):
            pixel_index = (i * 256 // np.n) + j
            np[i] = wheel(np, pixel_index & 255)
        np.show()
        time.sleep(wait_ms/1000.0)