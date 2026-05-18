import pathlib
import sys

# Allow `from photobooth.strip import ...` without installing the package.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
