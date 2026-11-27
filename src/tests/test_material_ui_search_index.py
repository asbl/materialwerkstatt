from __future__ import annotations

import json
from pathlib import Path

import pytest
import pymupdf

from material_ui.app import create_app
from material_ui.config import AppConfig


@pytest.fixture
def application(tmp_path):
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    yield app
    app.extensions['material_runtime'].close()


def write_source(root, name, body='Wurzel', header='title: Blatt'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'---\n{header}\n---\n\n{body}\n')
    return path


def test_search_ranks_all_sources_and_decks_before_limiting(application, tmp_path):
    for number in range(51):
        write_source(tmp_path, f'{number:03}.qmd', 'Wurzel ' * (100 if number == 50 else 1))
    (tmp_path / 'last.excalidraw').write_text(json.dumps({'elements': [{'type': 'text', 'text': 'Wurzel ' * 200}]}))
    results = application.test_client().get('/api/search?q=wurzel').json['results']
    assert len(results) == 50
    assert [item['path'] for item in results[:2]] == ['last.excalidraw', '050.qmd']


def test_index_reuses_text_and_metadata_and_tracks_external_changes(application, tmp_path, monkeypatch):
    first = write_source(tmp_path, 'a.qmd', 'Wurzel')
    second = write_source(tmp_path, 'b.qmd', 'Wurzel')
    reads = []
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path.suffix == '.qmd':
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read)
    client = application.test_client()
    assert len(client.get('/api/search?q=wurzel').json['results']) == 2
    assert reads.count(first) == reads.count(second) == 1
    reads.clear()
    assert len(client.get('/api/search?q=wurzel').json['results']) == 2
    assert reads == []
    first.write_text('---\ntitle: Neu\n---\nPotenzen\n')
    assert [hit['path'] for hit in client.get('/api/search?q=wurzel').json['results']] == ['b.qmd']
    assert reads == [first]
    second.rename(tmp_path / 'c.qmd')
    assert [hit['path'] for hit in client.get('/api/search?q=wurzel').json['results']] == ['c.qmd']
    (tmp_path / 'c.qmd').unlink()
    assert client.get('/api/search?q=wurzel').json['results'] == []
    index = application.extensions['material_runtime'].services.search.index
    assert index.db.execute('SELECT path FROM files').fetchall() == [('a.qmd',)]


def test_index_refreshes_pdf_presence_without_rereading_source(application, tmp_path, monkeypatch):
    source = write_source(tmp_path, 'ab.qmd', header='title: Blatt\nformat:\n  pdf:\n    output-file: custom.pdf')
    client = application.test_client()
    assert client.get('/api/search?q=wurzel&pdf=with-pdf').json['results'] == []
    pdf = tmp_path / 'build/pdf/custom.pdf'
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b'%PDF')
    original = Path.read_text

    def read(path, *args, **kwargs):
        assert path != source, 'unchanged source must not be reread'
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read)
    assert client.get('/api/search?q=wurzel&pdf=with-pdf').json['results'][0]['pdf'] == 'build/pdf/custom.pdf'
    pdf.unlink()
    assert client.get('/api/search?q=wurzel&pdf=with-pdf').json['results'] == []


def test_generated_decks_inherit_source_facets_without_walking_build(application, tmp_path, monkeypatch):
    source = write_source(tmp_path, 'unterricht/mathe/klasse-07/slide.qmd', 'Keine Treffer', 'title: Folien\ntags: [mathe]')
    deck = tmp_path / 'build/artefakte' / source.relative_to(tmp_path).with_suffix('.excalidraw')
    deck.parent.mkdir(parents=True)
    deck.write_text(json.dumps({'elements': [{'type': 'text', 'text': 'Quadratwurzel'}]}))
    ignored = tmp_path / 'build/site/ignored.excalidraw'
    ignored.parent.mkdir(parents=True)
    ignored.write_text(deck.read_text())
    import material_ui.catalog as catalog_module
    original = catalog_module.os.walk

    def walk(root):
        for directory, children, files in original(root):
            assert Path(directory) != tmp_path / 'build'
            yield directory, children, files

    monkeypatch.setattr(catalog_module.os, 'walk', walk)
    results = application.test_client().get('/api/search?q=wurzel&subject=mathe&grade=klasse-07&tags=mathe&kind=Deck').json['results']
    assert [hit['path'] for hit in results] == [str(deck.relative_to(tmp_path))]
    assert results[0]['source_path'] == str(source.relative_to(tmp_path))


def test_index_ignores_deleted_deck_elements_and_outside_symlinks(application, tmp_path):
    outside = tmp_path.parent / 'outside.qmd'
    outside.write_text('Wurzel')
    (tmp_path / 'escape.qmd').symlink_to(outside)
    (tmp_path / 'deleted.excalidraw').write_text(json.dumps({'elements': [{'type': 'text', 'text': 'Wurzel', 'isDeleted': True}]}))
    assert application.test_client().get('/api/search?q=wurzel').json['results'] == []


