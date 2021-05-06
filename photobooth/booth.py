import logging
import time

import os
import urllib.request
import subprocess
import pathlib
# from typing import get_type_hints
# from functools import wraps
# from inspect import getfullargspec
from multiprocessing import Process, Event


# Components
from photobooth.printer import Printer
from photobooth.neopixel import Neopixel
from photobooth.camera import Camera

DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_LOG_PATH = '/var/log/photobooth.log'

# def validate_input(obj, **kwargs):
#     """ Used by type_check()
#     """
#     hints = get_type_hints(obj)
#     # iterate all type hints
#     for attr_name, attr_type in hints.items():
#         if attr_name == 'return':
#             continue
#         if not isinstance(kwargs[attr_name], attr_type):
#             raise TypeError('Argument %r is not of type %s' % (attr_name, attr_type))


# def type_check(decorator):
#     """ Decorator to run a check for inputs according to type hints
#     """
#     @wraps(decorator)
#     def wrapped_decorator(*args, **kwargs):
#         # translate *args into **kwargs
#         func_args = getfullargspec(decorator)[0]
#         kwargs.update(dict(zip(func_args, args)))
#         validate_input(decorator, **kwargs)
#         return decorator(**kwargs)
#     return wrapped_decorator

def connect(host: str = 'http://google.com') -> bool:
    try:
        urllib.request.urlopen(host)
        return True
    except Exception:
        return False


def arp_list(broadcast_ip: str = "255.255.255.255") -> list:
    """ Gets a list of hosts responding to arp
    """
    # poke hosts
    null_result = subprocess.run(f"ping -c2 {broadcast_ip} -b", shell=True, capture_output=True)
    del null_result

    # Get arp list
    arp_raw = subprocess.run("arp | grep ether", shell=True, capture_output=True)
    arp_raw = arp_raw.stdout.decode("utf-8").strip("\n").split("\n")

    # Parse
    result = list()
    for a in arp_raw:
        p, t, m, f, i = a.split()
        result.append({"ip": p, "mac": m, "interface": i})

    return result


def run_local_cmd(cmd):
    """ Run a bash command as the current Python user, probably root (because ws281x)
    """
    try:
        output = subprocess.run(cmd, shell=True, capture_output=True)
    except Exception as err:
        print(err)
    else:
        return output


