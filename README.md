

# Photobooth
This package contains a simple photobooth framework written in Python3.7. This repository should be considered a Proof of Concept.

Currently supports a RaspberryPi 4B controlling somenumber of NeoPixel (ws281x) panels/strips, Printers, Cameras, and status LEDs and switches connected to the GPIO.

![Raspberry Pi Circuit Diagram](./img/RPi-4B-circuit-diagram.png "Raspberry Pi 4B")

# Quickstart
```shell
sudo pip3 install -e git+https://github.com/namachieli/photobooth.git#egg=photobooth
sudo python3
```
```python
import photobooth
booth = photobooth.RPi()

booth.start_web()
booth.start_kiosk()

# Check for supported camera models:
# from photobooth.camera import supported_camera_list
# supported_camera_list()
# Or run "gphoto2 --list-cameras" in bash
camera = booth.add_camera(name="main", model="Canon EOS 1100D")

camera.capture()
booth.copy_to_last_shot(camera.last_shot())  # copy the last shot to a location Django can access.
booth.display_last_shot()
```

# Basic structure
- `photobooth.booth.Booth()` - Contains all logic that is not controller (raspberrypi) specific, and loads portable components (neopixel, printer, camera, etc) on demand.
  - `Booth().start_kiosk()` - Starts an xsession and runs the [kiosk](./photobooth/resources/kiosk.sh)
- `photobooth.booth.Thread()` - Provides a wrapper class for running any function/method as a thread asynchronously. Ex: `panel_test = booth.run_as_thread(np.panel_test, executions=1, start=True)`
- `photobooth.rpi.RPi()` - Contains all logic for the RaspberryPi Controller family.
- `photobooth.arduino.Arduino()` - (FUTURE)
- `photobooth.neopixelNeopixel()` - Contains generic logic spcific to just a ws281x compliant Neopixel component. (Portable)
  - `Booth().add_neopixel()` - initializes and sets up a NeoPixel object
- `photobooth.printer.Printer()` - Contains generic logic spcific to printers (Thermal, Photo, InkJet, etc). (Portable)
  - `Booth().add_printer()` - initializes and sets up a Printer object
- `photobooth.camera.Camera()` - Contains generic logic specific to Cameras. (Portable)
  - `Booth().add_camera()` - initializes and sets up a camera object
- `photobooth_web/` - A simple Django web environment for displaying resources.
  - `Booth().start_web()` - Starts the webserver as a thread in the background
  - `Booth().check_web()` - Provides status of the webserver (True/False)
  - `Booth().stop_web()` - Stops the webserver thread running in the background

New components, such as Printers, NeoPixel boards/strips, Cameras, etc can easily be added as a portable class defining how to use the component, and relevant logic in Booth() to init and add them.

Because controller logic ( RPi() ) doesn't care about components, and inherits 'Booth' level logic, new controllers can be easily added as needed (such as Arduino, or future RPi variants).

See [examples/booth_init.py](./examples/booth_init.py) for an example of how to use this library to run a photobooth using the reference circuit diagram, a Canon t7i (EOS 1100D), and a PBM-8350U Thermal Receipt Printer.

Functions/Methods are documented in more detail in [/photobooth/README.md](./photobooth/README.md)

# Contributions
I am open to Issues and PRs, but I make no garuntee for support, acceptance, or implementation/Bug Fixing.
