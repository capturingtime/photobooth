import time
import board
import neopixel

from PIL import Image, ImageDraw, ImageFont

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
OFF = (0, 0, 0)

text = "Testing Aa Gg Ii Jj Qq Kk"
pixel_pin = board.D18
display_width = 32
display_height = 8
num_pixels = int(display_width * display_height)
brightness = 0.05
scrollSpeed = 0.12

ORDER = neopixel.GRB
np = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=brightness, auto_write=False, pixel_order=ORDER)  # noqa: E501


def getIndex(x, y):
    """ This function, given a relative (x, y) coordinate, will return the corresponding pixel index
        Example:  0, 0 = 248 (top left pixel)
                  0, 7 = 255 (bottom left pixel)
                 31, 7 = 0   (bottom right pixel)
                 31, 0 = 7   (top right pixel)

        NeoPixel Panels use a snake like numbering for the pixel index
        Example 8x32 grid
        248--247  xxx--007
         |    |    |    |
         |    |    |    |
         |    |    |    |
         |    |    |    |
         |    |    |    |
         |    |    |    |
        255  240--xxx  000
    """
    x = display_width-x-1
    if x % 2 != 0:
        return (x*8)+y
    else:
        return (x*8)+(7-y)


font = ImageFont.truetype("5x7.ttf", 8)
text_width, text_height = font.getsize(text)
# image = Image.new('P', (text_width + display_width + display_width, display_height), 0)

# For some reason we need to remove 1 px from the image width for it to clear smoothly at the end
image = Image.new('P', (text_width + (display_width * 2) - 1, display_height), 0)
draw = ImageDraw.Draw(image)

# .text(x_offset, y_offset)
# y_offset = -1 (Top pixel top row, bottom pixel second from bottom row)
# y_offset = 0 (Top pixel second from top row, bottom pixel bottom row) * Looks better at 8pt font
draw.text((display_width, 0), text, font=font, fill=255)


def scroll(color=WHITE, count=1, speed=scrollSpeed):
    offset_x = 0
    # end_of_text = False
    # All this math should be revisited
    for n in range(count):
        i = text_width + display_width
        while i > 0:
            for x in range(display_width):
                for y in range(display_height):
                    if image.getpixel((x + offset_x, y)) == 255:
                        np[getIndex(x, y)] = color
                    else:
                        np[getIndex(x, y)] = (0, 0, 0)
            offset_x += 1
            if offset_x + display_width > image.size[0]:
                offset_x = 0
            np.show()
            time.sleep(speed)  # scrolling text speed
            i -= 1
            # if i == 0 and not end_of_text:
            #     end_of_text = True
            #     i = display_width
    # np.fill(OFF)
    # np.show()

scroll()
