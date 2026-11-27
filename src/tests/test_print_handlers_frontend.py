from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "material_ui/static"


def test_print_handler_registry_last_wins_and_unregisters():
    if not shutil.which("node"):
        pytest.skip("Node.js ist nicht installiert")
    script = f"""
import assert from 'node:assert/strict';
import {{ createPrintHandlerRegistry }} from {json.dumps((STATIC / 'print-handlers.js').as_uri())};
const registry = createPrintHandlerRegistry();
assert.equal(registry.active(), null);
assert.throws(() => registry.register({{ id: 'kaputt' }}));
const first = registry.register({{ id: 'a', print: () => true }});
const second = registry.register({{ id: 'b', print: () => false }});
assert.equal(registry.active().id, 'b');
second();
second();
assert.equal(registry.active().id, 'a');
first();
assert.equal(registry.active(), null);
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_print_button_offers_plugin_handler_before_browser_dialog():
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    body = source[source.index("async function printCurrentPdf()"):source.index("async function browserPrintPdf(url)")]
    assert body.index("printHandlers.active()") < body.index("await browserPrintPdf(url)")
    assert "if (handled !== false) return;" in body
    assert "plugin-print-handlers" in json.loads((STATIC / "api-contract.json").read_text())["capabilities"]
