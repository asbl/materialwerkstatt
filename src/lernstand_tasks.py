"""Managed diagnostic export and optional deployment to a configured web directory."""
from pathlib import Path
import json

from invoke import task
from material_core import lernstand
from material_core import workspace

ROOT = workspace.root()


def folder(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT / 'unterricht'):
        raise ValueError('Einheit muss unter unterricht liegen.')
    return path


@task(name='pruefen')
def check(_ctx, einheit):
    """Diagnose, Kompetenzen und Materialverweise prüfen."""
    path = folder(einheit)
    _, data = lernstand.load(path, ROOT)
    report = lernstand.audit(data, path, ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['fehler']:
        raise SystemExit(1)


@task(name='export')
def export_cmd(_ctx, einheit, build=False, loesungen=False):
    """Veröffentlichungspaket mit PDF, Katalog, Vorschau und ZIP erzeugen."""
    from material_ui.plugins.lernstand import export as publication
    from project_tasks import BuildService, _run, QUARTO
    service = BuildService(ROOT, _run)
    target = publication.export(folder(einheit), ROOT,
        build=(lambda source: publication.ensure_pdf(source, service, QUARTO)) if build else None,
        solutions=loesungen)
    print(target)
    return target


@task(name='upload')
def upload(_ctx, einheit, ziel='', build=False, loesungen=False, trocken=False):
    """Paket per rsync in ein konfiguriertes Webverzeichnis übertragen."""
    from material_ui.plugins.lernstand.upload import upload as publish
    from material_ui.plugins.lernstand import export as publication
    from project_tasks import BuildService, _run, QUARTO
    service = BuildService(ROOT, _run)
    return publish(folder(einheit), ROOT, destination=ziel,
        build=(lambda source: publication.ensure_pdf(source, service, QUARTO)) if build else None,
        solutions=loesungen, dry_run=trocken)


@task(name='anlegen')
def initialize(_ctx, einheit, kennung, kompetenz='grundlagen'):
    """Vorhandene Einheit um eine Diagnose mit einem ersten Förderweg ergänzen."""
    import re
    from io import StringIO
    from ruamel.yaml import YAML
    from material_core.filesystem import atomic_write_text
    path = folder(einheit)
    manifest = path / 'einheit.yaml'
    yaml = YAML()
    original_manifest = manifest.read_text(encoding='utf-8')
    unit = yaml.load(original_manifest)
    if 'lernstand' in unit:
        raise ValueError('Diese Einheit besitzt bereits einen Lernstand-Bereich.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', kompetenz):
        raise ValueError('Ungültige Kompetenz-ID.')
    source = f'foerdermaterial/{kompetenz}/basis/ab_uebungen.qmd'
    data = {'schema': 1, 'id': kennung, 'version': '1',
        'kompetenzen': [{'id': kompetenz, 'titel': kompetenz.replace('-', ' ').capitalize(),
            'stufen': [{'id': 'basis', 'beschreibung': 'Grundlagen sichern'}]}],
        'materialien': [
            {'id': 'eingang', 'rolle': 'diagnose', 'quelle': 'diagnose/ab_lernstand.qmd', 'online': False},
            {'id': 'uebungen', 'rolle': 'foerdermaterial', 'quelle': source, 'kompetenz': kompetenz, 'stufe': 'basis', 'online': False},
            {'id': 'nachtest', 'rolle': 'nachtest', 'quelle': 'nachtest/ab_lernstand.qmd', 'online': False}],
        'aufgaben': [{'id': 'eingang-01', 'nummer': '1', 'diagnose': 'eingang', 'kompetenz': kompetenz,
            'empfehlung': ['uebungen'], 'ausloeser': 'Antwort falsch oder unsicher.'}]}
    lernstand.validate(data, path, ROOT)
    lernstand.unique_id(path, ROOT, kennung)
    targets = [(path / item['quelle'], item['rolle']) for item in data['materialien']]
    if any(target.exists() for target, _ in targets):
        raise ValueError('Eine der Vorlagendateien existiert bereits.')
    created = []
    try:
        for target, role in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            title = {'diagnose': 'Lernstandserhebung', 'nachtest': 'Nachtest', 'foerdermaterial': 'Grundlagen üben'}[role]
            atomic_write_text(target, f'---\ntitle: {title}\nformat: pdf\n---\n\n<!-- Entwurf: Aufgaben und Lösungen fachlich ausarbeiten, bevor online freigegeben wird. -->\n\n# Aufgabe 1\n\n<!-- Diagnoseaufgabe zur Kompetenz {kompetenz} ergänzen. -->\n', overwrite=False)
            created.append(target)
        unit['lernstand'] = data
        stream = StringIO()
        yaml.dump(unit, stream)
        def check_manifest():
            if manifest.read_text(encoding='utf-8') != original_manifest:
                raise ValueError('Einheit wurde inzwischen geändert. Bitte erneut anlegen.')
        atomic_write_text(manifest, stream.getvalue(), before_replace=check_manifest)
    except BaseException:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    print('Entwurf angelegt. Quellen bearbeiten und anschließend in einheit.yaml ausdrücklich online freigeben.')
