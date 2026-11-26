from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


STATIC = Path(__file__).resolve().parents[1] / 'material_ui/static'


def run_node(script):
    if not shutil.which('node'):
        pytest.skip('Node.js ist nicht installiert')
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_picker_filters_merges_sorts_and_rejects_outdated_search_responses():
    run_node(r'''
import assert from 'node:assert/strict';
import {createPickerController} from MODULE;
import {createFulltextState} from FULLTEXT;
const fulltext = createFulltextState();
const state = {qmds: [
  {path:'a.qmd',title:'Wurzel A',subject:'mathe',area:'unterricht',kind:'Arbeitsblatt',pdf:'a.pdf',mtime:1},
  {path:'b.qmd',title:'Wurzel B',subject:'info',area:'unterricht',kind:'Arbeitsblatt',pdf:null,mtime:2}
], qmdPath:'',activeFilter:'alle', activeResult:0,facetFilters:{subject:'',grade:'',kind:'',tag:'',pdf:'',sort:'title'}};
const container = {innerHTML:'',setAttribute(){},removeAttribute(){},querySelectorAll(){return []}};
const input = {value:'wurzel'};
const calls = [];
const controller = createPickerController({uiIcon:name=>`<svg data-icon="${name}"></svg>`,state,fulltext,elements:{documentSearch:input,documentResults:container},escapeHtml:String,normalizeSearch:s=>s.toLowerCase(),selectDocument(){},api: (url, options) => new Promise(resolve=>calls.push({url,options,resolve}))});
fulltext.results = [{path:'c.qmd',title:'A weiterer Treffer',subject:'mathe',area:'unterricht',kind:'Arbeitsblatt',pdf:'c.pdf',mtime:3,score:2,snippet:'wurzel',line:5}];
controller.renderDocumentResults(true);
assert.deepEqual(state.filteredQmds.map(x=>x.path), ['c.qmd','a.qmd','b.qmd']);
state.facetFilters.subject='mathe';
state.facetFilters.pdf='with-pdf';
controller.renderDocumentResults(true);
assert.deepEqual(state.filteredQmds.map(x=>x.path), ['c.qmd','a.qmd']);
state.activeFilter='subject:info';
controller.renderDocumentResults(true);
assert.deepEqual(state.filteredQmds, []);
state.activeFilter='alle';
let timer;
globalThis.setTimeout = handler => {timer=handler;return 1};
globalThis.clearTimeout = ()=>{};
controller.scheduleFulltextSearch();
const first = timer();
assert.ok(calls[0].url.includes('pdf=with-pdf'));
input.value='po';
controller.scheduleFulltextSearch();
assert.ok(calls[0].options.signal.aborted);
calls[0].resolve({results:[{path:'outdated.qmd',title:'Falscher Treffer',subject:'mathe',pdf:'old.pdf'}]});
await first;
assert.deepEqual(fulltext.results, []);
input.value='potenz';
controller.scheduleFulltextSearch();
const second = timer();
state.facetFilters.subject='info';
controller.scheduleFulltextSearch();
const third = timer();
calls[2].resolve({results:[{path:'new.qmd',title:'Potenzen',subject:'info',pdf:'new.pdf',score:3}]});
await third;
calls[1].resolve({results:[{path:'old.qmd',title:'Alt',subject:'mathe',pdf:'old.pdf'}]});
await second;
assert.deepEqual(state.filteredQmds.map(x=>x.path), ['new.qmd']);
'''.replace('MODULE', json.dumps((STATIC / 'picker.js').as_uri()))
       .replace('FULLTEXT', json.dumps((STATIC / 'fulltext-state.js').as_uri())))