class Booth():
    """
    """
    # @type_check
    def __init__(self,
                 web_root: str = None,
                 debug: bool = False):
        self.abspath = os.path.dirname(__file__)
        self.debug = debug
        self._init_logger()

        if not web_root:
            parent_dir = str(pathlib.Path(__file__).resolve().parents[1])
            self.web_root = f"{parent_dir}/photobooth_web"
        else:
            self.web_root = web_root

    # @type_check
    def except_and_log(self, ex_type=ValueError, ex_msg: str = "", log: str = ""):
        """ Raises an exception based on the type provided in ex_type, and logs to file
            If 'log' provided, this string will be added after the log header, before the exception
        """
        if not ex_msg:
            ex_msg = "An unspecified exception occured and no message was provided"

        try:
            raise ex_type(ex_msg)
        except Exception:
            self.logger.exception(log)

    def start_web(self):
        # TODO: Add intelligence to understand the status of the web daemon
        """ Start the Django web server
        """
        cmd = f"python3 {self.web_root}/manage.py runserver 0.0.0.0:8000"
        self.web_server = self.run_as_thread(run_local_cmd, cmd=cmd, start=True)
        return self.web_server

    def start_kiosk(self):
        """ Starts an xsession and runs the kiosk.sh script to load the browser
            that will display output to users
        """
        cmd = f"xinit {self.abspath}/resources/kiosk.sh -- vt$(fgconsole)"
        self.kiosk = self.run_as_thread(run_local_cmd, cmd=cmd, start=True)
        return self.kiosk

    def copy_to_last_shot(self, last_shot: str):
        """ Copy the local file provided to the location that Django looks for to load with last.html
        """
        if not getattr(self, '_last_shot_tgt', None):
            self.reset_last_shot()

        cmd = f"cp {last_shot} {self._last_shot_tgt}"
        try:
            run_local_cmd(cmd=cmd)
        except Exception as err:
            self.except_and_log(ex_type=Exception, ex_msg=err, log="Tried to copy last shot")
        else:
            return True

    def display_last_shot(self):
        """ Intended to be ran after start_kiosk()
            Loads a chromium tab that displays last.html from django
        """
        cmd = "chromium-browser --kiosk --no-sandbox --display=:0.0 --incognito "\
              "http://127.0.0.1:8000/main/last/"
        try:
            run_local_cmd(cmd=cmd)
        except Exception as err:
            self.except_and_log(ex_type=Exception, ex_msg=err, log="Tried to display last shot")
        else:
            return True

    def reset_last_shot(self):
        """ Used to reset last.jpg
        """
        if not getattr(self, '_last_shot_tgt', None):
            self._init_last_shot()
        img_dir = f"{self.web_root}/mainscreen/static/img"
        copy = f"cp {img_dir}/nolast.jpg {img_dir}/last.jpg"
        run_local_cmd(cmd=copy)
        return True

    def _init_last_shot(self):
        """ Initializes 'Last shot' logic (seperate so its optional)
        """
        # Where Django looks for the target for last.html
        self._last_shot_tgt = f"{self.web_root}/mainscreen/static/img/last.jpg"

    def display_help(self):
        # TODO :
        """ When you hit the ('Help' | 'Instructions?') button, display the help screen
        """
        pass

    def _init_logger(self):
        """
        """
        self.logger = logging
        debug = getattr(self, "debug", None)
        if debug:
            level = logging.DEBUG
        else:
            level = DEFAULT_LOG_LEVEL

        self.logger.basicConfig(filename=DEFAULT_LOG_PATH,
                                filemode='a',
                                level=level,
                                datefmt='%Y-%m-%dT%H:%M:%S%z',
                                format='%(levelname)s:%(process)d:%(asctime)s:%(message)s')
        self.logger.info('Logger initialized')

    @staticmethod
    def _init_printer(model: str = None, name: str = None, **kwargs):
        """ Initialize a printer for use
        """
        return Printer(model=model, name=name, **kwargs)

    def add_printer(self, name: str = None, model: str = None, **kwargs):
        """ Add a printer to the Booth().printers attribute
        """
        if not getattr(self, "printers", None):
            self.printers = list()
        # ensure a unique name
        if not name:
            name = f"printer-{len(self.printers)+1}"
        # Instantiate the printer
        printer = self._init_printer(name=name, model=model, **kwargs)
        # add the printer to a list of printers (objects)
        self.printers.append(printer)
        # provide the printer object back to the caller
        return printer

    @staticmethod
    def _init_neopixel(**kwargs):
        """ Initialize a 'neopixel' for use.
            Neopixel is typically a 5050 pixel (RGB)
            controlled by the common ws281x library.
        """
        return Neopixel(**kwargs)

    def add_neopixel(self, name: str = None, control=None, rows: int = 8, cols: int = 32, **kwargs):
        """ Add a neopixel to the Booth().neopixels attribute
            Control is used as the 'pin' positional argument.
            Can either be a pin object from the package 'board' (board.D18)
            or an int() of the relative pin ID.
        """
        if not getattr(self, "neopixels", None):
            self.neopixels = list()
        # ensure a unique name
        if not name:
            name = f"neopixel-{len(self.neopixels)+1}"

        # Add inputs to kwargs to be passed through, but only if they have a real value.
        update = {"name": name, "control": control, "rows": rows, "cols": cols}
        kwargs.update({k: v for k, v in update.items() if v})

        # Instantiate the neopixel
        neopixel = self._init_neopixel(**kwargs)
        # add the neopixel to a list of neopixels (objects)
        self.neopixels.append(neopixel)
        # provide the neopixel object back to the caller
        return neopixel

    @staticmethod
    def _init_camera(**kwargs):
        """ Initialize a camera for use.
            driven by GPhoto2
        """
        return Camera(**kwargs)

    def add_camera(self, name: str = None, model: str = None, **kwargs):
        """ Add a camera to the Booth().cameras attribute.
        """
        if not model:
            raise ValueError("model is a required field. Use supported_camera_list() "
                             "from photobooth.camera for a list of supported camera models")

        if not getattr(self, "cameras", None):
            self.cameras = list()
        # ensure a unique name
        if not name:
            name = f"camera-{len(self.cameras)+1}"

        # Instantiate the camera
        camera = self._init_camera(name=name, model=model, **kwargs)
        # add the camera to a list of cameras (objects)
        self.cameras.append(camera)
        # provide the camera object back to the caller
        return camera

    @staticmethod
    def net_check_local():
        return arp_list()

    @staticmethod
    def net_check_www():
        return connect()

    @staticmethod
    def check_web():
        return connect('http://127.0.0.1:8000/main/')

    def stop_web(self):
        return self.web_server.stop_immediately()

    def clear_components(self):
        if getattr(self, 'neopixels', None):
            for np in self.neopixels:
                np.clear()
            delattr(self, 'neopixels')

        if getattr(self, 'cameras', None):
            delattr(self, 'cameras')

        if getattr(self, 'printers', None):
            delattr(self, 'printers')
        return True

    @staticmethod
    def run_as_thread(target, *args, **kwargs):
        """ Method to call something as a thread within the class
        """
        return Thread(target, *args, **kwargs)


