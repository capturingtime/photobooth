import board
import neopixel
import time
import os

from random import randint
from PIL import Image, ImageDraw, ImageFont

ABSPATH = os.path.dirname(__file__)
RESOURCES = os.path.join(ABSPATH, 'resources')

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
PURPLE = (255, 0, 255)
CYAN = (0, 255, 255)
ORANGE = (255, 128, 0)
PINK = (255, 0, 128)
WHITE = (255, 255, 255)
OFF = (0, 0, 0)  # Not included in color lists

COLOR_LIST = ["RED", "GREEN", "BLUE", "YELLOW", "PURPLE", "CYAN", "ORANGE", "PINK", "WHITE"]
COLOR_TUPLE_LIST = [RED, GREEN, BLUE, YELLOW, PURPLE, CYAN, ORANGE, PINK, WHITE]

# The default brightness percent as a float (0.1 = 10%)
DEFAULT_BRIGHTNESS = 0.1

DEAFULT_ORDER = neopixel.GRB
DEAFULT_PIN = board.D18

DEFAULT_SPEED = 0.01


def wheel(np, pos):
    """ Input a value 0 to 255 to get a color value.
        The colours are a transition r - g - b - back to r.
        Source: Adafruit tutorials
    """
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


def getIndex(x, y, rows, cols):
    """ This function, given a relative (x, y) coordinate, will return the corresponding pixel index
        Example: 8x32 grid
        Example:  0, 0 = 248 (top left pixel)
                  0, 7 = 255 (bottom left pixel)
                 31, 7 = 0   (bottom right pixel)
                 31, 0 = 7   (top right pixel)

        NeoPixel Panels use a snake like numbering for the pixel index

        248--247  xxx--007
         |    |    |    |
         |    |    |    |
         |    |    |    |
         |    |    |    |
         |    |    |    |
         |    |    |    |
        255  240--xxx  000
    """
    x = cols-x-1
    if x % 2 != 0:
        return (x*rows)+y
    else:
        return (x*rows)+(rows-1-y)


def valid_color_tuple(rgb_tuple, fix=False) -> (bool, tuple):
    """ Check that color values are int and less than 256
        Returns True/False, and either the original tuple, or a fixed one
    """
    if not isinstance(rgb_tuple, tuple):
        raise ValueError("valid_color_tuple(rgb_tuple) must be type(tuple)")

    elif len(rgb_tuple) < 3 or len(rgb_tuple) > 4:
        raise ValueError(
            "valid_color_tuple(rgb_tuple) should contain values for (R,G,B, or R,G,B,A)")

    valid = True
    rgb_list = list(rgb_tuple)
    for i in range(len(rgb_list)):
        c = rgb_list[i]
        if not isinstance(c, int):
            raise ValueError(f"A non-int value was passed as a color value. Received: {c}")
        if c > 255 or c < 0:
            valid = False
            if fix:
                rgb_list[i] = 255 if c > 255 else 0

    if valid:
        return True, tuple(rgb_list)
    else:
        return False, tuple(rgb_list)


