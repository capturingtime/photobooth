"""
This class written and tested with:
$ gphoto2 --version
This version of gphoto2 is using the following software versions and options:
gphoto2         2.5.27         gcc, popt(m), exif, no cdk, no aa, no jpeg, no readline
libgphoto2      2.5.22         all camlibs, gcc, ltdl, EXIF
libgphoto2_port 0.12.0         iolibs: disk ptpip serial usb1 usbdiskdirect usbscsi, gcc, ltdl, USB, serial without locking  # noqa: E501
"""
import subprocess
import re
import os

from multiprocessing import Manager
from ctypes import c_wchar_p, c_bool
from datetime import datetime
from sys import platform

# Import not working for some reason
# from photobooth.booth import run_local_cmd

DEFAULT_CAPTURE_DIR = "/opt/captures"


# Adding statically since import isnt working
def run_local_cmd(cmd):
    """ Run a bash command as the current Python user, probably root (because ws281x)
    """
    try:
        output = subprocess.run(cmd, shell=True, capture_output=True)
    except Exception as err:
        print(err)
    else:
        return output


def check_os():
    """ Verify that the OS is Linux
    """
    if not platform == 'linux':
        # TODO: is this the right exception to raise?
        raise RuntimeError(f"Linux is the only supported OS for this class. Detected: {platform}")
    else:
        return True


def check_dir_rw_or_make(tgt_dir: str, mkdir_perms=0o766):
    """ Manage folder creation and permissions checking for the target directory
    """
    check_os()

    if tgt_dir.startswith("~"):
        tgt_dir = os.path.expanduser(tgt_dir)

    if os.path.exists(tgt_dir):
        # Check if existing Dir is RW
        if not os.access(tgt_dir, os.W_OK) and not os.access(tgt_dir, os.R_OK):
            status = os.stat(tgt_dir)
            p = oct(status.st_mode)[-3:]
            raise OSError(f"Target directory '{tgt_dir}' exists, but not RW. Permission: {p}")
        else:
            return True
    else:
        os.mkdir(tgt_dir)
        os.chmod(tgt_dir, mkdir_perms)
        # Recursive check
        if check_dir_rw_or_make(tgt_dir):
            return True
        else:
            return False  # This shouldn't ever happen


# TODO: Should all of these static functions be seperated for cleanliness and add as a superclass?
def check_gphoto2():
    """ verify gphoto2 is installed
    """
    check_os()  # No reason to check if its not linux (wont have gphoto2)

    result = subprocess.run("which gphoto2", shell=True, capture_output=True)
    check = result.stdout.decode("utf-8").strip("\n").split("/")[-1:]

    if 'gphoto2' not in check:
        # TODO: is this the right exception to raise?
        raise RuntimeError("GPhoto2 was not found on this system")
    else:
        return True


def supported_camera_list():
    """ Grabs the list of gphoto2 cameras and parses into a list
    """
    check_gphoto2()  # No reason to keep going if GPhoto2 isn't installed

    # TODO: Error checking/Handling

    # Capture and cleanup camera list output
    cameras = subprocess.run("gphoto2 --list-cameras", shell=True, capture_output=True)
    cameras = cameras.stdout.decode("utf-8").split("\n\t")
    return [v.strip("\n").strip('"') for v in cameras][1:]  # Slice removes the table header


def get_cameras() -> list:
    """  Grabs a list of connected cameras
    """
    check_gphoto2()  # No reason to keep going if GPhoto2 isn't installed
    cameras = subprocess.run("gphoto2 --auto-detect", shell=True, capture_output=True)

    # TODO: Error checking/Handling

    # Parse the output into a list of (what should be) pairs of values [Camera, addr]
    cameras = cameras.stdout.decode("utf-8").strip(" \n").split("\n")[2:]

    detected_cameras = list()
    for c in cameras:
        model, addr = re.split(" {2,}", c)
        detected_cameras.append({"model": model, "addr": addr})

    return detected_cameras


