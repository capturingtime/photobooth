import sys
import os
import RPi.GPIO as GPIO
import time
from seven_seg_control import set_digit

COUNTDOWN = 3
OUTPUT_DIR = "/home/pi/booth_images"
PHOTO_PREFIX = "photobooth_"
shutter_btn_pin = 24
countdown_led_pin = 22


def check_output_dir():
    """ Checks that the output directory exists and is writable
    """

    if not os.path.exists(OUTPUT_DIR):
        os.mkdir(OUTPUT_DIR)
    elif not os.path.isdir(OUTPUT_DIR):
        sys.exit(f'The spcified output directory ({OUTPUT_DIR}) exists but is not a directory')
    else:
        try:
            open(OUTPUT_DIR, 'w')
        except IOError:
            sys.exit(f'Output directory ({OUTPUT_DIR}) exists and is not writable')


def shutter_countdown(seconds: int = COUNTDOWN):
    i = COUNTDOWN
    while i > 0:
        result = set_digit(i)
        if not result:
            print('Something went wrong when setting the 7seg')
        GPIO.output(countdown_led_pin, True)
        time.sleep(.25)
        GPIO.output(countdown_led_pin, False)
        time.sleep(.75)
        i -= 1
    set_digit(0)
