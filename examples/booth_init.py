import board
import time

from photobooth import RPi
# https://pypi.org/project/pyzenfolio/


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

# FIXME: Network may not be ready after reboot. Race Condition. Maybe make this a thread?
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

# probably needs to be multiprocessing
attract = booth.run_as_thread(panel.scroll, start=True, speed=0.01,
                              text="Press the big blue button to begin!  ",)

# Run Booth
while True:
    # TODO: Make each "if" a function to make this loop less unruly as it grows.
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
        camera.copy_last_shot_to_dir(dir='/opt/booth_images')
        last_shot_ts = time.time()
    elif booth.check_sw_input("print"):
        print("Print button was pressed")
        # TODO: Add intelligence to prevent infinite printing (kids like buttons)
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
        printer.qr(content="https://google.com", size=10)
        printer.ln()
        printer.text(text="Thank you for using our photobooth! "
                          "Please visit us at http://website.net")
        printer.cut()
        last_print = time.time()
    elif booth.check_sw_input("last_shot"):
        print("Last Shot button pressed")
        now = time.time()

        # check if button pressed in last 5 seconds
        # FIXME: Clunky since this timer should match/exceed the redirect in last.html
        try:
            delta = int(now - last_show)  # noqa: F821
        except Exception:
            # There probably wasn't any 'last' shown, so do nothing
            pass
        else:
            # If its been less than (seconds) then its still displaying it, so just ignore
            if delta <= 5:
                continue

        # Check if we had a shot in the last 3 minutes
        try:
            delta = int(now - last_shot_ts)  # noqa: F821
        except Exception:
            # There probably wasn't a shot taken yet, so do nothing
            continue
        else:
            # If its been more than (seconds), reset the last shot because its probably not theirs
            if delta >= 180:
                booth.reset_last_shot()

        booth.display_last_shot()
        last_show = time.time()
    # elif booth.check_sw_input("reset"):
    # TODO: Add a reset Button
    # elif booth.check_sw_input("show_help"):
    # TODO: Add a show_help Button
