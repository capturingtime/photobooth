from escpos.printer import Usb
from inspect import getfullargspec

# Lookup https://www.the-sz.com/products/usbid/
PRINTER_MAP = {
    "default": {
        "model": "Unknown",
        "config": {
            "idVendor": 0x0416,
            "idProduct": 0x5011,
            "in_ep": 0x81,
            "out_ep": 0x01,
            "timeout": 0
        },
        "details": {
            "paperSizes": [],
            "connection_type": None,
            "autoCut": None,
            "print_modes": {
                "thermal": None,
                "inkjet": None,
                "photo": None,
                "laser": None
            }
        }
    },
    "PBM-8350U": {
        "model": "PBM-8350U",
        "config": {
            "idVendor": 0x0416,
            "idProduct": 0x5011,
            "in_ep": 0x81,
            "out_ep": 0x03,
            "timeout": 0
        },
        "details": {
            "paperSizes": [
                "80mm"
            ],
            "connection_type": "usb",
            "autoCut": True,
            "print_modes": {
                "thermal": True,
                "inkjet": False,
                "photo": False,
                "laser": False
            }
        }
    }
}


class Printer():
    """ Loads a printer according to the model supplied (explicit list of support)
        and provides common functions
    """
    def __init__(self,
                 name: str = "",
                 printerModel: str = "",
                 **kwargs):

        if not name:
            # Forces a unique printer name
            name = f"printer-{id(self)}"
        self.name = name

        if printerModel:
            self.printer_spec = PRINTER_MAP.get(str(printerModel), dict())
        else:
            self.printer_spec = PRINTER_MAP.get("default")

        self.model = self.printer_spec.get('model', 'unknown')

        valid_kwargs = getfullargspec(Usb)
        # ['self', 'idVendor', 'idProduct', 'timeout', 'in_ep', 'out_ep']

        # Look for kwargs passed that match a kwarg for Usb() and override
        for k, v in kwargs:
            if k in valid_kwargs:
                self.printer_spec["config"][k] = kwargs.pop(k, None)

        self.inputs = locals()

        config = self.printer_spec['config']
        self.printer = Usb(**config)

    def ln(self, count=1):
        """ feeds n lines to print buffer
            replicates Escpos().ln() in newer version (>=3.0)
            https://github.com/python-escpos/python-escpos/blob/f9ce77705757dcd3a3946569d02810ae7e122e88/src/escpos/escpos.py#L531
        """
        if count < 0:
            count = 0
        if count == 0:
            return False
        return self.printer.text('\n' * count)

    def text(self, text):
        """ Pass through to Escpos().text()
            https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L424
        """
        return self.printer.text(text)

    def cut(self, mode="PART"):
        """ Pass through to Escpos().cut()
            https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L597
        """
        return self.printer.cut(mode)

    def barcode(self, *args, **kwargs):
        """ Pass through to Escpos().barcode()
            https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L295
        """
        return self.printer.barcode(*args, **kwargs)

    def qr(self, *args, **kwargs):
        """ Pass through to Escpos().qr()
            https://github.com/python-escpos/python-escpos/blob/cbe38648f50dd42e25563bd8603953eaa13cb7f6/src/escpos/escpos.py#L134
        """
        return self.printer.qr(*args, **kwargs)

    # FIXME
    # Possible answer to a dynamic pass through method
    # Disabling because i dont feel like testing it right now
    # def __getattr__(self, name):
    #     try:
    #         method = setattr(self, getattr(Usb, name))
    #     except Exception as err:
    #         print(err)

    #     else:
    #         return method

"""
$lsusb
Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 001 Device 006: ID 0416:5011 Winbond Electronics Corp. Virtual Com Port
Bus 001 Device 004: ID 04a9:3217 Canon, Inc.
Bus 001 Device 002: ID 2109:3431 VIA Labs, Inc. Hub
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub


$lsusb -vvv -d 0416:5011

Bus 001 Device 006: ID 0416:5011 Winbond Electronics Corp. Virtual Com Port
Device Descriptor:
  bLength                18
  bDescriptorType         1
  bcdUSB               2.00
  bDeviceClass            0
  bDeviceSubClass         0
  bDeviceProtocol         0
  bMaxPacketSize0        64
  idVendor           0x0416 Winbond Electronics Corp.
  idProduct          0x5011 Virtual Com Port
  bcdDevice            2.00
  iManufacturer           1 STMicroelectronics
  iProduct                2 POS80 Printer USB
  iSerial                 0
  bNumConfigurations      1
  Configuration Descriptor:
    bLength                 9
    bDescriptorType         2
    wTotalLength       0x0020
    bNumInterfaces          1
    bConfigurationValue     1
    iConfiguration          5 (error)
    bmAttributes         0xc0
      Self Powered
    MaxPower              100mA
    Interface Descriptor:
      bLength                 9
      bDescriptorType         4
      bInterfaceNumber        0
      bAlternateSetting       0
      bNumEndpoints           2
      bInterfaceClass         7 Printer
      bInterfaceSubClass      1 Printer
      bInterfaceProtocol      2 Bidirectional
      iInterface              4 (error)
      Endpoint Descriptor:
        bLength                 7
        bDescriptorType         5
        bEndpointAddress     0x81  EP 1 IN
        bmAttributes            2
          Transfer Type            Bulk
          Synch Type               None
          Usage Type               Data
        wMaxPacketSize     0x0040  1x 64 bytes
        bInterval               0
      Endpoint Descriptor:
        bLength                 7
        bDescriptorType         5
        bEndpointAddress     0x03  EP 3 OUT
        bmAttributes            2
          Transfer Type            Bulk
          Synch Type               None
          Usage Type               Data
        wMaxPacketSize     0x0040  1x 64 bytes
        bInterval               0
can't get device qualifier: Resource temporarily unavailable
can't get debug descriptor: Resource temporarily unavailable
Device Status:     0x0001
  Self Powered
"""