import threading
import time
import RPi.GPIO as GPIO


class Thread(threading.Thread):
    def __init__(self, gpio, pin):
        self.pin = pin
        self.gpio = gpio

        super(Thread, self).__init__()
        self._stop_event = threading.Event()

    def stop(self, *args, **kwargs):
        self._stop_event.set()
        super(Thread, self).join(*args, **kwargs)

    def run(self):
        while not self._stop_event.is_set():
            self.gpio.output(self.pin, True)
            time.sleep(0.25)
            self.gpio.output(self.pin, False)
            time.sleep(0.75)
        print("Stopped")


led = 26
mode = GPIO.BCM
g = GPIO
g.setmode(mode)
g.setup(led, GPIO.OUT)

blink = Thread(g, 26)
blink.start()
time.sleep(5)
blink.stop()