def test_render_diagnostics_only_use_matching_qmd_source_lines():
    run_node(r'''
import assert from 'node:assert/strict';
import {renderDiagnostics} from MODULE;
const issues=renderDiagnostics({log:'ab.qmd:5:3 error\nother.qmd:99 error\nbuild/ab.tex:200 error\nWarnung ab.qmd:8:2 warning\nmaterial-ui-render-token.qmd:4 error'},'unterricht/ab.qmd');
assert.deepEqual(issues.map(x=>[x.line,x.column,x.level]),[[5,3,'error'],[8,2,'warning'],[4,1,'error']]);
'''.replace('MODULE', json.dumps((STATIC / 'diagnostics.js').as_uri())))


def test_search_normalization_matches_umlauts_and_alternative_spelling():
    run_node(r'''
import assert from 'node:assert/strict';
import {normalizeSearch} from MODULE;
assert.equal(normalizeSearch('Größen'), normalizeSearch('Groessen'));
assert.equal(normalizeSearch('Café'), normalizeSearch('cafe'));
'''.replace('MODULE', json.dumps((STATIC / 'ui-utils.js').as_uri())))


def test_diagnostics_ignore_delayed_answers_after_document_changes():
    run_node(r'''
import assert from 'node:assert/strict';
import {createDiagnosticsController} from MODULE;
const node=()=>({hidden:true,textContent:'',replaceChildren(){},append(){},addEventListener(){}});
globalThis.document={getElementById:node,createElement:node};
let text='Text A',displayed=[];
const state={qmdPath:'a.qmd',session:1,revision:'a',dirty:false,course:{kursMode:false}};
const requests=[];
const editor={getEditorText:()=>text,setDiagnostics:issues=>{displayed=issues},jumpToLine(){},focus(){}};
const controller=createDiagnosticsController({state,editor,setStatus(){},api:(url,options)=>url==='/api/check'?new Promise(resolve=>requests.push({options,resolve})):Promise.resolve({issues:[],status:''})});
const first=controller.check();
state.qmdPath='b.qmd';state.session++;state.revision='b';text='Text B';
const second=controller.check();
assert.ok(requests[0].options.signal.aborted);
requests[1].resolve({issues:[{level:'warning',title:'B',detail:'Nur B',line:2}]});
await second;
requests[0].resolve({issues:[{level:'error',title:'A',detail:'Veraltet',line:1}]});
await first;
assert.deepEqual(displayed.map(x=>x.title),['B']);
controller.updateRender({current:'b.qmd',running:false,detail:{source_revision:'old',log:'b.qmd:1 error'}});
assert.deepEqual(displayed.map(x=>x.title),['B']);
'''.replace('MODULE', json.dumps((STATIC / 'diagnostics.js').as_uri())))


def test_background_diagnostics_cannot_cancel_render_preflight():
    run_node(r'''
import assert from 'node:assert/strict';
import {createDiagnosticsController} from MODULE;
const node=()=>({hidden:true,textContent:'',replaceChildren(){},append(){},addEventListener(){}});
globalThis.document={getElementById:node,createElement:node};
const state={qmdPath:'klausur.qmd',session:1,course:{kursMode:false}};
const requests=[];
const controller=createDiagnosticsController({state,
  editor:{getEditorText:()=> 'Klausur',setDiagnostics(){}},setStatus(){},
  api:(url,options)=>url==='/api/check'?new Promise(resolve=>requests.push({options,resolve})):Promise.resolve({issues:[],status:''})});
const preflight=controller.check({beforeRender:true});
const background=controller.check();
assert.equal(requests[0].options.signal.aborted,false);
requests[1].resolve({issues:[]});
await background;
requests[0].resolve({issues:[]});
assert.equal(await preflight,true,'Background check must not silently stop rendering');
// A document switch still invalidates the preflight result.
const outdated=controller.check({beforeRender:true});
state.session++;
requests[2].resolve({issues:[]});
assert.equal(await outdated,false);
'''.replace('MODULE', json.dumps((STATIC / 'diagnostics.js').as_uri())))


