"""Deployment adapter for static Lernstand packages; no server assumed."""
import json
import os
import subprocess
from datetime import datetime, timezone

from material_core.lernstand import load
from .export import snapshot
import hashlib


def upload(path, root, destination='', build=None, solutions=False, dry_run=False):
    destination = destination or os.environ.get('LERNSTAND_UPLOAD_ZIEL', '')
    if not destination or destination.startswith('-') or '\n' in destination:
        raise ValueError('Uploadziel fehlt: --ziel oder LERNSTAND_UPLOAD_ZIEL (z. B. user@server:/srv/lernstand/einheiten).')
    _, data = load(path, root)
    # Each unit gets a separate destination; never delete unrelated server files.
    remote = destination.rstrip('/') + '/' + data['id'] + '/'
    if dry_run:
        print(json.dumps(['rsync', '-a', '--protect-args', '--delete-delay', '--dry-run', '--',
            str(root / 'build/lernstand' / data['id']) + '/', remote], ensure_ascii=False))
        return
    with snapshot(path, root, build=build, solutions=solutions) as target:
        catalog = json.loads((target / 'katalog.json').read_text())
        remote = destination.rstrip('/') + '/' + catalog['id'] + '/'
        digest = hashlib.sha256((target / 'paket.zip').read_bytes()).hexdigest()
        subprocess.run(['rsync', '-a', '--protect-args', '--delete-delay', '--', str(target) + '/', remote], check=True)
        status = {'einheit': catalog['id'], 'version': catalog['version'], 'ziel': remote,
                  'paket_sha256': digest, 'zeit': datetime.now(timezone.utc).isoformat()}
        (root / 'build/lernstand' / (catalog['id'] + '-upload.json')).write_text(json.dumps(status, indent=2), encoding='utf-8')
    print('Upload abgeschlossen:', remote)
