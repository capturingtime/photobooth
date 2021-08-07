"""
This example assumes you have connected your Raspberry Pi 4 according to the diagram in the readme
"""

import board
import time

from photobooth import RPi

booth = RPi()

print("starting webserver")
booth.start_web()  # stored in booth.web_server

# Wait until webserver is started
while not booth.check_web():
    time.sleep(0.05)
print("Webserver started")
print("starting kiosk")
booth.start_kiosk()  # Stored in booth.kiosk

print("setting up components and running checks")
booth.reset_last_shot()

# Setup panel and run a panel test as a thread (so we don't have to wait for it to finish)
panel = booth.add_neopixel(name="main", control=board.D18)
panel_test = booth.run_as_thread(panel.panel_test, executions=1, start=True)

# Check network
if booth.net_check_local():
    booth.toggle_led(label="net_local", on=True)

if booth.net_check_www():
    booth.toggle_led(label="net_www", on=True)

# Setup Camera and toggle LED
camera = booth.add_camera(name="main", model="Canon EOS 1100D")
booth.toggle_led(label="camera_rdy", on=True)

# Setup Printer and toggle LED
printer = booth.add_printer(name="receipt", model="PBM-8350U")
booth.toggle_led(label="print_rdy", on=True)

# Wait for panel test to finish
while panel_test.is_alive():
    time.sleep(0.05)

print("Booth is online and ready")
# Booth is ready
booth.toggle_led(label="shutter_rdy", on=True)

attract = booth.run_as_thread(panel.scroll, start=True, speed=0.01,
                              text="Press the capture button to begin!  ",)

# Run Booth
while True:
    time.sleep(0.05)  # if you dont have a short sleep, your CPU will catch fire. /s

    if booth.check_sw_input("capture"):
        print("Capture button was pressed")
        attract.stop_immediately()
        panel.scroll(text="3...")
        panel.scroll(text="2...")
        panel.scroll(text="1...")
        panel.flash(text="Smile! :D")
        capture = booth.run_as_thread(target=camera.capture, executions=1, start=True)
        wait = booth.run_as_thread(target=panel.twinkle, start=True, count=20)
        while capture.is_alive():
            time.sleep(0.01)
        wait.stop_immediately()
        panel.scroll(text="AWESOME!")
        booth.copy_to_last_shot(camera.last_shot())
        attract.restart()
        booth.display_last_shot()
    elif booth.check_sw_input("print"):
        print("Print button was pressed")
        now = time.time()
        # Check if we had a recent print
        try:
            delta = int(now - last_print)  # noqa: F821
        except Exception:
            # There probably wasn't a last_print, so go ahead
            pass
        else:
            # Only print if we haven't in the last 3 seconds (successive pushes)
            if delta <= 3:
                continue  # don't print
        booth.run_as_thread(panel.flash, text="Printing...", executions=1, start=True)
        while not camera.is_ready():
            time.sleep(0.01)  # wait for camera to be ready after the shot.
        printer.text(text=camera.last_shot())
        printer.ln()
        printer.qr(content="https://website.com", size=10)  # Could be where the photo was uploaded
        printer.ln()
        printer.text(text="Thank you for using our photobooth! "
                          "Please visit us at http://website.net")
        printer.cut()
        last_print = time.time()
