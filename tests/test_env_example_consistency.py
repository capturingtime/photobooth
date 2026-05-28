"""Cross-repo consistency: BOOTH_* keys must match between the example env
file in rpi_provisioning and the consumers in photobooth.

This is the failure mode this glue is most likely to hit — rename a key on
one side, forget to update the other, and the runtime silently falls back
to the hardcoded Python default. The test pairs the two sides so that drift
in either direction breaks the build.

Skips if the rpi_provisioning sibling repo isn't checked out next to this
one — the test is most useful in a dev environment that has both repos.
"""

import re
from pathlib import Path

import pytest

PHOTOBOOTH_ROOT = Path(__file__).resolve().parents[1]
SIBLING_ENV_EXAMPLE = (
    PHOTOBOOTH_ROOT.parent
    / "rpi_provisioning"
    / "booth_boot"
    / "resources"
    / "booth.env.example"
)

CONSUMER_SOURCES = [
    PHOTOBOOTH_ROOT / "photobooth" / "booth_main.py",
    PHOTOBOOTH_ROOT / "photobooth" / "logging_config.py",
]

# `BOOTH_*` keys mentioned in booth.env.example as either a real assignment or
# a commented-out example. Matches `BOOTH_X=...` and `#BOOTH_X=...`. Allows
# digits because real keys include them (e.g. ``BOOTH_S3_BUCKET``).
ENV_KEY_PATTERN = re.compile(r"^\s*#?\s*(BOOTH_[A-Z0-9_]+)\s*=", re.MULTILINE)

# Match the env-var name inside `os.environ.get("BOOTH_X", ...)` or
# `os.environ["BOOTH_X"]`. Anchoring on `os.environ` avoids false positives
# from docstring text or Python identifiers that happen to share the prefix.
CONSUMER_PATTERN = re.compile(
    r"""os\.environ(?:\.get\(|\[)\s*["'](BOOTH_[A-Z0-9_]+)["']"""
)


def _read_or_skip(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"sibling file not present: {path}")
    return path.read_text()


@pytest.fixture(scope="module")
def example_keys() -> set:
    text = _read_or_skip(SIBLING_ENV_EXAMPLE)
    return set(ENV_KEY_PATTERN.findall(text))


@pytest.fixture(scope="module")
def consumed_keys() -> set:
    keys = set()
    for src in CONSUMER_SOURCES:
        if src.exists():
            keys.update(CONSUMER_PATTERN.findall(src.read_text()))
    return keys


def test_example_file_has_known_keys(example_keys):
    """Sanity check: the regex actually found something to compare."""
    assert example_keys, "booth.env.example yielded zero BOOTH_* keys — parser broken?"


def test_every_example_key_is_consumed_by_code(example_keys, consumed_keys):
    """Documented vars must be read by the runtime — no dead documentation."""
    unused = example_keys - consumed_keys
    assert not unused, (
        f"BOOTH_* keys documented in booth.env.example but not consumed by "
        f"booth_main.py or logging_config.py: {sorted(unused)}"
    )


def test_every_consumed_key_is_documented_in_example(example_keys, consumed_keys):
    """Code-level vars must be documented — no hidden runtime config."""
    undocumented = consumed_keys - example_keys
    assert not undocumented, (
        f"BOOTH_* keys read by the runtime but not documented in "
        f"booth.env.example: {sorted(undocumented)}"
    )