class Neopixel():
    """ Loads a 'neopixel' for use.
        Neopixel is typically a 5050 pixel (RGB)
        controlled by the common ws281x library.
    """
    def __init__(self,
                 name: str = None,
                 control=DEAFULT_PIN,
                 rows: int = 8,
                 cols: int = 32,
                 brightness: float = DEFAULT_BRIGHTNESS,
                 pixel_order: str = DEAFULT_ORDER,
                 auto_write=False,
                 **kwargs):

        if not name:
            # Forces a unique name
            name = f"neopixel-{id(self)}"

        if not control:
            control = DEAFULT_PIN

        self.name = name
        self.rows = rows
        self.cols = cols
        self.inputs = locals()
        self.num_px = rows * cols

        # board_pin = getattr(board, f"D{pin}")

        # Init
        self.np = neopixel.NeoPixel(
            control, self.num_px, brightness=brightness, pixel_order=pixel_order,
            auto_write=auto_write, **kwargs)

        # TODO: Add logic that verifies the panel is working

    def rainbow_cycle(self, wait_ms=1, iterations=1):
        """ Draw rainbow that uniformly distributes itself across all pixels.
            Source: Adafruit tutorials
        """
        for j in range(255*iterations):
            for i in range(self.np.n):
                pixel_index = (i * 256 // self.np.n) + j
                self.np[i] = wheel(self.np, pixel_index & 255)
            self.np.show()
            time.sleep(wait_ms/1000.0)

        return True

    def color_chase(self, color: tuple = CYAN, wait: float = DEFAULT_SPEED):
        """ Snake-like color chase from index 0 to -1
            Source: Adafruit tutorials
        """
        for i in range(self.np.n):
            self.np[i] = color
            time.sleep(wait)
            self.np.show()
        return True

    def twinkle(self, wait: float = DEFAULT_SPEED, count: int = 10):
        """ Randomly selects a pixel, and flashes it with a random color
            Source: Adafruit tutorials
        """
        last = None
        for _ in range(count):
            c = randint(0, len(COLOR_TUPLE_LIST) - 1)  # Choose random color index
            j = randint(0, self.np.n - 1)  # Choose random pixel

            # Check that the pixel is off (different pixel)
            while self.np[j] == last:
                j = randint(0, self.np.n - 1)  # Choose a different random pixel
            last = j
            self.np[j] = COLOR_TUPLE_LIST[c]  # Set pixel to color
            self.np.show()
            # Ramp up brightness
            for i in range(1, 5):
                self.np.brightness = i / 5.0
                self.np.show()
                time.sleep(wait)

            # Ramp down brightness
            for i in range(5, 0, -1):
                self.np.brightness = i / 5.0
                self.np[j] = OFF
                self.np.show()
                time.sleep(wait)

    # TODO: Is reducing the current color of each pixel slowly to 0 a smoother execution?
    def fade_out(self, duration: int = 1):
        """ Fades out to OFF over the duration
        """
        original_brightness = self.np.brightness

        step_level = 0.01
        sleep_cycle = duration / (original_brightness / step_level)

        while self.np.brightness > 0:
            # FIXME :
            # Im not totally sure why, but...
            # self.np.brightness -= step_level
            # causes self.np.brightness of 0.1 to become 0.09000000000000001
            # and i dont feel like figuring out why right now
            self.np.brightness = round(self.np.brightness - step_level, 2)
            self.np.show()
            time.sleep(sleep_cycle)

        self.np.fill(OFF)
        self.np.show()

        # Reset brightness to original value now that pixels are OFF
        self.np.brightness = original_brightness

        return True

    def draw_text(self, text: str, x_offset: int = 0,
                  font_name: str = "Apple_II_mod.ttf", font_pt: int = 8) -> Image.Image:
        """ Using PIL, draw text into an image to be scrolled
        """
        if self.rows < 5:
            raise ValueError(
                f"Unable to scroll text on a board with rows < 5 px. Board Rows: {self.rows} ")

        text = str(text)

        if not font_name.endswith('.ttf'):
            font_name = f'{font_name}.ttf'

        if not os.path.exists(f"{RESOURCES}/{font_name}"):
            raise ValueError(
                f"The font: '{font_name}' could not be found, please try a font in ./resources")

        font = ImageFont.truetype(f"{RESOURCES}/{font_name}", font_pt)
        text_width, text_height = font.getsize(text)

        # FIXME :
        # For some reason we need to remove 1 px from the image width
        # for it to clear smoothly at the end
        # Instead of messing with the math, a workaround of clearing the panel
        # after the scroll was added
        image = Image.new('P', (text_width + (self.cols * 2), self.rows), 0)
        draw = ImageDraw.Draw(image)

        draw.text((self.cols, x_offset), text, font=font, fill=255)

        return image

    def scroll(self, text,
               speed: float = DEFAULT_SPEED,
               count=1,
               offset_x: int = 0,
               color: tuple((int, int, int)) = WHITE):
        """ Scroll the input across the board
        """

        rows = self.rows
        cols = self.cols

        # Check if text is not a PIL.Image.Image object
        if not isinstance(text, Image.Image):
            text = self.draw_text(text)

        if not isinstance(speed, float):
            raise ValueError(
                f"Neopixel().scroll(speed) must be a float. Received: {speed} ({type(speed)})")

        if speed > 1:
            raise ValueError(
                f"Neopixel().scroll(speed) must be less than 1.0. Received: {speed}")

        # FIXME: Better way to do this part
        # Reconstruct the original text width from
        # image = Image.new('P', (text_width + (self.cols * 2) - 1, self.rows), 0)
        # in self.draw_text()
        text_width = text.width - (self.cols * 2)

        valid, color = valid_color_tuple(color, fix=True)

        # TODO: All this math should be revisited
        for n in range(count):
            i = text_width + cols
            while i > 0:
                for x in range(cols):
                    for y in range(rows):
                        if text.getpixel((x + offset_x, y)) == 255:
                            self.np[getIndex(x, y, rows, cols)] = color
                        else:
                            self.np[getIndex(x, y, rows, cols)] = (0, 0, 0)
                offset_x += 1
                if offset_x + cols > text.size[0]:
                    offset_x = 0
                self.np.show()
                time.sleep(speed)  # scrolling text speed
                i -= 1
        self.clear()  # Sometimes the last few px are visible, this just clears it off.
        return True

    # TODO :
    def flash(self, **kwargs):
        """ Flash the input on the board n times
            width is limited by width of panel
        """
        self.scroll(**kwargs)  # Temporary, will be replaced

    # TODO :
    def cycle_text(self, **kwargs):
        """ given a list of strings, alternate randomly through them
            using scroll, flash, etc.
        """
        self.scroll(**kwargs)  # Temporary, will be replaced

    def clear(self):
        """ clear the panel and set all pixels to OFF
        """
        self.np.fill(OFF)
        self.np.show()
        return True

    def fill(self, color=WHITE):
        """ Fill the panel to a specific color
            Accepts the following:
            the color list in COLOR_LIST
            tuple(int(r_val), int(g_val), int(b_val))
            int(rgb_val)
        """
        # Error checking and data munging to resolve the 'color' input
        if isinstance(color, str):
            if color.upper() in COLOR_LIST:
                color = globals()[color.upper()]
            else:
                raise ValueError(
                    f"The color name: {color} is not supported. "
                    f"Please use one of {COLOR_LIST}")
        elif isinstance(color, tuple):
            valid = valid_color_tuple(color)
            if not valid:
                raise ValueError(f"A non RGB color tuple was provided: {color}")
        elif isinstance(color, int):
            if color > 255 or color < 0:
                raise ValueError(f"A value of '{color}' for color cannot be used for RGB, "
                                 "please use a number in the range 0-255")
            else:
                color = (color, color, color)
        self.np.fill(color)
        self.np.show()
        return True

    def panel_test(self, extended=False):
        """ Runs a panel test by cycling some various logic
        """

        self.scroll(text="Panel test in progress...", speed=0.001)
        time.sleep(0.25)
        if extended:
            self.scroll(text="ABCDEFGHIJKLMNOPQRSTUVQXYZ", color=RED, speed=0.001)
            time.sleep(0.25)
            self.scroll(text="abcdefghijklmnopqrstuvwxyz", color=GREEN, speed=0.001)
            time.sleep(0.25)
            self.scroll(text="1234567890!@#$%^&*(){}[]:;\"'~`+-\\/=_,.<>", color=BLUE, speed=0.001)
            time.sleep(0.25)
        for color in COLOR_LIST:
            self.fill(color)
            time.sleep(.2)
        self.rainbow_cycle(iterations=1)
        self.fade_out(duration=1)
