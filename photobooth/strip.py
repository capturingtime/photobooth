"""Photo strip compositor — composites N captured images onto a PNG template."""

from PIL import Image


class PhotoStrip:
    """Loads a template once at startup; compose() can be called many times.

    The template PNG must have an alpha channel — it is composited on top of the
    photos so frames, borders, and text overlay cleanly.
    """

    def __init__(self, loader, template_name: str):
        data = loader.load(template_name)
        cfg = data["config"]
        self.shot_count: int = cfg["shot_count"]
        self.canvas_size: tuple = (cfg["canvas"]["width"], cfg["canvas"]["height"])
        self.slots: list = cfg["slots"]
        if len(self.slots) != self.shot_count:
            raise ValueError(f"slot count ({len(self.slots)}) != shot_count ({self.shot_count})")
        self.columns: int = cfg.get("columns", 1)
        self.template = Image.open(data["template_path"]).convert("RGBA")

    def compose(self, shots: list, output_path: str) -> str:
        """Composite shots onto the template and save as a single strip JPEG.

        The output is always one strip wide (``canvas_size`` from the template
        sidecar). The ``columns`` setting is *not* applied here — call
        ``expand_for_print()`` separately when a physical print needs the
        side-by-side layout. This way the file uploaded to S3 and shown on
        the kiosk is the single-strip form (one copy per capture), which is
        what the customer actually downloads.

        Runs synchronously — call via loop.run_in_executor() from async contexts.

        Args:
            shots: Ordered list of image file paths, one per slot.
            output_path: Destination path for the composited JPEG.

        Returns:
            output_path (for chaining with run_in_executor).
        """
        strip = Image.new("RGB", self.canvas_size, color=(255, 255, 255))
        for slot, shot_path in zip(self.slots, shots):
            photo = _center_crop(
                Image.open(shot_path).convert("RGB"),
                slot["width"],
                slot["height"],
            )
            strip.paste(photo, (slot["x"], slot["y"]))
        strip.paste(self.template, (0, 0), mask=self.template)

        strip.save(output_path, "JPEG", quality=95)
        return output_path

    def expand_for_print(self, input_path: str, output_path: str) -> str:
        """Duplicate a composed strip side-by-side for the physical printer.

        A 2×6 strip duplicated columns=2 yields a 4×6 print sheet; the
        operator cuts the two identical strips apart after printing. The
        digital copy (uploaded + displayed) stays single-strip — see
        ``compose()``.

        Pass-through when ``columns <= 1``: there's nothing to duplicate, so
        ``input_path`` is returned unchanged and no file is written. Callers
        can always use the returned path without branching on column count.

        Args:
            input_path: A strip JPEG produced by ``compose()``.
            output_path: Destination for the expanded print-ready JPEG.

        Returns:
            ``input_path`` if columns <= 1, otherwise ``output_path``.
        """
        if self.columns <= 1:
            return input_path

        strip = Image.open(input_path).convert("RGB")
        w, h = strip.size
        canvas = Image.new("RGB", (w * self.columns, h), color=(255, 255, 255))
        for col in range(self.columns):
            canvas.paste(strip, (col * w, 0))
        canvas.save(output_path, "JPEG", quality=95)
        return output_path


def _center_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Scale to fill the slot then center-crop — no black bars."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    img = img.resize((round(src_w * scale), round(src_h * scale)), Image.LANCZOS)
    new_w, new_h = img.size
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))
