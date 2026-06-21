"""Tests for photobooth.printer.

The ``Printer`` class is a thin shim over ``escpos.printer.Usb``. The unit
test value here is mostly: model-string → ``PRINTER_MAP`` resolution, kwargs
plumbing, and the tiny ``ln()`` helper's edge-case clamping.

The escpos device itself is mocked everywhere — instantiating ``Usb()`` for
real tries to open a USB endpoint, which is neither portable nor desirable
in a unit test.
"""

import copy
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("escpos", reason="python-escpos not installed in this env")

from photobooth import printer  # noqa: E402


@pytest.fixture
def fake_usb():
    """Patch ``escpos.printer.Usb`` so Printer.__init__ doesn't touch USB."""
    with patch.object(printer, "Usb") as mock_usb:
        mock_usb.return_value = MagicMock()
        yield mock_usb


class TestPrinterInit:
    def test_default_model_loads_default_spec(self, fake_usb):
        p = printer.Printer()
        assert p.model == "Unknown"
        # default spec's USB config was passed to Usb(**config)
        kwargs = fake_usb.call_args.kwargs
        assert kwargs["idVendor"] == 0x0416
        assert kwargs["idProduct"] == 0x5011
        assert kwargs["out_ep"] == 0x01

    def test_pbm_model_loads_pbm_spec(self, fake_usb):
        p = printer.Printer(model="PBM-8350U")
        assert p.model == "PBM-8350U"
        kwargs = fake_usb.call_args.kwargs
        # PBM-8350U overrides out_ep to 0x03
        assert kwargs["out_ep"] == 0x03

    def test_unknown_model_falls_through_to_empty_spec(self, fake_usb):
        """A model not in PRINTER_MAP yields ``self.model == "unknown"``."""
        with pytest.raises(KeyError):
            # printer_spec becomes {} for unknown model, then config = spec["config"]
            # KeyErrors. Document the current behavior so a future change is
            # an intentional decision rather than an accident.
            printer.Printer(model="DefinitelyNotARealModel")

    def test_unique_default_name_per_instance(self, fake_usb):
        a = printer.Printer()
        b = printer.Printer()
        assert a.name != b.name

    def test_explicit_name_is_respected(self, fake_usb):
        p = printer.Printer(name="receipt")
        assert p.name == "receipt"

    def test_init_deep_copies_spec_no_shared_map_mutation(self, fake_usb):
        """Per-instance config must not alias (and mutate) PRINTER_MAP."""
        before = copy.deepcopy(printer.PRINTER_MAP["PBM-8350U"])
        p = printer.Printer(model="PBM-8350U")
        p.printer_spec["config"]["out_ep"] = 0x99  # mutate this instance only
        assert printer.PRINTER_MAP["PBM-8350U"] == before

    def test_usb_kwarg_override_reaches_config(self):
        """A valid escpos ``Usb`` kwarg passed in overrides the spec default.

        Uses a real-signature stub for ``Usb`` so ``getfullargspec`` can see
        the arg names (a bare MagicMock exposes none), then confirms the
        override lands in the per-instance config and the shared map is intact.
        """

        class _SpecUsb:
            def __init__(
                self, idVendor=None, idProduct=None, timeout=None, in_ep=None, out_ep=None
            ):
                self.captured = {"out_ep": out_ep}

        with patch.object(printer, "Usb", _SpecUsb):
            p = printer.Printer(model="PBM-8350U", out_ep=0x09)

        assert p._config["out_ep"] == 0x09
        assert printer.PRINTER_MAP["PBM-8350U"]["config"]["out_ep"] == 0x03


class TestPrinterPassthroughs:
    def test_text_delegates_to_escpos(self, fake_usb):
        p = printer.Printer()
        p.text("hello world")
        p.printer.text.assert_called_once_with("hello world")

    def test_cut_delegates_to_escpos_with_default_mode(self, fake_usb):
        p = printer.Printer()
        p.cut()
        p.printer.cut.assert_called_once_with("PART")

    def test_cut_passes_explicit_mode(self, fake_usb):
        p = printer.Printer()
        p.cut(mode="FULL")
        p.printer.cut.assert_called_once_with("FULL")

    def test_barcode_delegates(self, fake_usb):
        p = printer.Printer()
        p.barcode("123456", "EAN13")
        p.printer.barcode.assert_called_once_with("123456", "EAN13")

    def test_qr_delegates(self, fake_usb):
        p = printer.Printer()
        p.qr("https://example.com/key", size=8)
        p.printer.qr.assert_called_once_with("https://example.com/key", size=8)


class TestLn:
    def test_positive_count_feeds_that_many_newlines(self, fake_usb):
        p = printer.Printer()
        p.ln(3)
        p.printer.text.assert_called_once_with("\n\n\n")

    def test_zero_count_returns_false_without_feeding(self, fake_usb):
        p = printer.Printer()
        assert p.ln(0) is False
        p.printer.text.assert_not_called()

    def test_negative_count_clamped_to_zero(self, fake_usb):
        p = printer.Printer()
        assert p.ln(-5) is False
        p.printer.text.assert_not_called()
