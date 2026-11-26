from __future__ import annotations

import pytest

from material_core import filesystem
from wissensbasis.config import Fach
from wissensbasis.scan import load_manifest, save_manifest


def test_manifest_failure_keeps_previous_state(project, monkeypatch):
    fach = Fach("testfach")
    original = {"fach": "testfach", "quellenordner": "quellen-testfach", "dokumente": []}
    save_manifest(fach, original)
    before = fach.manifest.read_bytes()

    def no_space(*args):
        raise OSError("Kein Speicherplatz")

    monkeypatch.setattr(filesystem.os, "fsync", no_space)
    with pytest.raises(OSError):
        save_manifest(fach, {**original, "version": 2})
    assert fach.manifest.read_bytes() == before
    assert load_manifest(fach) == original
    assert not list(fach.manifest.parent.glob(f".{fach.manifest.name}.*"))
