import asyncio
import os

from random import randint
from PIL import Image, ImageDraw, ImageFont

import board
import neopixel

ABSPATH = os.path.dirname(__file__)
RESOURCES = os.path.join(ABSPATH, "resources")

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
PURPLE = (255, 0, 255)
CYAN = (0, 255, 255)
ORANGE = (255, 128, 0)
PINK = (255, 0, 128)
WHITE = (255, 255, 255)
OFF = (0, 0, 0)

COLOR_LIST = ["RED", "GREEN", "BLUE", "YELLOW", "PURPLE", "CYAN", "ORANGE", "PINK", "WHITE"]
COLOR_TUPLE_LIST = [RED, GREEN, BLUE, YELLOW, PURPLE, CYAN, ORANGE, PINK, WHITE]

DEFAULT_BRIGHTNESS = 0.1
DEAFULT_ORDER = neopixel.GRB
DEAFULT_PIN = board.D18
DEFAULT_SPEED = 0.005


def wheel(np, pos):
    """Map 0-255 position to an RGB rainbow color. Source: Adafruit tutorials."""
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
    """Map (x, y) grid coordinate to NeoPixel snake-wired index.

    NeoPixel panels use a serpentine (snake) wiring pattern. Column direction
    alternates even/odd so this function inverts the y-axis on even columns.
    """
    x = cols - x - 1
    if x % 2 != 0:
        return (x * rows) + y
    else:
        return (x * rows) + (rows - 1 - y)


def valid_color_tuple(rgb_tuple, fix=False) -> tuple:
    """Validate that an RGB tuple contains three ints in [0, 255].

    Returns (valid: bool, tuple). When fix=True, clamps out-of-range values.
    """
    if not isinstance(rgb_tuple, tuple):
        raise ValueError("valid_color_tuple(rgb_tuple) must be type(tuple)")
    if len(rgb_tuple) < 3 or len(rgb_tuple) > 4:
        raise ValueError("valid_color_tuple(rgb_tuple) should contain (R,G,B) or (R,G,B,A)")

    valid = True
    rgb_list = list(rgb_tuple)
    for i, c in enumerate(rgb_list):
        if not isinstance(c, int):
            raise ValueError(f"Non-int color value: {c}")
        if c > 255 or c < 0:
            valid = False
            if fix:
                rgb_list[i] = 255 if c > 255 else 0

    return valid, tuple(rgb_list)