@pytest.mark.parametrize('failure', ['preflight', 'check-network', 'save', 'render-network'])
def test_failed_render_start_clears_pending_pdf_message(failure):
    run_node(r'''
import assert from 'node:assert/strict';
import {createRenderPanelController} from MODULE;
const failure=FAILURE;
const state={qmdPath:'klausur.qmd',session:1,course:{kursMode:false},loadedPdf:''};
const elements={pdfEmptyState:{textContent:'PDF-Vorschau wird erstellt …'},pdfRenderingOverlay:{hidden:false}};
let submitted=false;
const controller=createRenderPanelController({state,elements,setStatus(){},
  beforeRender:async()=>{if(failure==='check-network') throw new Error('offline');return failure!=='preflight';},
  flushPendingSave:async()=>{if(failure==='save') throw new Error('Speichern fehlgeschlagen');},
  api:async()=>{submitted=true;throw new Error('offline');}});
await controller.renderDocument();
assert.notEqual(elements.pdfEmptyState.textContent,'PDF-Vorschau wird erstellt …');
assert.match(elements.pdfEmptyState.textContent,/konnte nicht|fehlgeschlagen/);
assert.equal(elements.pdfRenderingOverlay.hidden,true);
assert.equal(submitted,failure==='render-network');
'''.replace('MODULE', json.dumps((STATIC / 'render-panel.js').as_uri())).replace('FAILURE', json.dumps(failure)))


def test_shared_solution_pairs_with_each_explicit_worksheet():
    run_node(r'''
import assert from 'node:assert/strict';
import {pairMaterialEntries} from MODULE;
const entries = [
  {path:'unit/ab_mini.qmd', loesung:'ab_loesungen.qmd'},
  {path:'unit/ab_potenzen.qmd', loesung:'ab_loesungen.qmd'},
  {path:'unit/ab_loesungen.qmd', solution:true},
  {path:'unit/ab_zehner.qmd'},
  {path:'unit/ab_zehner-loesungen.qmd', solution:true},
  {path:'other/ab_loesungen.qmd', solution:true},
];
const groups = pairMaterialEntries(entries);
assert.deepEqual(groups.map(group => group.entry.path), ['unit/ab_mini.qmd', 'unit/ab_potenzen.qmd', 'unit/ab_zehner.qmd', 'other/ab_loesungen.qmd']);
assert.deepEqual(groups.map(group => group.solutions.map(entry => entry.path)), [['unit/ab_loesungen.qmd'], ['unit/ab_loesungen.qmd'], ['unit/ab_zehner-loesungen.qmd'], []]);
const automatic = pairMaterialEntries([{path:'ab_x.qmd'}, {path:'ab_x-loesung.qmd', solution:true}, {path:'ab_x_loesungen.qmd', solution:true}]);
assert.equal(automatic[0].solutions.length, 2);
const missing = pairMaterialEntries([{path:'ab_x.qmd', loesung:'missing.qmd'}, {path:'ab_x-loesung.qmd', solution:true}]);
assert.equal(missing[0].solutions.length, 1);
'''.replace('MODULE', json.dumps((STATIC / 'ui-utils.js').as_uri())))


def test_note_resolution_includes_solutions_and_prefers_canonical_path():
    run_node(r'''
import assert from 'node:assert/strict';
import {worksheetNotesFor} from MODULE;
const entries = [
  {path:'unit/ab_test.qmd'},
  {path:'unit/ab_test-loesung.qmd', solution:true},
  {path:'unit/ab_test-notiz.md', kind:'Notiz'},
  {path:'unit/ab_test-notizen.md', kind:'Notiz'},
  {path:'unit/ab_test-loesung_notiz.md', kind:'Notiz'},
  {path:'other/ab_test-notizen.md', kind:'Notiz'},
  {path:'unit/ab_test_notiz.md', kind:'Datei'},
];
assert.deepEqual(worksheetNotesFor(entries, 'unit/ab_test.qmd').map(e=>e.path),
  ['unit/ab_test-notizen.md', 'unit/ab_test-notiz.md']);
assert.deepEqual(worksheetNotesFor(entries, 'unit/ab_test-loesung.qmd').map(e=>e.path),
  ['unit/ab_test-loesung_notiz.md']);
assert.deepEqual(worksheetNotesFor(entries, 'unit/ab_other.qmd'), []);
'''.replace('MODULE', json.dumps((STATIC / 'ui-utils.js').as_uri())))


