"""Tests for ``photobooth.state_store`` (v0.5.0 Phase 5).

The state store is the durability layer for both the resume record
(``/var/lib/photobooth/resume.json``) and Phase 6's upload queue. Two
contracts matter: (1) reads of a missing file must not raise — callers
treat "no file" as "no prior state"; (2) writes must be atomic — a crash
mid-write must leave the previous file intact, never half-written JSON.
The atomicity test simulates a crash by patching ``os.replace`` to raise.
"""

import json
import os

import pytest

from photobooth import state_store


def test_load_json_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "no_such_file.json"
    assert state_store.load_json(str(missing)) == {}


def test_save_json_atomic_round_trip(tmp_path):
    target = tmp_path / "state.json"
    payload = {"mode": "series", "series_shots": ["a.jpg", "b.jpg"], "shot_index": 3}

    state_store.save_json_atomic(str(target), payload)

    assert target.exists()
    assert state_store.load_json(str(target)) == payload


def test_save_json_atomic_overwrites_existing(tmp_path):
    target = tmp_path / "state.json"
    state_store.save_json_atomic(str(target), {"v": 1})
    state_store.save_json_atomic(str(target), {"v": 2})
    assert state_store.load_json(str(target)) == {"v": 2}


def test_save_json_atomic_crash_during_replace_preserves_original(tmp_path, monkeypatch):
    """If ``os.replace`` fails after the temp file is written, the original
    file at ``path`` must remain intact and the temp file is left behind
    only as ``path.tmp`` (not as a half-written ``path``).

    This is the load-bearing crash-safety property for resume.json — a
    booth that powered off mid-write must come back up reading the prior
    good state, not corrupted JSON.
    """
    target = tmp_path / "state.json"
    state_store.save_json_atomic(str(target), {"good": True})

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated mid-replace power loss")

    monkeypatch.setattr(state_store.os, "replace", boom)
    with pytest.raises(OSError):
        state_store.save_json_atomic(str(target), {"good": False})

    monkeypatch.setattr(state_store.os, "replace", real_replace)
    # Original file untouched.
    assert state_store.load_json(str(target)) == {"good": True}


def test_save_json_atomic_temp_file_cleaned_on_write_error(tmp_path, monkeypatch):
    """A failure during the temp-file write phase must remove the temp
    file so a retry doesn't trip over a stale partial write.
    """
    target = tmp_path / "state.json"

    real_open = open

    def failing_open(path, *args, **kwargs):
        fh = real_open(path, *args, **kwargs)
        if path == str(target) + ".tmp":
            # Wrap fh.write to raise after a partial write.
            orig_write = fh.write

            def boom(_):
                raise OSError("disk full")

            fh.write = boom
        return fh

    monkeypatch.setattr("builtins.open", failing_open)
    with pytest.raises(OSError):
        state_store.save_json_atomic(str(target), {"x": 1})

    assert not (tmp_path / "state.json.tmp").exists()


def test_delete_if_exists_removes_file(tmp_path):
    target = tmp_path / "state.json"
    state_store.save_json_atomic(str(target), {"x": 1})
    assert target.exists()

    state_store.delete_if_exists(str(target))
    assert not target.exists()


def test_delete_if_exists_missing_file_is_noop(tmp_path):
    missing = tmp_path / "no_such_file.json"
    # Must not raise.
    state_store.delete_if_exists(str(missing))


def test_save_json_atomic_pretty_prints(tmp_path):
    """Resume / queue files are human-debuggable on the booth Pi —
    ``sort_keys`` + ``indent`` make ``cat resume.json`` readable.
    """
    target = tmp_path / "state.json"
    state_store.save_json_atomic(str(target), {"b": 2, "a": 1})
    raw = target.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed == {"a": 1, "b": 2}
    assert "\n" in raw  # indented
    assert raw.index('"a"') < raw.index('"b"')  # sorted