def test_search_pdf_filters_solution_and_sorting(application, tmp_path):
    write_source(tmp_path, 'ab.qmd', header='title: Zebra')
    source = write_source(tmp_path, 'ab-loesung.qmd', header='title: Alpha')
    source.with_suffix('.pdf').write_bytes(b'%PDF')
    client = application.test_client()
    assert [hit['title'] for hit in client.get('/api/search?q=wurzel&sort=title').json['results']] == ['Alpha', 'Zebra']
    assert [hit['path'] for hit in client.get('/api/search?q=wurzel&solution=true&pdf=with-pdf').json['results']] == ['ab-loesung.qmd']
    assert [hit['path'] for hit in client.get('/api/search?q=wurzel&pdf=without-pdf').json['results']] == ['ab.qmd']


def test_index_skips_oversized_sources_and_does_not_serve_previous_text(application, tmp_path, monkeypatch):
    import material_ui.search as search_module
    monkeypatch.setattr(search_module, 'MAX_SEARCH_BYTES', 500)
    client = application.test_client()
    write_source(tmp_path, 'a.qmd', 'Wurzel')
    assert client.get('/api/search?q=wurzel').json['results']
    write_source(tmp_path, 'a.qmd', 'Wurzel ' * 200)
    assert client.get('/api/search?q=wurzel').json['results'] == []


def test_index_detects_later_created_explicit_deck_link(application, tmp_path):
    write_source(tmp_path, 'unterricht/mathe/ab.qmd', 'Andere Inhalte', 'title: Blatt\ndeck: build/custom.excalidraw\ntags: [mathe]')
    client = application.test_client()
    assert client.get('/api/search?q=wurzel').json['results'] == []
    deck = tmp_path / 'build/custom.excalidraw'
    deck.parent.mkdir()
    deck.write_text(json.dumps({'elements': [{'type': 'text', 'text': 'Wurzel'}]}))
    assert [hit['path'] for hit in client.get('/api/search?q=wurzel&tags=mathe').json['results']] == ['build/custom.excalidraw']


def test_search_snippet_positions_survive_umlaut_expansion(application, tmp_path):
    write_source(tmp_path, 'a.qmd', 'ä' * 200 + ' Wurzel')
    result = application.test_client().get('/api/search?q=wurzel').json['results'][0]
    assert 'Wurzel' in result['snippet']


def write_original_pdf(root, name, *pages):
    path = root / 'wissen' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as pdf:
        for text in pages:
            pdf.new_page().insert_text((72, 72), text)
        pdf.save(path)
    return path


def test_original_pdfs_share_search_and_link_to_best_page(application, tmp_path):
    write_source(tmp_path, 'a.qmd', 'Brüche')
    pdf_name = 'arbeitsblatt/mathematik/klasse-06/thema/Quelle & Übungen.pdf'
    pdf = write_original_pdf(tmp_path, pdf_name, 'Brüche', 'Brüche addieren und Brüche vergleichen')
    write_original_pdf(tmp_path, 'nicht-erschlossen.pdf', 'Brüche addieren')
    (tmp_path / 'wissen/_pdf-erschliessung.json').write_text(json.dumps({
        'eintraege': {'known': {'pfad': pdf_name}, 'invalid': {'pfad': '../other.pdf'}},
    }))
    client = application.test_client()
    response = client.get('/api/search?q=brueche')
    assert response.json['sourceErrors'] == []
    assert response.json['sources'] == [{'id': 'original-pdf', 'name': 'Original-PDFs'}]
    source, qmd = response.json['results']
    name = pdf.relative_to(tmp_path).as_posix()
    assert source['path'] == source['pdf'] == name
    assert source['page'] == 2 and 'addieren' in source['snippet']
    assert qmd['path'] == 'a.qmd'
    assert client.get('/api/pdf', query_string={'path': name}).mimetype == 'application/pdf'
    assert client.get('/api/search?q=brueche&pdf=without-pdf').json['results'] == [qmd]
    assert client.get('/api/search?q=brueche&subject=mathematik&grade=klasse-06').json['results'] == [source]
    pdf.unlink()
    assert client.get('/api/search?q=brueche').json['results'] == [qmd]


