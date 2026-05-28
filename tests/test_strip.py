"""Tests for photobooth.strip and photobooth.template_loader."""
import json
import pytest
from pathlib import Path
from PIL import Image

from photobooth.strip import PhotoStrip, _center_crop
from photobooth.template_loader import LocalTemplateLoader, TemplateLoader

RESOURCES = Path(__file__).resolve().parents[1] / "photobooth" / "resources"
REAL_TEMPLATE_PNG = RESOURCES / "strip_test_template.png"
REAL_TEMPLATE_JSON = RESOURCES / "strip_test_template.json"


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_image(path: Path, size=(800, 600), mode="RGB", color=(100, 150, 200)) -> Path:
    """Write a solid-color image file and return its path."""
    img = Image.new(mode, size, color=color)
    img.save(path)
    return path


def _make_template(path: Path, size=(600, 1800)) -> Path:
    """Write an RGBA template PNG where the top-left quarter is opaque red."""
    img = Image.new("RGBA", size, color=(0, 0, 0, 0))
    # Draw a thin opaque frame around the edges so alpha compositing is testable.
    for x in range(size[0]):
        for y in [0, size[1] - 1]:
            img.putpixel((x, y), (255, 0, 0, 255))
    for y in range(size[1]):
        for x in [0, size[0] - 1]:
            img.putpixel((x, y), (255, 0, 0, 255))
    img.save(path)
    return path


def _make_sidecar(path: Path, shot_count: int = 3, slots=None) -> Path:
    """Write a template.json sidecar and return its path."""
    if slots is None:
        slots = [
            {"x": 0, "y": 0, "width": 540, "height": 520},
            {"x": 0, "y": 640, "width": 540, "height": 520},
            {"x": 0, "y": 1250, "width": 540, "height": 520},
        ]
    config = {
        "name": "Test Strip",
        "shot_count": shot_count,
        "canvas": {"width": 600, "height": 1800},
        "slots": slots,
    }
    path.write_text(json.dumps(config))
    return path


@pytest.fixture()
def template_dir(tmp_path) -> Path:
    """A valid template folder with both template.png and template.json."""
    folder = tmp_path / "strip_test"
    folder.mkdir()
    _make_template(folder / "template.png")
    _make_sidecar(folder / "template.json")
    return tmp_path  # base dir; template name is "strip_test"


@pytest.fixture()
def strip(template_dir) -> PhotoStrip:
    """A ready-to-use PhotoStrip loaded from the valid template fixture."""
    loader = LocalTemplateLoader(str(template_dir))
    return PhotoStrip(loader=loader, template_name="strip_test")


@pytest.fixture()
def shots(tmp_path) -> list:
    """Three solid-color JPEG files — one per slot in the default sidecar."""
    paths = []
    colors = [(200, 50, 50), (50, 200, 50), (50, 50, 200)]
    for i, color in enumerate(colors):
        p = tmp_path / f"shot_{i}.jpg"
        _make_image(p, size=(800, 600), color=color)
        paths.append(str(p))
    return paths


# ---------------------------------------------------------------------------
# LocalTemplateLoader
# ---------------------------------------------------------------------------


class TestLocalTemplateLoader:
    def test_load_raises_when_png_missing(self, tmp_path):
        folder = tmp_path / "no_png"
        folder.mkdir()
        _make_sidecar(folder / "template.json")
        loader = LocalTemplateLoader(str(tmp_path))
        with pytest.raises(FileNotFoundError, match="template.png"):
            loader.load("no_png")

    def test_load_raises_when_json_missing(self, tmp_path):
        folder = tmp_path / "no_json"
        folder.mkdir()
        _make_template(folder / "template.png")
        loader = LocalTemplateLoader(str(tmp_path))
        with pytest.raises(FileNotFoundError, match="template.json"):
            loader.load("no_json")

    def test_load_returns_template_path_string(self, template_dir):
        loader = LocalTemplateLoader(str(template_dir))
        result = loader.load("strip_test")
        assert result["template_path"] == str(
            template_dir / "strip_test" / "template.png"
        )

    def test_load_returns_parsed_config(self, template_dir):
        loader = LocalTemplateLoader(str(template_dir))
        result = loader.load("strip_test")
        cfg = result["config"]
        assert cfg["shot_count"] == 3
        assert cfg["canvas"] == {"width": 600, "height": 1800}
        assert len(cfg["slots"]) == 3

    def test_is_abstract_base(self):
        assert issubclass(LocalTemplateLoader, TemplateLoader)

    def test_template_loader_is_abstract(self):
        with pytest.raises(TypeError):
            TemplateLoader()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# PhotoStrip.__init__
