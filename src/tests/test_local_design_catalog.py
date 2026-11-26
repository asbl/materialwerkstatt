import json
from material_core.designs import load_designs


def test_public_catalog_works_without_private_templates(tmp_path):
    path = tmp_path / 'template-designs.json'
    path.write_text(json.dumps([{'id': 'public', 'label': 'Public'}]))
    assert load_designs(path, tmp_path / 'fehlt.json') == [{'id': 'public', 'label': 'Public'}]


def test_private_catalog_is_optional_and_marks_local_entries(tmp_path):
    path = tmp_path / 'template-designs.json'
    path.write_text(json.dumps([{'id': 'public', 'label': 'Public'}]))
    local = tmp_path / 'privat' / 'template-designs.json'
    local.parent.mkdir()
    local.write_text(json.dumps([{'id': 'private', 'label': 'Private'}]))
    assert load_designs(path, local) == [
        {'id': 'public', 'label': 'Public'},
        {'id': 'private', 'label': 'Private', 'local_only': True},
    ]
