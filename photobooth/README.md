
# booth.py
### connect()
Attempt to connect to an HTTP host and check availability
##### Arguments
`host [str]` - The host to connect to. Default: `http://google.com`
##### Return `boolean`

### arp_list()
Gets a list of hosts responding to arp
##### Arguments
- `broadcast_ip [str]` - The broadcast IP to use. Default: `255.255.255.255`
##### Return `list[dictionary]`
A list of dictionaries containing data for each found host

### run_local_cmd()
Run a bash command as the current Python user, probably root (because ws281x)
##### Arguments `None`
##### Return `string`
stdout of the command ran.

## Booth()
Contains all methods necessary to operate the photobooth

### except_and_log()
Raises an exception based on the type provided in ex_type, and logs to file. If 'log' provided, this string will be added after the log header, before the exception
##### Arguments
- `ex_type [type(exception)]` - The type of exception to raise. Default: `ValueError`
- `ex_msg [str]` - Exception message to raise.
- `log [str]` - Log message to precede exception text.
##### Return `None`

### start_web()
Start the Django web server
##### Arguments `None`
##### Return `object`

### start_kiosk()
Starts an xsession and runs the kiosk.sh script to load the browser that will display output to users
##### Arguments
##### Return `object`

### copy_to_last_shot()
Copy the local file provided to the location that Django looks for to load with last.html
##### Arguments
- `last_shot [str]` - the source image that should be copied to `photobooth_web/mainscreen/static/img/last.jpg`. Can be overridden at `Booth()._last_shot_tgt`
##### Return `True`

### display_last_shot()
Intended to be ran after `start_kiosk()`. Loads a chromium tab that displays last.html from Django
##### Arguments `None`
##### Return `True`

### reset_last_shot()
Used to reset last.jpg to a placeholder
##### Arguments `None`
##### Return `True`

### add_printer()
Initialize and add a printer to the `Booth().printers` attribute
##### Arguments
- `name [str]` - The name that this printer should be referred to as. Default: printer-#
- `model [str]` - The model name of the printer. See [printer.py](./printer.py) for details
- `**kwargs` - Any other KeyWord arguments (kwargs) to be passed along to the class.
##### Return `object`

### add_neopixel()
Initialize and add a neopixel to the `Booth().neopixels` attribute. Control is used as the 'pin' argument.
##### Arguments
- `name [str]` - The name that this printer should be referred to as. Default: printer-#
- `control [int, attribute]` - Can either be a pin object from the package 'board' (`- board.D18`) or an `int()` of the relative pin ID.
- `rows [int]` - The number of rows for this panel/strip. Default: 8
- `cols [int]` - The number of columns for this panel/strip. Default: 32
- `**kwargs` - Any other KeyWord arguments (kwargs) to be passed along to the class.
##### Return `object`

### add_camera()
Initialize and add a camera to the `Booth().cameras` attribute.
##### Arguments
- `name [str]` - The name that this printer should be referred to as. Default: printer-#
- `model [str]` - The model name of the printer. See [printer.py](./printer.py) for details
- `**kwargs` - Any other KeyWord arguments (kwargs) to be passed along to the class.
##### Return `object`

### net_check_local()
Returns `arp_list()`
##### Arguments `None`
##### Return `arp_list()`

### net_check_www()
Returns `connect()` with default arguments.
##### Arguments `None`
##### Return `connect()`

### check_web()
Uses `connect()` to check the local django webserver
##### Arguments `None`
##### Return `connect()`
### stop_web()
Invokes `stop_immediately()` on the web server's thread
##### Arguments `None`
##### Return `True`

### clear_components()
Clear out and reset (if applicable) booth components
##### Arguments `None`
##### Return `True`

### run_as_thread()
Method to call something as a thread within the class
##### Arguments
- `target [function_reference]` - Takes the reference of a function of method. (exclude the `()`)
- `**args` - Any other arguments (args) to be passed along to the class.
- `**kwargs` - Any other KeyWord arguments (kwargs) to be passed along to the class.
##### Return `object`

## Thread()
Wrapper class for the native `multiprocessing` python library.
Leverages `multiprocessing.Process() and multiprocessing.Event()`
Wraps a provided function in a thread that can run independently until stopped
Functions provided should be designed to run a finite number of times so that a loop doesn't cause the function to never release control to the thread.
Setting executions to anything other than exactly int() > 0 will cause the thread to run until stopped.
For functions that modify class attributes, the attribute must be set up to use a shared memory variable, otherwise the attribute change won't persist the thread.
See `camera.Camera().capture()` for an example

### start()
Start the process in this thread
##### Arguments `None`
##### Return `None`

### stop()
Shortcut for `stop_gracefully()`
##### Arguments
- `**args` - Any other arguments (args) to be passed along.
- `**kwargs` - Any other KeyWord arguments (kwargs) to be passed along.
##### Return `stop_gracefully()`

### stop_gracefully()
Allow the thread to come to the end of an iteration, and stop.
##### Arguments
- `**args` - Any other arguments (args) to be passed along.
- `**kwargs` - Any other KeyWord arguments (kwargs) to be passed along.
##### Return `True`

### stop_immediately()
Send a SIGKILL to the thread, halting it without allowing the thread to come to the end of an iteration.
##### Arguments
- `**args` - Any other arguments (args) to be passed along.
- `**kwargs` - Any other KeyWord arguments (kwargs) to be passed along.
##### Return `True`

### restart()
Restart the thread. If not already stopped: `stop_immediately()` first.
##### Arguments `None`
##### Return `None`

### is_alive()
Returns `multiprocessing.Process.is_alive()`
##### Arguments `None`
##### Return `boolean`

# camera.py

# neopixel.py

# printer.py

# rpi.py