# ---------------------------------------------------------------------------


class TestPhotoStripInit:
    def test_slot_count_mismatch_raises_value_error(self, tmp_path):
        folder = tmp_path / "bad"
        folder.mkdir()
        _make_template(folder / "template.png")
        # shot_count=3 but only 2 slots
        _make_sidecar(
            folder / "template.json",
            shot_count=3,
            slots=[
                {"x": 0, "y": 0, "width": 540, "height": 520},
                {"x": 0, "y": 640, "width": 540, "height": 520},
            ],
        )
        loader = LocalTemplateLoader(str(tmp_path))
        with pytest.raises(ValueError, match="slot count"):
            PhotoStrip(loader=loader, template_name="bad")

    def test_shot_count_set_from_sidecar(self, strip):
        assert strip.shot_count == 3

    def test_canvas_size_set_from_sidecar(self, strip):
        assert strip.canvas_size == (600, 1800)

    def test_slots_list_set_from_sidecar(self, strip):
        assert len(strip.slots) == 3
        assert strip.slots[0] == {"x": 0, "y": 0, "width": 540, "height": 520}

    def test_template_loaded_as_rgba(self, strip):
        assert strip.template.mode == "RGBA"
        assert strip.template.size == (600, 1800)

    def test_shot_count_two(self, tmp_path):
        folder = tmp_path / "two_shot"
        folder.mkdir()
        _make_template(folder / "template.png")
        _make_sidecar(
            folder / "template.json",
            shot_count=2,
            slots=[
                {"x": 0, "y": 0, "width": 540, "height": 820},
                {"x": 0, "y": 900, "width": 540, "height": 820},
            ],
        )
        loader = LocalTemplateLoader(str(tmp_path))
        ps = PhotoStrip(loader=loader, template_name="two_shot")
        assert ps.shot_count == 2
        assert len(ps.slots) == 2


# ---------------------------------------------------------------------------
# PhotoStrip.compose
# ---------------------------------------------------------------------------


class TestPhotoStripCompose:
    def test_returns_output_path(self, strip, shots, tmp_path):
        out = str(tmp_path / "result.jpg")
        returned = strip.compose(shots, out)
        assert returned == out

    def test_creates_jpeg_at_output_path(self, strip, shots, tmp_path):
        out = str(tmp_path / "result.jpg")
        strip.compose(shots, out)
        assert Path(out).exists()
        img = Image.open(out)
        assert img.format == "JPEG"

    def test_output_matches_canvas_size(self, strip, shots, tmp_path):
        out = str(tmp_path / "result.jpg")
        strip.compose(shots, out)
        img = Image.open(out)
        assert img.size == (600, 1800)

    def test_output_is_rgb(self, strip, shots, tmp_path):
        out = str(tmp_path / "result.jpg")
        strip.compose(shots, out)
        img = Image.open(out)
        assert img.mode == "RGB"

    def test_compose_idempotent(self, strip, shots, tmp_path):
        """compose() can be called multiple times on the same PhotoStrip."""
        out1 = str(tmp_path / "r1.jpg")
        out2 = str(tmp_path / "r2.jpg")
        strip.compose(shots, out1)
        strip.compose(shots, out2)
        assert Path(out1).exists()
        assert Path(out2).exists()

    def test_shot_color_visible_in_slot(self, strip, shots, tmp_path):
        """The photo pixel colors should appear at each slot's top-left corner."""
        out = str(tmp_path / "result.jpg")
        strip.compose(shots, out)
        result = Image.open(out).convert("RGB")
        slot = strip.slots[0]
        # Sample a pixel safely inside the slot — JPEG may shift exact values slightly
        px = result.getpixel((slot["x"] + 10, slot["y"] + 10))
        # Shot 0 is red-dominant (200, 50, 50); verify red channel dominates
        assert px[0] > px[1] and px[0] > px[2]


# ---------------------------------------------------------------------------
# _center_crop
# ---------------------------------------------------------------------------


