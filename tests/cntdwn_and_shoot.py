from seven_seg_control import init_gpio, reset_7seg
from shutter_control import check_output_dir, shutter_countdown


import RPi.GPIO as GPIO
import time
from datetime import datetime
import subprocess

OUTPUT_DIR = "/home/pi/booth_images"
PHOTO_PREFIX = "photobooth_"
shutter_btn_pin = 24
countdown_led_pin = 22


check_output_dir()

init_gpio()

GPIO.setup(shutter_btn_pin, GPIO.IN)
GPIO.setup(countdown_led_pin, GPIO.OUT)

while True:
    if GPIO.input(shutter_btn_pin):
        shutter_countdown()

        current_stamp = datetime.now().strftime("%Y%m%d-%Hh%Mm%Ss")
        filename = f"{OUTPUT_DIR}/{PHOTO_PREFIX}{current_stamp}.jpg"

        subprocess.check_output(
            f"gphoto2 --capture-image-and-download --filename {filename}",
            stderr=subprocess.STDOUT, shell=True)

        reset_7seg()

        subprocess.run(f"gpicview {filename} &", stderr=subprocess.STDOUT, shell=True)

    time.sleep(.05)
