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
            raise ValueError(
                f"slot count ({len(self.slots)}) != shot_count ({self.shot_count})"
            )
        self.columns: int = cfg.get("columns", 1)
        self.template = Image.open(data["template_path"]).convert("RGBA")

    def compose(self, shots: list, output_path: str) -> str:
        """Composite shots onto the template and save as JPEG.

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

        if self.columns > 1:
            w, h = self.canvas_size
            canvas = Image.new("RGB", (w * self.columns, h), color=(255, 255, 255))
            for col in range(self.columns):
                canvas.paste(strip, (col * w, 0))
        else:
            canvas = strip

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
