from photobooth.strip import PhotoStrip
from photobooth.template_loader import LocalTemplateLoader, TemplateLoader

# Hardware and cloud deps may not be present on non-Pi / non-AWS environments.
try:
    from photobooth.uploader import Uploader
except ImportError:
    Uploader = None  # type: ignore[assignment,misc]

try:
    from photobooth.rpi import RPi
except ImportError:
    RPi = None  # type: ignore[assignment,misc]

__all__ = ["LocalTemplateLoader", "PhotoStrip", "RPi", "TemplateLoader", "Uploader"]
