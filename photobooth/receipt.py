"""Receipt content for the thermal printer.

Pure presentation — the marketing copy and QR layout printed after each
capture. Kept apart from ``booth_main`` so copy edits don't touch runtime
logic. ``render`` accepts any object exposing the python-escpos surface
(``text`` / ``ln`` / ``qr`` / ``cut``), so it's trivially unit-testable
against a fake printer.
"""

from typing import Optional


def render(printer, url: str, pending_notice: Optional[str] = None) -> None:
    """Write the post-capture receipt to ``printer``.

    ``url`` becomes the QR payload — a presigned/deterministic S3 URL.
    Never log it: it carries an AWS signature (sensitive credential
    material). ``pending_notice``, when set, prints under the QR to tell
    the user their link will start working once the booth reconnects
    (Phase 6 offline-upload path).
    """
    printer.text("Capturing Time Photography")
    printer.ln()
    printer.ln()
    printer.text("Thank you for using our photobooth!")
    printer.ln()
    printer.ln()
    printer.text("Please visit us at http://capturingtimephoto.net")
    printer.ln()
    printer.text("    to schedule your free 30 minute consultation")
    printer.ln()
    printer.text("    for your next portrait session or event!")
    printer.ln()
    printer.ln()
    printer.text("Mention this photobooth when you book your next")
    printer.ln()
    printer.text("session with us & receive an extra 10% discount!")
    printer.ln()
    printer.ln()
    printer.text("Scan the QR code below to download your photo:")
    printer.ln()
    printer.qr(content=url, size=5)
    printer.ln()
    if pending_notice:
        printer.text(pending_notice)
        printer.ln()
        printer.ln()
    printer.text("Reach us at contact@capturingtimephoto.net")
    printer.ln()
    printer.text("Tag us on")
    printer.ln()
    printer.text("Instagram: @capturingtimephoto")
    printer.ln()
    printer.text("Facebook: @capturingtimephotollc")
    printer.cut()