def capture_and_download(download_dir: str, camera: str, port: str):
    """ Using the specific camer/port, capture and download an image to download_dir
    """
    now = datetime.now()
    ds = now.strftime("%Y%m%d-%Hh%Mm%Ss-%f")

    filename = f"{download_dir}/{ds}.jpg"

    result = subprocess.run("gphoto2 --capture-image-and-download --keep-raw "
                            f"--filename '{filename}' "
                            F"--camera '{camera}' "
                            f"--port '{port}' ",
                            capture_output=True,
                            shell=True)

    # TODO: Can probably expand exceptions for better handling in higherlevel logic
    if result.returncode != 0:
        raise Exception("Something went wrong trying to capture an image.\n"
                        f"stdout: {result.stdout.decode('utf-8')}\n"
                        f"stderr: {result.stderr.decode('utf-8')}")
    else:
        return filename  # return the file created


def config_gphoto2(*args, **kwargs):
    """ Change config elements about gphoto2.
    """
    args = ' '.join([v for v in args])
    kwargs = ' '.join([f"{k}={v}" for k, v in kwargs.items()])
    result = subprocess.run(f"gphoto2 --set-config {args} {kwargs}",
                            shell=True, capture_output=True)

    # TODO: Can probably expand exceptions for better handling in higherlevel logic
    if result.returncode != 0:
        raise Exception("Something went wrong trying to cconfigure GPhoto2\n"
                        f"stdout: {result.stdout.decode('utf-8')}\n"
                        f"stderr: {result.stderr.decode('utf-8')}")
    else:
        return True


# TODO: Add more static functions
# gphoto2 --abilities
# gphoto2 --summary


class Camera():
    """ Manages actions for a camera using the gphoto2 library
        This class currently only support linux systems with gphoto2 installed
    """
    def __init__(self, model: str,
                 output_dir: str = DEFAULT_CAPTURE_DIR, name: str = "",
                 leave_raw: bool = True):
        self.inputs = locals()

        """ Set Queue() attributes
            Using Queue(), we can enable certain attributes to exist uniquely across forks
              that are spawned by threading.Thread(), multiprocessing.Process(), etc.
            This adds some complexity to the class under the covers, but doesn't change much
              around the usage. If higher level logic is not using Thread() / Process(),
              this shouldn't effect anything.
        """
        self._ready = Manager().Value(c_bool, False)
        self._last_shot = Manager().Value(c_wchar_p, "None")
        self._captures = Manager().list()

        if not name:
            # Forces a unique camera name
            name = f"camera-{id(self)}"
        self.name = name

        self.detected_cameras = get_cameras()
        self.model = model
        self.addr = str()
        self.output_dir = output_dir if not output_dir.startswith(
            "~") else os.path.expanduser(output_dir)

        check_dir_rw_or_make(output_dir)

        supported_cameras = supported_camera_list()

        # Quick Check
        if self.model not in supported_cameras:
            match = False
            # Try to resolve a partial model to a full model (first match, not best)
            for a_model in supported_cameras:
                if self.model.lower() in a_model.lower():
                    match = True
                    self.model = a_model
            if not match:
                raise Exception(f"Provided model ({self.model}) not in supported list. "
                                "Please check the list of supported camera models via:\n"
                                "from photobooth.camera import supported_camera_list\n"
                                "supported_camera_list()")

        for camera in self.detected_cameras:
            model = camera["model"]
            addr = camera["addr"]

            if self.model in model:
                self.addr = addr

        if not self.addr:
            raise Exception(f"Requested camera ({self.model}) isn't detected\n"
                            f"Detected cameras: \n{self.detected_cameras}")

        # Configure GPhoto2
        config_gphoto2(capturetarget=int(leave_raw))

        # Init is done
        self._ready.value = True

    def is_ready(self):
        return self._ready.value

    def captures(self):
        return list(self._captures)

    def last_shot(self):
        return self._last_shot.value

    def copy_last_shot_to_dir(self, dir: str):
        """ Copy the last shot to the target directory
        """
        rw = check_dir_rw_or_make(tgt_dir=dir)
        if rw:
            run_local_cmd(f"cp {self._last_shot.value} {dir}")
            return True
        else:
            return False

    # TODO: Functions that the camera can do
    def capture(self):
        """ Captures an image and downloads it to self.output_dir
        """
        if not self.is_ready():
            raise Exception("This camera is currently busy, please wait until is_ready()")
        self._ready.value = False
        pic = capture_and_download(download_dir=self.output_dir, camera=self.model, port=self.addr)
        self._captures.append(pic)
        self._last_shot.value = pic
        self._ready.value = True
        return pic
