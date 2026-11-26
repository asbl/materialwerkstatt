from copy import deepcopy

import pytest

from material_core import foerdermaterial as fm
from material_core import lernstand
from material_core.kompetenzen import katalog
from material_ui.config import AppConfig
from material_ui.documents import qmd_source_paths
from material_ui.errors import InvalidInput


@pytest.fixture
def offer(tmp_path):
    competencies = tmp_path / 'wissen/kompetenzraster/mathematik/teilkompetenzen'
    competencies.mkdir(parents=True)
    (competencies / 'arithmetik.md').write_text(
        '---\nkompetenzen:\n  - id: zahlen-vergleichen\n    titel: Zahlen vergleichen\n---\n')
    folder = tmp_path / 'foerdermaterial/mathematik/zahlen/basis'
    folder.mkdir(parents=True)
    (folder / 'ab_uebungen.qmd').write_text('Aufgabe 1')
    data = {'schema': 1, 'id': 'zahlen-basis', 'titel': 'Zahlen vergleichen',
            'zentrale_kompetenzen': [{'fach': 'mathematik', 'id': 'zahlen-vergleichen'}],
            'niveau': 'basis', 'aufgaben': [{'quelle': 'ab_uebungen.qmd', 'fundstelle': 'Aufgabe 1'}]}
    return tmp_path, folder, data


def test_offer_and_missing_source(offer):
    root, folder, data = offer
    assert not fm.audit(data, folder, root)['fehler']
    (folder / 'ab_uebungen.qmd').unlink()
    assert fm.audit(data, folder, root)['fehler']


def test_existing_unicode_competency_ids_are_preserved(offer):
    root, _, _ = offer
    path = root / 'wissen/kompetenzraster/mathematik/teilkompetenzen/stochastik.md'
    path.write_text('---\nkompetenzen:\n  - id: kenngrössen-bestimmen\n---\n')
    assert 'kenngrössen-bestimmen' in katalog(root, 'mathematik')


@pytest.mark.parametrize('change', ['unknown', 'duplicate', 'extra', 'duration', 'empty', 'path', 'private'])
def test_invalid_offer(offer, change):
    root, folder, data = offer
    if change == 'unknown':
        data['zentrale_kompetenzen'][0]['id'] = 'unknown'
    elif change == 'duplicate':
        data['zentrale_kompetenzen'] *= 2
    elif change == 'extra':
        data['schueler'] = 'synthetic'
    elif change == 'duration':
        data['dauer_minuten'] = True
    elif change == 'empty':
        data['aufgaben'] = []
    elif change == 'path':
        data['aufgaben'][0]['quelle'] = '/tmp/example.qmd'
    elif change == 'private':
        data['aufgaben'][0]['quelle'] = '../../../../foerderempfehlungen/example.qmd'
    with pytest.raises(ValueError):
        fm.validate(data, folder, root)


def test_offer_rejects_symlink_into_private_area(offer):
    root, folder, data = offer
    private = root / 'foerderempfehlungen'
    private.mkdir()
    target = private / 'synthetic.qmd'
    target.write_text('synthetic')
    (folder / 'link.qmd').symlink_to(target)
    data['aufgaben'][0]['quelle'] = 'link.qmd'
    with pytest.raises(ValueError):
        fm.validate(data, folder, root)


def test_catalog_rejects_duplicate_offer_ids(offer):
    from ruamel.yaml import YAML
    root, folder, data = offer
    for directory in (folder, folder / 'duplicate'):
        directory.mkdir(exist_ok=True)
        with (directory / 'angebot.yaml').open('w') as handle:
            YAML().dump(data, handle)
    with pytest.raises(ValueError, match='Doppelte Förderangebot-ID'):
        fm.catalog(root)


def test_material_editor_excludes_private_files_and_aliases(tmp_path):
    private = tmp_path / 'foerderempfehlungen'
    private.mkdir()
    (private / 'synthetic.qmd').write_text('synthetic')
    (tmp_path / 'alias').symlink_to(private, target_is_directory=True)
    (tmp_path / 'alias-file.qmd').symlink_to(private / 'synthetic.qmd')
    (tmp_path / 'public.qmd').write_text('public')
    config = AppConfig(tmp_path)
    for value in ('foerderempfehlungen/synthetic.qmd', 'alias/synthetic.qmd'):
        with pytest.raises(InvalidInput):
            config.safe_path(value)
        assert not config.is_visible(tmp_path / value)
    assert qmd_source_paths(tmp_path) == [tmp_path / 'public.qmd']


def test_local_competency_links_are_explicit_and_legacy_is_readable(offer):
    root, folder, data = offer
    teaching = root / 'unterricht/example'
    teaching.mkdir(parents=True)
    local = {'schema': 1, 'id': 'example', 'version': '1',
             'kompetenzen': [{'id': 'local', 'titel': 'Local',
                              'stufen': [{'id': 'basis', 'beschreibung': 'Basis'}]}],
             'materialien': [{'id': 'diagnose', 'rolle': 'diagnose', 'quelle': 'test.qmd'}]}
    assert any('Zuordnung zu zentralen' in w for w in lernstand.audit(local, teaching, root)['hinweise'])
    local['kompetenzen'][0]['zentrale_kompetenzen'] = deepcopy(data['zentrale_kompetenzen'])
    assert not any('Zuordnung zu zentralen' in w for w in lernstand.audit(local, teaching, root)['hinweise'])
    local['kompetenzen'][0]['zentrale_kompetenzen'][0]['id'] = 'unknown'
    with pytest.raises(lernstand.LernstandError, match='Unbekannte zentrale Kompetenz'):
        lernstand.validate(local, teaching, root)
