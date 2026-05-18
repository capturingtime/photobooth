"""
Photobooth asyncio entry point.

Assumes Raspberry Pi 4B wired per the diagram in the README.
Run with: python3 examples/booth_init.py
"""

import asyncio
import board

from photobooth import RPi, Uploader

S3_BUCKET = "public.capturingtimephoto.net"


async def main():
    loop = asyncio.get_running_loop()

    booth = RPi()
    uploader = Uploader(bucket_name=S3_BUCKET)

    # Start Django web server and wait until it responds
    await booth.start_web()
    while not booth.check_web():
        await asyncio.sleep(0.1)
    print("Web server ready")

    await booth.start_kiosk()
    booth.reset_last_shot()

    # Add hardware components
    panel = booth.add_neopixel(name="main", control=board.D18)
    camera = booth.add_camera(name="main", model="Canon EOS 1100D")
    printer = booth.add_printer(name="receipt", model="PBM-8350U")

    # Run panel test concurrently with network checks
    panel_test = asyncio.create_task(panel.panel_test())

    if booth.net_check_local():
        booth.toggle_led(label="net_local", on=True)
    if booth.net_check_www():
        booth.toggle_led(label="net_www", on=True)

    booth.toggle_led(label="camera_rdy", on=True)
    booth.toggle_led(label="print_rdy", on=True)

    await panel_test
    booth.toggle_led(label="shutter_rdy", on=True)
    print("Booth is online and ready")

    # Register GPIO interrupts — buttons now push events into booth.event_queue
    booth.setup_gpio_events(loop)

    # Attract loop animation runs as a background task
    attract = asyncio.create_task(
        panel.scroll(text="Press the capture button to begin!  ", count=999)
    )

    last_print_time: float = 0.0

    # Main event loop — awaits button events instead of busy-polling GPIO
    while True:
        event = await booth.next_event()

        if event == "capture":
            print("Capture button pressed")
            attract.cancel()

            # Countdown
            for label in ("3...", "2...", "1...", "Smile! :D"):
                await panel.scroll(text=label)

            # Capture and upload concurrently — twinkle during the wait
            twinkle_task = asyncio.create_task(panel.twinkle(count=30))
            image_path = await camera.capture_async()
            twinkle_task.cancel()

            booth.copy_to_last_shot(image_path)
            await booth.display_last_shot()

            # Upload to S3 and print receipt with QR code
            url = await uploader.upload(image_path)
            await loop.run_in_executor(None, _print_receipt, printer, url)

            attract = asyncio.create_task(
                panel.scroll(text="Press the capture button to begin!  ", count=999)
            )

        elif event == "print":
            now = loop.time()
            if now - last_print_time <= 3:
                # Debounce successive print presses
                continue
            print("Print button pressed")
            url = uploader.make_key(camera.last_shot())  # re-derive key; presign is async
            presign_task = asyncio.create_task(uploader.presign(url))
            flash_task = asyncio.create_task(panel.scroll(text="Printing...", count=1))
            actual_url = await presign_task
            await flash_task
            await loop.run_in_executor(None, _print_receipt, printer, actual_url)
            last_print_time = now

        elif event == "last_shot":
            await booth.display_last_shot()


def _print_receipt(printer, url: str) -> None:
    """Synchronous receipt print — runs in thread executor from async caller."""
    printer.ln()
    printer.text("Thank you for visiting Capturing Time Photography!\n")
    printer.ln()
    printer.text("Scan the QR code below to download your photo:\n")
    printer.qr(content=url, size=10)
    printer.ln()
    printer.text("Visit us at capturingtimephoto.net\n")
    printer.cut()


if __name__ == "__main__":
    asyncio.run(main())
