import logging
import threading
import os
# from typing import get_type_hints
# from functools import wraps
# from inspect import getfullargspec

from photobooth.printer import Printer
from photobooth.neopixel import Neopixel

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


class Booth():
    """
    """
    # @type_check
    def __init__(self,
                 debug: bool = False
                 ):
        """
        """
        self.abspath = os.path.dirname(__file__)
        self.debug = debug
        self._init_logger()

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
        return Printer(printerModel=model, name=name, **kwargs)

    def add_printer(self, name: str = None, model: str = None, **kwargs):
        """ Add a printer to the Booth().printers attribute
        """
        if not getattr(self, "printers", None):
            self.printers = list()
        # ensure a unique name
        if not name:
            name = f"printer{len(self.printers)+1}"
        # Instantiate the printer
        printer = self._init_printer(model=model, **kwargs)
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
            name = f"neopixel{len(self.neopixels)+1}"

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
    def run_as_thread(target, *args, **kwargs):
        """ Method to call something as a thread within the class
        """
        return Thread(target, *args, **kwargs)


class Thread(threading.Thread):
    """ Wraps a provided function in a thread that can run independently until stopped
        Functions provided should be designed to run a finite number of times
    """
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
