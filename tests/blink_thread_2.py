import threading
import time
import RPi.GPIO as GPIO


def blink(gpio, pin):
    gpio.output(pin, True)
    time.sleep(0.25)
    gpio.output(pin, False)
    time.sleep(0.75)


class Thread(threading.Thread):
    def __init__(self, target, *args, **kwargs):
        threading.Thread.__init__(self)
        self._target = target
        self._args = args
        self._kwargs = kwargs
        self._stop_event = threading.Event()
    def stop(self, *args, **kwargs):
        self._stop_event.set()
        super(Thread, self).join(*args, **kwargs)
        return True
    def run(self):
        while not self._stop_event.is_set():
            self._target(*self._args, **self._kwargs)


led = 26
mode = GPIO.BCM
g = GPIO
g.setmode(mode)
g.setup(led, GPIO.OUT)

t = Thread(blink, g, led)
t.start()

time.sleep(5)

t.stop()