def test_search_index_reuses_qmd_and_pdf_text_after_restart(tmp_path, monkeypatch):
    source = write_source(tmp_path, 'a.qmd', 'Brüche')
    write_original_pdf(tmp_path, 'quelle.pdf', 'Brüche')
    (tmp_path / 'wissen/_pdf-erschliessung.json').write_text(json.dumps({
        'eintraege': {'pdf': {'pfad': 'quelle.pdf'}},
    }))
    first = create_app(config=AppConfig(tmp_path))
    try:
        hits = first.test_client().get('/api/search?q=brueche').json['results']
        assert len(hits) == 2
    finally:
        _runtime(first).close()

    from material_ui.search import SearchService

    restarted = create_app(config=AppConfig(tmp_path))
    try:
        with monkeypatch.context() as patch:
            def unexpected(*args):
                pytest.fail('Unveränderte Quelle erneut indexiert')

            patch.setattr(SearchService, 'load_source', unexpected)
            patch.setattr(SearchService, 'load_pdf', unexpected)
            assert restarted.test_client().get('/api/search?q=brueche').json['results'] == hits
        source.write_text('Terme vereinfachen')
        assert [hit['path'] for hit in restarted.test_client().get('/api/search?q=brueche').json['results']] == ['wissen/quelle.pdf']
    finally:
        _runtime(restarted).close()


# -- Such-Provider (Plugin-Schnittstelle ctx.search) ---------------------------------------------------


def _runtime(app):
    return app.extensions['material_runtime']


def test_search_providers_merge_tag_and_cap_results(application, tmp_path):
    write_source(tmp_path, 'a.qmd', 'Wurzel')
    search = _runtime(application).services.search

    def provider(query, filters):
        assert query == 'wurzel' and filters['sort'] == 'relevance'
        return [
            {'path': 'wissen/extern/quelle.pdf', 'title': 'Externe Quelle', 'snippet': 'Wurzel', 'score': 5, 'pdf': 'wissen/extern/quelle.pdf'},
            {'path': 'wissen/extern/defekt', 'score': 1},  # ohne title: Stem als Titel
            {'kein': 'pfad'},  # ungueltig, wird verworfen
            'kaputt',
        ]

    unregister = search.register_provider(provider, source_id='extern', name='Externe Quelle')
    client = application.test_client()
    data = client.get('/api/search?q=wurzel').json
    assert data['sources'] == [{'id': 'extern', 'name': 'Externe Quelle'}]
    assert data['sourceErrors'] == []
    paths = [item['path'] for item in data['results']]
    assert 'a.qmd' in paths and 'wissen/extern/quelle.pdf' in paths and 'wissen/extern/defekt' in paths
    extern = next(item for item in data['results'] if item['path'] == 'wissen/extern/quelle.pdf')
    assert extern['source'] == 'extern' and extern['title'] == 'Externe Quelle' and extern['score'] == 5
    assert extern['pdf'] == 'wissen/extern/quelle.pdf'
    stem = next(item for item in data['results'] if item['path'] == 'wissen/extern/defekt')
    assert stem['title'] == 'defekt' and stem['source'] == 'extern'
    # Kerntreffer bleiben ohne source-Feld.
    assert next(item for item in data['results'] if item['path'] == 'a.qmd').get('source') is None
    unregister()
    unregister()  # idempotent
    assert application.test_client().get('/api/search?q=wurzel').json['sources'] == []


def test_search_provider_errors_are_isolated(application, tmp_path):
    write_source(tmp_path, 'a.qmd', 'Wurzel')
    search = _runtime(application).services.search

    def broken(query, filters):
        raise RuntimeError('kaputt')

    search.register_provider(broken, source_id='broken', name='Kaputt')
    search.register_provider(lambda q, f: [{'path': 'wissen/x.pdf', 'title': 'X'}], source_id='ok')
    data = application.test_client().get('/api/search?q=wurzel').json
    assert [item['path'] for item in data['results']] == ['a.qmd', 'wissen/x.pdf']
    assert data['sourceErrors'] == [{'source': 'broken', 'name': 'Kaputt', 'message': 'kaputt'}]
    assert {s['id'] for s in data['sources']} == {'broken', 'ok'}


def test_search_provider_registration_validates_input(application):
    search = _runtime(application).services.search
    with pytest.raises(ValueError):
        search.register_provider(lambda q, f: [], source_id='Bad ID!')
    with pytest.raises(ValueError):
        search.register_provider('nicht-aufrufbar', source_id='x')
    assert search.provider_sources() == []


def test_plugin_search_port_exposes_registry(application, tmp_path):
    from material_ui.plugins.ports import PluginSearch

    runtime = _runtime(application)
    ctx = runtime.plugins.contexts['kalender']
    port = PluginSearch(runtime.services.search)
    assert port.available
    unregister = port.register(lambda q, f: [{'path': 'wissen/y.pdf', 'title': 'Y'}], source_id='port', name='Port')
    assert port.sources() == [('port', 'Port')]
    assert application.test_client().get('/api/search?q=irgendwas').json['sources'] == [{'id': 'port', 'name': 'Port'}]
    unregister()
    assert PluginSearch(None).available is False
    assert PluginSearch(None).sources() == []
    with pytest.raises(RuntimeError):
        PluginSearch(None).register(lambda q, f: [], source_id='x')
