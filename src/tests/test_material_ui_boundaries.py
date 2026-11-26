"""Architectural invariants using small synthetic workspaces."""
import json
from pathlib import Path
import subprocess

import pytest

from material_ui.app import initialize_runtime
from material_ui.config import AppConfig
from material_ui.runtime import RuntimeState
from material_ui.material_changes import MaterialChange


@pytest.fixture
def services(tmp_path):
    runtime = RuntimeState()
    services = initialize_runtime(runtime, AppConfig(tmp_path))
    try:
        yield services, tmp_path
    finally:
        runtime.close()


def test_index_search_and_units_do_not_write_sources(services):
    app, root = services
    folder = root / 'unterricht/mathematik/klasse-7/thema'
    folder.mkdir(parents=True)
    source = folder / 'ab_loesung.qmd'
    original = '---\ntitle: Test\n---\nText\n'
    source.write_text(original)
    stamp = source.stat().st_mtime_ns
    entries = app.documents.all_entries()
    assert entries[0]['kind'] == 'Lösung'
    assert entries[0]['tags'] == ['Lösung']
    app.search.search('Test')
    app.units.overview()
    assert source.read_text() == original
    assert source.stat().st_mtime_ns == stamp
    assert not (folder / '.material-history').exists()
    assert app.files.repair_solution_metadata()['changed'] == [source.relative_to(root).as_posix()]
    assert app.files.repair_solution_metadata()['changed'] == []


def test_mutations_notify_only_after_success_and_keep_shared_services(services):
    app, root = services
    source = root / 'notiz_test.md'
    source.write_text('---\nkind: Notiz\n---\nTest')
    changes = []
    unsubscribe = app.changes.subscribe(changes.append)
    assert app.files.units is app.units is app.folders.units
    assert app.documents.all_entries()[0]['path'] == source.name
    with pytest.raises(ValueError):
        app.files.rename(source.name, 'hinweise.md')
    assert source.exists()
    assert changes == []
    target = app.files.rename(source.name, 'notiz_neu.md')
    assert MaterialChange('moved', (source, target)) in changes
    assert MaterialChange('invalidated') in changes
    assert app.documents.all_entries()[0]['path'] == target.name
    app.files.delete(target.name)
    assert app.documents.all_entries() == []
    unsubscribe()


def test_failed_reference_update_rolls_back_file_and_emits_nothing(services, monkeypatch):
    from contextlib import contextmanager
    app, root = services
    source = root / 'ab_test.qmd'
    source.write_text('Test')
    changes = []
    app.changes.subscribe(changes.append)
    @contextmanager
    def fail(*args):
        yield
        raise OSError('reference write failed')
    monkeypatch.setattr(app.units, 'reference_updates', fail)
    with pytest.raises(OSError):
        app.files.rename(source.name, 'ab_neu.qmd')
    assert source.read_text() == 'Test'
    assert not (root / 'ab_neu.qmd').exists()
    assert changes == []


def test_frontend_owners_reject_stale_loads_and_preserve_search():
    static = Path(__file__).resolve().parents[1] / 'material_ui/static'
    script = '''
import assert from 'node:assert/strict';
import {createDocumentState} from DOC;
import {createSearchState} from SEARCH;
const state = {session:0, documentLoad:0};
const documents = createDocumentState(state);
const old = documents.begin();
const current = documents.begin();
assert.equal(documents.accept({path:'old'}, old), false);
assert.equal(documents.accept({path:'new', text:'text', revision:'r'}, current), true);
assert.equal(documents.snapshot().path, 'new');
documents.close();
assert.equal(documents.accept({path:'new'}, current), false);
assert.equal(documents.snapshot().path, '');
let context = 'tagTree';
const elements = {documentSearch:{value:''}, tagSearch:{value:''}};
const search = createSearchState({elements, getContext:()=>context});
search.setQuery('Bruch');
search.displayDocument('Arbeitsblatt');
search.closeDocument();
assert.equal(search.query(), 'Bruch');
assert.equal(elements.documentSearch.value, 'Bruch');
context = 'folder';
search.activate('global');
search.setQuery('Prozent');
search.displayDocument('AB Prozent');
assert.equal(search.query(), '');
assert.equal(search.query('tagTree'), 'Bruch');
context = 'tagTree';
search.activate('tagTree');
assert.equal(elements.documentSearch.value, 'Bruch');
'''.replace('DOC', json.dumps((static / 'document-state.js').as_uri())).replace('SEARCH', json.dumps((static / 'search-state.js').as_uri()))
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_workspace_modes_serialize_transitions_and_recover_from_failure():
    module = (Path(__file__).resolve().parents[1] / 'material_ui/static/workspace-modes.js').as_uri()
    script = '''
import assert from 'node:assert/strict';
import {createWorkspaceModeRegistry} from MODULE;
const modes = createWorkspaceModeRegistry();
const calls = [];
let release;
const gate = new Promise(resolve => release = resolve);
const first = {id:'one', enter:async entry=>{ calls.push(entry); if(entry==='a') await gate; }, leave:()=>calls.push('leave')};
modes.register(first);
const pending = modes.enter(first, 'a');
const next = modes.enter(first, 'b');
await Promise.resolve();
assert.deepEqual(calls, ['a']);
release();
await Promise.all([pending,next]);
assert.deepEqual(calls, ['a','b']);
const broken = {id:'broken', enter:()=>{throw new Error('failed')}, leave:()=>calls.push('cleanup')};
await assert.rejects(modes.enter(broken), /failed/);
assert.equal(modes.active(), null);
assert.deepEqual(calls, ['a','b','leave','cleanup']);
await modes.enter(first,'c');
assert.equal(modes.activeId(), 'one');
await modes.leave();
assert.equal(modes.active(), null);
'''.replace('MODULE', json.dumps(module))
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_course_service_creation_does_not_wait_for_workspace_lock(tmp_path):
    import threading
    from course_sync.application import CourseApplication
    from course_sync.config import settings
    application = CourseApplication(settings.build_app_config().with_root(tmp_path))
    ready, release = threading.Event(), threading.Event()
    def prepare():
        with application.WORKSPACE_LOCK:
            ready.set()
            release.wait(5)
    worker = threading.Thread(target=prepare)
    worker.start()
    try:
        assert ready.wait(2)
        completed = threading.Event()
        result = []
        def read_service():
            result.append(application.mdx_course_parser())
            completed.set()
        reader = threading.Thread(target=read_service)
        reader.start()
        try:
            assert completed.wait(2), 'Read-service construction blocked behind workspace preparation'
        finally:
            release.set()
            reader.join(5)
        assert result[0] is application.mdx_course_parser()
    finally:
        release.set()
        worker.join(5)