class Thread():
    """ Leverages multiprocessing(Process, Event)
        Wraps a provided function in a thread that can run independently until stopped
        Functions provided should be designed to run a finite number of times so that
          a loop doesn't cause the function to never release control to the thread.
        Setting executions to anything other than exactly int() > 0 will cause the thread
          to run until stopped.

        For functions that modify class attributes, the attribute must be set up to use
        a shared memory variable, otherwise the attribute change won't persist the thread.

        See camera.Camera().capture() for an example
    """
    def __init__(self, target, *args, executions: int = 0, start=False, **kwargs):
        self.inputs = locals()  # For posterity
        self._target = target
        self._args = args
        self._kwargs = kwargs
        self._stop_event = Event()
        self.executions = executions if isinstance(executions, int) else 0
        self.results = list()  # So results are retrievable
        self._setup()
        if start:
            self.start()

    def _setup(self):
        # Spawns a process
        self.process = Process(target=self._target,
                               args=self._args,
                               kwargs=self._kwargs)
        # override the default Process().run() method with Thread()._run()
        self.process.run = self._run

    def start(self):
        # Start the process in this thread
        self.process.start()

    def stop(self, *args, **kwargs):
        # Shortcut for stop_gracefully()
        return self.stop_gracefully(*args, **kwargs)

    def stop_gracefully(self, *args, **kwargs):
        """
        """
        self._stop_event.set()
        self.process.join(*args, **kwargs)
        while self.is_alive():
            time.sleep(0.001)  # check every millisecond
        self.process.close()
        return True

    def stop_immediately(self, *args, **kwargs):
        self._stop_event.set()
        self.process.kill(*args, **kwargs)
        while self.is_alive():
            time.sleep(0.001)  # check every millisecond
        self.process.close()
        return True

    def restart(self):
        if not self._stop_event.is_set():
            self.stop_immediately()
        self._stop_event.clear()
        self._setup()
        self.start()

    def is_alive(self):
        return self.process.is_alive()

    def _run(self):
        """ This method is used to replace the default Process().run() method,
              which is executed on Process().start()
        """
        if self.executions > 0:
            # Run n times
            remaining = self.executions
            while remaining > 0:
                self.results.append(self._target(*self._args, **self._kwargs))
                remaining -= 1
            # Cleanup
            self.process.close()
        else:
            # Run until stopped
            while not self._stop_event.is_set():
                self.results.append(self._target(*self._args, **self._kwargs))
