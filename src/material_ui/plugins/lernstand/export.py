"""Publication format owned by the optional Lernstand export plugin.

Usable from Invoke without loading Flask routes or starting the plugin host.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import html
import json
import shutil
import tempfile
import zipfile

from material_core.lernstand import (
    LernstandError, load, audit, unique_id, source_path, pdf_path,
)


def _require(condition, message):
    if not condition:
        raise LernstandError(message)


def publication_entries(data, folder, root, solutions=False):
    entries = []
    for item in data['materialien']:
        if not item.get('online', False):
            continue
        entries.append((item, 'quelle', source_path(folder, item['quelle'], root)))
        if solutions and item.get('loesung_online', False) and item.get('loesung'):
            entries.append((item, 'loesung', source_path(folder, item['loesung'], root)))
    return entries


def ensure_pdf(source, service, quarto=None):
    """Use the managed build's dependency signature to avoid repeated renders."""
    if service.pdf_is_current(source) is not True:
        return service.build_document(source, **({'quarto': quarto} if quarto else {}))


@contextmanager
def export_lock(base, unit_id):
    import fcntl
    base.mkdir(parents=True, exist_ok=True)
    with (base / (unit_id + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def snapshot(folder, root, build=None, solutions=False):
    """Pin an independent package until its consumer finishes reading it."""
    _, data = load(folder, root)
    unique_id(folder, root, data['id'])
    base = root / 'build/lernstand'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=base) as temp:
        target = Path(temp) / 'package'
        with export_lock(base, data['id']):
            _require(load(folder, root)[1]['id'] == data['id'], 'Einheiten-ID während des Wartens geändert.')
            shutil.copytree(_export(folder, root, build, solutions), target)
        yield target


def export(folder, root, build=None, solutions=False):
    _, data = load(folder, root)
    unique_id(folder, root, data['id'])
    with export_lock(root / 'build/lernstand', data['id']):
        _require(load(folder, root)[1]['id'] == data['id'], 'Einheiten-ID während des Wartens geändert.')
        return _export(folder, root, build, solutions)


def _export(folder, root, build=None, solutions=False):
    """Build into a staging directory; retain the previous release on any error."""
    manifest_text = (folder / 'einheit.yaml').read_text(encoding='utf-8')
    unit, data = load(folder, root)
    report = audit(data, folder, root)
    _require(not report['fehler'], '\n'.join(report['fehler']))
    entries = publication_entries(data, folder, root, solutions)
    _require(entries, 'Keine Materialien für online freigegeben.')
    revisions = {source: hashlib.sha256(source.read_bytes()).digest() for _, _, source in entries}
    base = root / 'build/lernstand'
    base.mkdir(parents=True, exist_ok=True)
    target = base / data['id']
    with tempfile.TemporaryDirectory(prefix='.export-', dir=base) as temp:
        stage = Path(temp)
        catalog = {'schema': 1, 'id': data['id'], 'version': data['version'], 'titel': unit['titel'],
                   'kompetenzen': data['kompetenzen'], 'materialien': [], 'aufgaben': []}
        published = {}
        for item, role, source in entries:
            if build:
                build(source)
            pdf = pdf_path(source, root)
            _require(pdf.is_file(), f'PDF fehlt: {pdf}. Mit --build exportieren.')
            _require(pdf.stat().st_mtime >= source.stat().st_mtime, f'PDF veraltet: {source}. Mit --build exportieren.')
            from material_core.builds import BuildService
            _require(BuildService(root, None).pdf_is_current(source) is True, f'PDF-Abhängigkeiten geändert: {source}. Mit --build exportieren.')
            relative = Path('dateien') / item['id'] / ('loesung.pdf' if role == 'loesung' else 'blatt.pdf')
            dest = stage / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, dest)
            record = published.setdefault(item['id'], {k: v for k, v in item.items() if k in ('id', 'rolle', 'kompetenz', 'stufe', 'titel')})
            record[role] = relative.as_posix()
            record[role + '_sha256'] = hashlib.sha256(dest.read_bytes()).hexdigest()
        role_order = {'diagnose': 0, 'wegweiser': 1, 'foerdermaterial': 2, 'nachtest': 3}
        catalog['materialien'] = sorted(published.values(), key=lambda item: role_order[item['rolle']])
        catalog['aufgaben'] = [{**task, 'empfehlung': [mid for mid in task['empfehlung'] if mid in published]}
                               for task in data.get('aufgaben', []) if task['diagnose'] in published]
        (stage / 'katalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
        competency_names = {comp['id']: comp['titel'] for comp in data['kompetenzen']}
        rows = []
        for item in catalog['materialien']:
            links = ' · '.join(f'<a href="{html.escape(item[key], quote=True)}">{label}</a>' for key, label in [('quelle', 'Blatt'), ('loesung', 'Lösung')] if key in item)
            rows.append(f"<tr><td>{html.escape(competency_names.get(item.get('kompetenz'), {'diagnose': 'Lernstandserhebung', 'nachtest': 'Nachtest', 'wegweiser': 'Wegweiser'}.get(item['rolle'], item['rolle'])))}</td><td>{html.escape(item.get('stufe', '').replace('stufe-', 'Stufe '))}</td><td>{html.escape(item.get('titel', item['id']))}</td><td>{links}</td></tr>")
        guidance = ['<h2>Dein Förderweg</h2><p>Prüfe deine Antworten mit deiner Lehrkraft. Bei falschen oder unsicheren Antworten helfen diese Materialien.</p><ul>']
        for task in catalog['aufgaben']:
            links = []
            for mid in task['empfehlung']:
                item = published[mid]
                links.append(f'<a href="{html.escape(item["quelle"], quote=True)}">{html.escape(item.get("titel", mid))}</a>')
            guidance.append('<li>' + html.escape(published[task['diagnose']].get('titel', task['diagnose']) + ' · Aufgabe ' + task.get('nummer', task['id'])) + ': ' + ('; '.join(links) or 'Mit der Lehrkraft besprechen.') + '</li>')
        guidance.append('</ul>')
        (stage / 'style.css').write_text("""
:root { font-family: system-ui, sans-serif; color: #172d36; background: #f3f6f7; }
body { max-width: 76rem; margin: 2rem auto; padding: 0 1rem 3rem; line-height: 1.5; }
h1 { font-size: clamp(1.6rem, 4vw, 2.4rem); } a { color: #075d78; }
table { width: 100%; border-collapse: collapse; background: white; }
caption { text-align: left; font-weight: bold; margin: 1rem 0; }
th, td { text-align: left; padding: .8rem; border-bottom: 1px solid #d6e0e4; vertical-align: top; }
th { background: #dce9ed; } li { margin-block: .7rem; }
@media (max-width: 600px) { th, td { padding: .4rem; font-size: .85rem; } }
""", encoding='utf-8')
        (stage / 'index.html').write_text('<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="style.css"><title>' + html.escape(unit['titel']) + '</title><body><h1>' + html.escape(unit['titel']) + '</h1><table><caption>Diagnose und Fördermaterial</caption><tr><th>Kompetenz</th><th>Stufe</th><th>Material</th><th>Download</th></tr>' + ''.join(rows) + '</table>' + ''.join(guidance) + '</body></html>', encoding='utf-8')
        # ZIP is also the portable upload artifact. Source paths never leave the private repo.
        archive = stage / 'paket.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
            for path in sorted(stage.rglob('*')):
                if path.is_file() and path != archive:
                    out.write(path, path.relative_to(stage))
        _require(all(source.is_file() and hashlib.sha256(source.read_bytes()).digest() == revision for source, revision in revisions.items()), 'Material während des Exports geändert. Bitte erneut exportieren.')
        _require((folder / 'einheit.yaml').read_text(encoding='utf-8') == manifest_text, 'Einheit während des Exports geändert. Bitte erneut exportieren.')
        backup = base / (data['id'] + '.previous')
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            target.rename(backup)
        try:
            stage.rename(target)
        except BaseException:
            if backup.exists():
                backup.rename(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return target
