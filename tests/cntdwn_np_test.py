import time
import board
import neopixel
import RPi.GPIO as GPIO

from seven_seg_control import init_gpio, reset_7seg
from neopixel_control import rainbow_cycle
from shutter_control import shutter_countdown

shutter_btn_pin = 24
countdown_led_pin = 22

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
OFF = (0, 0, 0)

np = neopixel.NeoPixel(board.D18, 256, brightness=0.25, auto_write=True)

init_gpio()

GPIO.setup(shutter_btn_pin, GPIO.IN)
GPIO.setup(countdown_led_pin, GPIO.OUT)

while True:
    if GPIO.input(shutter_btn_pin):
        shutter_countdown(3)

        reset_7seg()

        for c in [RED, GREEN, BLUE]:
            np.fill(c)
            np.show()
            time.sleep(1)

        rainbow_cycle(np)

        np.fill(OFF)
        np.show()

    time.sleep(.05)