class TestCenterCrop:
    def test_output_dimensions_exact(self):
        img = Image.new("RGB", (800, 600))
        result = _center_crop(img, 300, 200)
        assert result.size == (300, 200)

    def test_landscape_source_portrait_slot(self):
        img = Image.new("RGB", (1200, 400))
        result = _center_crop(img, 100, 400)
        assert result.size == (100, 400)

    def test_portrait_source_landscape_slot(self):
        img = Image.new("RGB", (400, 1200))
        result = _center_crop(img, 400, 100)
        assert result.size == (400, 100)

    def test_same_aspect_ratio(self):
        img = Image.new("RGB", (600, 400))
        result = _center_crop(img, 300, 200)
        assert result.size == (300, 200)

    def test_square_source_wide_slot(self):
        img = Image.new("RGB", (500, 500))
        result = _center_crop(img, 400, 100)
        assert result.size == (400, 100)

    def test_square_source_tall_slot(self):
        img = Image.new("RGB", (500, 500))
        result = _center_crop(img, 100, 400)
        assert result.size == (100, 400)

    def test_upscale_small_source(self):
        """Small source image should be scaled up to fill the slot."""
        img = Image.new("RGB", (50, 50))
        result = _center_crop(img, 400, 300)
        assert result.size == (400, 300)

    def test_center_crop_is_centered(self):
        """Pixel at center of result should come from center of source."""
        # Create an image with a distinct center pixel
        img = Image.new("RGB", (100, 100), color=(0, 0, 0))
        img.putpixel((50, 50), (255, 0, 0))
        # Crop to same size — no scaling, just verify no off-by-one shift
        result = _center_crop(img, 100, 100)
        assert result.getpixel((50, 50)) == (255, 0, 0)


# ---------------------------------------------------------------------------
# Real template file (photobooth/resources/strip_test_template.{png,json})
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_loader(tmp_path) -> LocalTemplateLoader:
    """LocalTemplateLoader pointed at a folder containing the real template files.

    LocalTemplateLoader expects <base>/<name>/template.{png,json}, so we
    symlink the resource files into a temporary subfolder with those names.
    """
    folder = tmp_path / "strip_test"
    folder.mkdir()
    (folder / "template.png").symlink_to(REAL_TEMPLATE_PNG)
    (folder / "template.json").symlink_to(REAL_TEMPLATE_JSON)
    return LocalTemplateLoader(str(tmp_path))


@pytest.fixture()
def real_strip(real_loader) -> PhotoStrip:
    return PhotoStrip(loader=real_loader, template_name="strip_test")


@pytest.fixture()
def real_shots(tmp_path) -> list:
    """Three solid-color JPEGs sized to match the real template's slots (538x358)."""
    paths = []
    colors = [(200, 80, 80), (80, 200, 80), (80, 80, 200)]
    for i, color in enumerate(colors):
        p = tmp_path / f"real_shot_{i}.jpg"
        _make_image(p, size=(538, 358), color=color)
        paths.append(str(p))
    return paths