class Neopixel:
    """Controls a ws281x NeoPixel LED panel.

    All animation methods are async coroutines — they yield control via
    await asyncio.sleep() between frames so the event loop stays responsive.
    Cancel an animation task with task.cancel() to stop it immediately.

    np.show() writes to hardware synchronously but is fast (<1 ms); it is
    called directly rather than offloaded to run_in_executor.
    """

    def __init__(
        self,
        name: str = None,
        control=DEAFULT_PIN,
        rows: int = 8,
        cols: int = 32,
        brightness: float = DEFAULT_BRIGHTNESS,
        pixel_order: str = DEAFULT_ORDER,
        auto_write: bool = False,
        **kwargs,
    ):
        if not name:
            name = f"neopixel-{id(self)}"
        if not control:
            control = DEAFULT_PIN

        self.name = name
        self.rows = rows
        self.cols = cols
        self.num_px = rows * cols

        self.np = neopixel.NeoPixel(
            control,
            self.num_px,
            brightness=brightness,
            pixel_order=pixel_order,
            auto_write=auto_write,
            **kwargs,
        )

    async def rainbow_cycle(self, wait_ms: float = 1, iterations: int = 1) -> bool:
        """Animate a rainbow that distributes uniformly across all pixels.

        Runs for the given number of iterations and returns. Source: Adafruit tutorials.
        """
        for j in range(255 * iterations):
            for i in range(self.np.n):
                pixel_index = (i * 256 // self.np.n) + j
                self.np[i] = wheel(self.np, pixel_index & 255)
            self.np.show()
            await asyncio.sleep(wait_ms / 1000.0)
        return True

    async def color_chase(self, color: tuple = CYAN, wait: float = DEFAULT_SPEED) -> bool:
        """Snake a single color from pixel 0 to the last pixel. Source: Adafruit tutorials."""
        for i in range(self.np.n):
            self.np[i] = color
            self.np.show()
            await asyncio.sleep(wait)
        return True

    async def twinkle(self, wait: float = DEFAULT_SPEED, count: int = 10):
        """Flash random pixels with random colors. Source: Adafruit tutorials."""
        last = None
        for _ in range(count):
            c = randint(0, len(COLOR_TUPLE_LIST) - 1)
            j = randint(0, self.np.n - 1)
            while self.np[j] == last:
                j = randint(0, self.np.n - 1)
            last = j
            self.np[j] = COLOR_TUPLE_LIST[c]
            self.np.show()
            for i in range(1, 5):
                self.np.brightness = i / 5.0
                self.np.show()
                await asyncio.sleep(wait)
            for i in range(5, 0, -1):
                self.np.brightness = i / 5.0
                self.np[j] = OFF
                self.np.show()
                await asyncio.sleep(wait)

    async def fade_out(self, duration: int = 1) -> bool:
        """Gradually reduce brightness to zero over duration seconds."""
        original_brightness = self.np.brightness
        step_level = 0.01
        # Sleep per step chosen so the full fade takes ~duration seconds
        sleep_cycle = duration / (original_brightness / step_level)

        while self.np.brightness > 0:
            # round() avoids floating-point drift (e.g. 0.1 - 0.01 = 0.09000000000000001)
            self.np.brightness = round(self.np.brightness - step_level, 2)
            self.np.show()
            await asyncio.sleep(sleep_cycle)

        self.np.fill(OFF)
        self.np.show()
        self.np.brightness = original_brightness
        return True

    def draw_text(
        self, text: str, x_offset: int = 0, font_name: str = "Apple_II_mod.ttf", font_pt: int = 8
    ) -> Image.Image:
        """Render text into a PIL Image sized for the panel (used by scroll)."""
        if self.rows < 5:
            raise ValueError(
                f"Cannot scroll on a board with rows < 5. Board rows: {self.rows}"
            )
        text = str(text)
        if not font_name.endswith(".ttf"):
            font_name = f"{font_name}.ttf"
        if not os.path.exists(f"{RESOURCES}/{font_name}"):
            raise ValueError(
                f"Font '{font_name}' not found. Place it in ./resources"
            )
        font = ImageFont.truetype(f"{RESOURCES}/{font_name}", font_pt)
        text_width, _ = font.getsize(text)
        # cols*2 padding on each side allows text to fully scroll on and off the panel
        image = Image.new("P", (text_width + (self.cols * 2), self.rows), 0)
        draw = ImageDraw.Draw(image)
        draw.text((self.cols, x_offset), text, font=font, fill=255)
        return image

    async def scroll(
        self,
        text,
        speed: float = DEFAULT_SPEED,
        count: int = 1,
        offset_x: int = 0,
        color: tuple = WHITE,
    ) -> bool:
        """Scroll text (or a pre-rendered PIL Image) across the panel."""
        rows = self.rows
        cols = self.cols

        if not isinstance(text, Image.Image):
            text = self.draw_text(text)

        if not isinstance(speed, float):
            raise ValueError(f"scroll(speed) must be a float. Got: {speed} ({type(speed)})")
        if speed > 1:
            raise ValueError(f"scroll(speed) must be < 1.0. Got: {speed}")

        text_width = text.width - (self.cols * 2)
        _, color = valid_color_tuple(color, fix=True)

        for _ in range(count):
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
                await asyncio.sleep(speed)
                i -= 1
        self.clear()
        return True

    async def scroll_for_duration(
        self,
        text,
        duration_s: float,
        color: tuple = WHITE,
        offset_x: int = 0,
    ) -> bool:
        """Scroll text once so the full pass takes ~duration_s seconds.

        Derives per-frame ``speed`` from the rendered text width so the caller
        specifies the target wall-clock duration rather than tuning ms-per-frame
        for each label. Pre-renders the image once and passes it to ``scroll``
        to avoid a second draw_text() pass.
        """
        if not isinstance(text, Image.Image):
            text = self.draw_text(text)
        # Frame count matches scroll()'s inner loop: text_width + cols where
        # text_width = image.width - (cols * 2). Simplifies to image.width - cols.
        frames = text.width - self.cols
        speed = duration_s / frames if frames > 0 else DEFAULT_SPEED
        return await self.scroll(
            text=text, speed=speed, count=1, offset_x=offset_x, color=color
        )

    async def flash(self, **kwargs):
        """Flash text on the panel (placeholder — delegates to scroll)."""
        await self.scroll(**kwargs)

    async def cycle_text(self, **kwargs):
        """Cycle through text on the panel (placeholder — delegates to scroll)."""
        await self.scroll(**kwargs)

    def clear(self) -> bool:
        """Set all pixels to OFF immediately."""
        self.np.fill(OFF)
        self.np.show()
        return True

    def fill(self, color=WHITE) -> bool:
        """Fill the panel with a solid color."""
        if isinstance(color, str):
            if color.upper() in COLOR_LIST:
                color = globals()[color.upper()]
            else:
                raise ValueError(f"Color '{color}' not supported. Use one of {COLOR_LIST}")
        elif isinstance(color, tuple):
            valid, color = valid_color_tuple(color)
        elif isinstance(color, int):
            if not 0 <= color <= 255:
                raise ValueError(f"Int color {color} must be in range 0-255")
            color = (color, color, color)
        self.np.fill(color)
        self.np.show()
        return True

    async def panel_test(self, extended: bool = False) -> None:
        """Run a sequence of animations to verify the panel is working."""
        await self.scroll(text="Panel test in progress...", speed=0.001)
        await asyncio.sleep(0.25)
        if extended:
            await self.scroll(text="ABCDEFGHIJKLMNOPQRSTUVQXYZ", color=RED, speed=0.001)
            await asyncio.sleep(0.25)
            await self.scroll(text="abcdefghijklmnopqrstuvwxyz", color=GREEN, speed=0.001)
            await asyncio.sleep(0.25)
            await self.scroll(
                text="1234567890!@#$%^&*(){}[]:;\"'~`+-\\/=_,.<>", color=BLUE, speed=0.001
            )
            await asyncio.sleep(0.25)
        for color in COLOR_LIST:
            self.fill(color)
            await asyncio.sleep(0.2)
        await self.rainbow_cycle(iterations=1)
        await self.fade_out(duration=1)
