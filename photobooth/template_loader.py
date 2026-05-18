"""Template loader abstraction — swap LocalTemplateLoader for USB or remote later."""
import json
from abc import ABC, abstractmethod
from pathlib import Path


class TemplateLoader(ABC):
    @abstractmethod
    def load(self, template_name: str) -> dict:
        """Return {"template_path": str, "config": dict}."""
        ...


class LocalTemplateLoader(TemplateLoader):
    """Loads templates from a local directory tree.

    Expected layout:
        <base_dir>/<template_name>/template.png
        <base_dir>/<template_name>/template.json
    """

    def __init__(self, base_dir: str):
        self._base = Path(base_dir)

    def load(self, template_name: str) -> dict:
        folder = self._base / template_name
        png = folder / "template.png"
        cfg = folder / "template.json"
        if not png.exists():
            raise FileNotFoundError(f"Template PNG not found: {png}")
        if not cfg.exists():
            raise FileNotFoundError(f"Template sidecar not found: {cfg}")
        with open(cfg) as f:
            config = json.load(f)
        return {"template_path": str(png), "config": config}