def test_search_provider_registry_merges_isolates_and_unsubscribes():
    run_node(r'''
import assert from 'node:assert/strict';
import {createSearchProviderRegistry} from MODULE;
const registry = createSearchProviderRegistry();
const unregister = registry.register((query, filters) => {
  assert.equal(query, 'wurzel');
  assert.equal(filters.sort, 'title');
  return [{path: 'wissen/a.pdf', title: 'A', score: 3}, {path: 'wissen/b.pdf'}, {kein: 'pfad'}, 'kaputt'];
}, 'extern', 'Externe Quelle');
registry.register(() => { throw new Error('kaputt'); }, 'broken');
const {results, errors} = registry.run('wurzel', {sort: 'title'});
assert.deepEqual(results.map(r => [r.path, r.source, r.score, r.title]), [['wissen/a.pdf', 'extern', 3, 'A'], ['wissen/b.pdf', 'extern', 0, 'b.pdf']]);
assert.deepEqual(errors.map(e => [e.source, e.name, e.message]), [['broken', 'broken', 'kaputt']]);
assert.deepEqual(registry.sources(), [{id: 'extern', name: 'Externe Quelle'}, {id: 'broken', name: 'broken'}]);
unregister(); unregister();
assert.deepEqual(registry.sources(), [{id: 'broken', name: 'broken'}]);
assert.throws(() => registry.register('keine-funktion', 'x'));
'''.replace('MODULE', json.dumps((STATIC / 'search-providers.js').as_uri())))


def test_picker_merges_local_plugin_search_providers_after_api_results():
    run_node(r'''
import assert from 'node:assert/strict';
import {createPickerController} from PICKER;
import {createSearchProviderRegistry} from PROVIDERS;
import {createFulltextState} from FULLTEXT;
const fulltext = createFulltextState();
const state = {qmds: [], qmdPath: '', activeFilter: 'alle', activeResult: 0,
  facetFilters: {subject:'',grade:'',kind:'',tag:'',pdf:'',sort:'relevance'}};
const container = {innerHTML:'',setAttribute(){},removeAttribute(){},querySelectorAll(){return []}};
const input = {value:'wurzel'};
let timer;
globalThis.setTimeout = handler => {timer=handler;return 1};
globalThis.clearTimeout = ()=>{};
const registry = createSearchProviderRegistry();
registry.register(() => [{path:'wissen/extern/x.pdf', title:'Extern', score:4, snippet:'wurzel Treffer'}], 'extern', 'Extern');
const controller = createPickerController({search: {query: () => input.value}, searchProviders: registry, state, fulltext,
  elements:{documentSearch:input,documentResults:container},escapeHtml:String,uiIcon:()=> '',
  normalizeSearch:s=>s.toLowerCase(),selectDocument(){},api: async () => ({results: [], sources: []})});
controller.scheduleFulltextSearch();
await timer();
assert.deepEqual(fulltext.results.map(r=>[r.path, r.source]), [['wissen/extern/x.pdf','extern']]);
assert.deepEqual(fulltext.sources, [{id:'extern',name:'Extern'}]);
assert.deepEqual(state.filteredQmds.map(x=>x.path), ['wissen/extern/x.pdf']);
'''.replace('PICKER', json.dumps((STATIC / 'picker.js').as_uri()))
       .replace('PROVIDERS', json.dumps((STATIC / 'search-providers.js').as_uri()))
       .replace('FULLTEXT', json.dumps((STATIC / 'fulltext-state.js').as_uri())))
