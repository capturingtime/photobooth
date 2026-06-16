import asyncio
import logging

from escpos.printer import Usb
from inspect import getfullargspec

logger = logging.getLogger(__name__)

# Lookup USB Devices - https://www.the-sz.com/products/usbid/
# TODO: Maybe convert this to a collection of YAML files that are ingested?
PRINTER_MAP = {
    "default": {
        "model": "Unknown",
        "config": {
            "idVendor": 0x0416,
            "idProduct": 0x5011,
            "in_ep": 0x81,
            "out_ep": 0x01,
            "timeout": 0,
        },
        "details": {
            "paperSizes": [],
            "connection_type": None,
            "autoCut": None,
            "print_modes": {
                "thermal": None,
                "inkjet": None,
                "photo": None,
                "laser": None,
            },
        },
    },
    "PBM-8350U": {
        "model": "PBM-8350U",
        "config": {
            "idVendor": 0x0416,
            "idProduct": 0x5011,
            "in_ep": 0x81,
            "out_ep": 0x03,
            "timeout": 0,
        },
        "details": {
            "paperSizes": ["80mm"],
            "connection_type": "usb",
            "autoCut": True,
            "print_modes": {
                "thermal": True,
                "inkjet": False,
                "photo": False,
                "laser": False,
            },
        },
    },
}


def _probe_printer_sync(model: str) -> bool:
    """Synchronous USB device probe — looks up ``model`` in ``PRINTER_MAP``
    and returns True if a USB device with that vendor/product ID is
    currently enumerated. Used by ``probe_printer_available``.
    """
    spec = PRINTER_MAP.get(model, PRINTER_MAP["default"])
    cfg = spec["config"]
    try:
        import usb.core

        dev = usb.core.find(idVendor=cfg["idVendor"], idProduct=cfg["idProduct"])
        return dev is not None
    except Exception as exc:
        logger.debug("probe_printer_available: USB lookup error %s", exc)
        return False


async def probe_printer_available(model: str = "PBM-8350U") -> bool:
    """Return True if the receipt printer's USB device is enumerated.

    Used by ``HealthMonitor`` (v0.5.0 Phase 4). The probe only checks
    that the USB device with the configured vendor/product ID is
    present — it does not open the device, so it is safe to call while
    another process (or a prior init attempt) holds the handle.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _probe_printer_sync, model)


class Printer:
    """Loads a printer according to the model supplied (explicit list of support)
    and provides common functions
    """

    def __init__(self, name: str = "", model: str = "", **kwargs):

        if not name:
            # Forces a unique printer name
            name = f"printer-{id(self)}"
        self.name = name

        if model:
            self.printer_spec = PRINTER_MAP.get(str(model), dict())
        else:
            self.printer_spec = PRINTER_MAP.get("default")

        self.model = self.printer_spec.get("model", "unknown")

        valid_kwargs = getfullargspec(Usb)
        # ['self', 'idVendor', 'idProduct', 'timeout', 'in_ep', 'out_ep']

        # Look for kwargs passed that match a kwarg for Usb() and override
        for k, v in kwargs:
            if k in valid_kwargs:
                self.printer_spec["config"][k] = kwargs.pop(k, None)

        self.inputs = locals()

        config = self.printer_spec["config"]
        self.printer = Usb(**config)

        # TODO: Add logic that verifies the printer is working

    def ln(self, count=1):
        """feeds n lines to print buffer
        replicates Escpos().ln() in newer version (>=3.0)
        https://github.com/python-escpos/python-escpos/blob/f9ce77705757dcd3a3946569d02810ae7e122e88/src/escpos/escpos.py#L531
        """
        if count < 0:
            count = 0
        if count == 0:
            return False
        return self.printer.text("\n" * count)

    def text(self, text):
        """Pass through to Escpos().text()
        https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L424
        """
        self.printer.text(text)
        return True

    def cut(self, mode="PART"):
        """Pass through to Escpos().cut()
        https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L597
        """
        return self.printer.cut(mode)

    # TODO: Make this better
    def barcode(self, *args, **kwargs):
        """Pass through to Escpos().barcode()
        https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L295
        """
        return self.printer.barcode(*args, **kwargs)

    # TODO: Make this better
    def qr(self, *args, **kwargs):
        """Pass through to Escpos().qr()
        https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L134
        """
        return self.printer.qr(*args, **kwargs)

    # TODO :
    # Possible answer to a dynamic pass through method
    # Disabling because i dont feel like testing it right now
    # def __getattr__(self, name):
    #     try:
    #         method = setattr(self, getattr(Usb, name))
    #     except Exception as err:
    #         logger.error("Printer USB error: %s", err)

    #     else:
    #         return method
