import json
import shutil
import subprocess
from pathlib import Path

import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.protocol import API_VERSION, CAPABILITIES


def test_protocol_endpoint_matches_shared_contract(tmp_path):
    app = create_app(config=AppConfig(tmp_path))
    try:
        response = app.test_client().get('/api/protocol')
        contract = json.loads((Path(__file__).resolve().parents[1] / 'material_ui/static/api-contract.json').read_text())
        assert response.status_code == 200
        assert response.json == contract == {'apiVersion': API_VERSION, 'capabilities': list(CAPABILITIES)}
    finally:
        app.extensions['material_runtime'].close()


def test_client_checks_version_and_capabilities_before_writing():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node fehlt')
    static = Path(__file__).resolve().parents[1] / 'material_ui/static'
    result = subprocess.run([node, '--input-type=module', '-e', f'''
import assert from 'node:assert/strict';
import {{api}} from {json.dumps((static / 'api.js').as_uri())};
import {{validateProtocol}} from {json.dumps((static / 'protocol.js').as_uri())};
const contract = {{apiVersion: 1, capabilities: ['document-slides', 'layout-diagnostics']}};
validateProtocol(contract, {{...contract, capabilities: [...contract.capabilities, 'future']}});
for (const server of [{{...contract, apiVersion: 2}}, {{...contract, capabilities: []}}, null]) {{
  assert.throws(() => validateProtocol(contract, server), error => error.status === 426);
}}
globalThis.document = {{querySelector: () => ({{content: 'token'}})}};
let writes = 0;
let checks = 0;
let server = {{...contract, capabilities: []}};
globalThis.fetch = async (url, options) => {{
  if (url === '/static/api-contract.json') return Response.json(contract);
  if (url === '/api/protocol') {{ checks++; return Response.json(server); }}
  // The server rejects a cached incompatible contract before executing the write.
  if (url !== '/api/server/restart' && (
      options.headers['X-Material-API-Version'] !== String(server.apiVersion) ||
      options.headers['X-Material-Capabilities'].split(',').some(c => !server.capabilities.includes(c)))) {{
    return Response.json({{error: {{message: 'incompatible'}}}}, {{status: 426}});
  }}
  writes++;
  return Response.json({{hasSlides: true, isPresentation: false, renderNeeded: false}});
}};
await assert.rejects(api('/api/document', {{method: 'POST', body: '{{}}'}}), error => error.status === 426);
assert.equal(writes, 0);
server = contract;
await api('/api/document', {{method: 'POST', body: '{{}}'}});
assert.equal(writes, 1);
await Promise.all([api('/api/window/heartbeat', {{method: 'POST'}}), api('/api/window/heartbeat', {{method: 'POST'}})]);
assert.equal(checks, 2); // Failed first handshake plus one successful handshake.
assert.equal(writes, 3);
server = {{...contract, apiVersion: 3}};
await assert.rejects(api('/api/document', {{method: 'POST', body: '{{}}'}}), error => error.status === 426);
assert.equal(writes, 3);
// Ein Serverneustart bleibt trotz Versionskonflikt möglich.
await api('/api/server/restart', {{method: 'POST'}});
assert.equal(writes, 4);
'''], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_browser_shows_protocol_mismatch_and_can_recover_after_reload(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    (tmp_path / 'blatt.qmd').write_text('---\ntitle: Protokolltest\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.route('**/api/protocol', lambda route: route.fulfill(json={'apiVersion': API_VERSION, 'capabilities': []}))
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#renderStatus').textContent.includes('nicht kompatibel')")
            page.locator('#headerMenuToggle').click()
            assert page.locator('#restartServer').is_visible()
            page.unroute('**/api/protocol')
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function("window.materialEditor.getText().includes('Protokolltest')")
            browser.close()
    finally:
        app.extensions['material_runtime'].close()