class TestRealTemplate:
    def test_sidecar_files_exist(self):
        assert REAL_TEMPLATE_PNG.exists(), "template PNG missing from resources/"
        assert REAL_TEMPLATE_JSON.exists(), "template JSON missing from resources/"

    def test_template_is_rgba(self):
        img = Image.open(REAL_TEMPLATE_PNG)
        assert img.mode == "RGBA"

    def test_template_canvas_size(self):
        img = Image.open(REAL_TEMPLATE_PNG)
        assert img.size == (600, 1800)

    def test_template_has_transparent_slots(self):
        img = Image.open(REAL_TEMPLATE_PNG)
        alpha = img.getchannel("A")
        transparent = alpha.histogram()[0]  # histogram()[0] = count of alpha=0 pixels
        assert transparent > 0, "template has no transparent pixels — slots not cut out"

    def test_sidecar_slot_count_matches_json(self):
        config = json.loads(REAL_TEMPLATE_JSON.read_text())
        assert config["shot_count"] == len(config["slots"])

    def test_sidecar_loads_correctly(self, real_loader):
        data = real_loader.load("strip_test")
        cfg = data["config"]
        assert cfg["shot_count"] == 3
        assert cfg["canvas"] == {"width": 600, "height": 1800}
        assert len(cfg["slots"]) == 3

    def test_slots_are_consistent_size(self):
        config = json.loads(REAL_TEMPLATE_JSON.read_text())
        widths = {s["width"] for s in config["slots"]}
        heights = {s["height"] for s in config["slots"]}
        assert len(widths) == 1, f"slots have inconsistent widths: {widths}"
        assert len(heights) == 1, f"slots have inconsistent heights: {heights}"

    def test_slots_within_canvas_bounds(self):
        config = json.loads(REAL_TEMPLATE_JSON.read_text())
        W, H = config["canvas"]["width"], config["canvas"]["height"]
        for i, s in enumerate(config["slots"]):
            assert s["x"] >= 0 and s["x"] + s["width"] <= W, f"slot {i} exceeds canvas width"
            assert s["y"] >= 0 and s["y"] + s["height"] <= H, f"slot {i} exceeds canvas height"

    def test_photostrip_loads_from_real_template(self, real_strip):
        assert real_strip.shot_count == 3
        assert real_strip.canvas_size == (600, 1800)
        assert real_strip.template.mode == "RGBA"

    def test_compose_with_real_template(self, real_strip, real_shots, tmp_path):
        out = str(tmp_path / "real_result.jpg")
        returned = real_strip.compose(real_shots, out)
        assert returned == out
        assert Path(out).exists()

    def test_compose_output_dimensions(self, real_strip, real_shots, tmp_path):
        out = str(tmp_path / "real_result.jpg")
        real_strip.compose(real_shots, out)
        result = Image.open(out)
        # compose() always emits single-strip; the column-duplication step
        # for physical printing lives in expand_for_print(), exercised in
        # TestExpandForPrint below.
        assert result.size == (600, 1800)

    def test_expand_for_print_doubles_strip_for_columns_2(
        self, real_strip, real_shots, tmp_path
    ):
        """The real sidecar has columns=2 — expand_for_print produces 1200×1800."""
        single = str(tmp_path / "single.jpg")
        real_strip.compose(real_shots, single)
        printable = str(tmp_path / "print.jpg")

        out = real_strip.expand_for_print(single, printable)

        assert out == printable
        assert Image.open(out).size == (1200, 1800)

    def test_expand_for_print_passthrough_when_columns_le_1(
        self, strip, shots, tmp_path
    ):
        """columns=1 (or absent) → no expansion, input path returned unchanged.

        The default sidecar fixture has no ``columns`` key, so columns defaults
        to 1. The real_strip fixture (production template) uses columns=2.
        """
        assert strip.columns == 1

        single = str(tmp_path / "single.jpg")
        strip.compose(shots, single)

        out = strip.expand_for_print(single, str(tmp_path / "should_not_exist.jpg"))

        assert out == single, "passthrough must return input_path unchanged"
        assert not (tmp_path / "should_not_exist.jpg").exists(), (
            "no output file should be written when columns <= 1"
        )

    def test_expand_for_print_left_and_right_halves_are_identical(
        self, real_strip, real_shots, tmp_path
    ):
        single = str(tmp_path / "single.jpg")
        real_strip.compose(real_shots, single)
        printable = str(tmp_path / "print.jpg")
        real_strip.expand_for_print(single, printable)

        full = Image.open(printable).convert("RGB")
        left = full.crop((0, 0, 600, 1800))
        right = full.crop((600, 0, 1200, 1800))
        # JPEG re-encoding can introduce subpixel differences; sample a
        # handful of points to verify the duplication, not a bit-for-bit match.
        for x, y in [(100, 100), (300, 900), (500, 1700)]:
            assert left.getpixel((x, y)) == right.getpixel((x, y)), (
                f"left/right halves differ at ({x},{y})"
            )

    def test_compose_slot_colors_visible(self, real_strip, real_shots, tmp_path):
        """Each photo's dominant color should be visible inside its slot."""
        out = str(tmp_path / "real_result.jpg")
        real_strip.compose(real_shots, out)
        result = Image.open(out).convert("RGB")
        config = json.loads(REAL_TEMPLATE_JSON.read_text())
        # Sample well inside each slot to avoid frame edge bleed
        expected_dominant = [0, 1, 2]  # red, green, blue channel index
        for slot, dominant_ch in zip(config["slots"], expected_dominant):
            cx = slot["x"] + slot["width"] // 2
            cy = slot["y"] + slot["height"] // 2
            px = result.getpixel((cx, cy))
            assert px[dominant_ch] > px[(dominant_ch + 1) % 3], (
                f"slot at y={slot['y']}: expected channel {dominant_ch} dominant, got {px}"
            )
