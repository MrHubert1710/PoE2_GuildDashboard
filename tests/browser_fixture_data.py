"""Small synthetic SQL dataset for browser tests; never opens production data."""
import csv
import json
from pathlib import Path

from backend.archive_import import import_bundle
from backend.database import migrate
from backend.reference import FIELDS, sha256


def build_browsing_fixture(data):
    data = Path(data)
    manifest = {'leagues': []}
    for league, count in (('Forbidden Rites', 60), ('Runes of Aldur', 3)):
        folder = data / 'leagues' / league
        (folder / 'reports').mkdir(parents=True)
        with (folder / 'history.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            for index in range(1, count + 1):
                item = 'Rites Token' if league == 'Forbidden Rites' else 'Aldur Token'
                if index == 3:
                    item = 'Literal %_ Item'
                if index == 4:
                    item = '<img src=x onerror="window.injected=true">'
                action = 'added'
                if league == 'Forbidden Rites' and index in (11, 12):
                    action = 'modified'
                    item = f'{20 if index == 11 else 15}× Rites Token'
                writer.writerow(dict(zip(FIELDS, [f'2026-01-{1 if index <= 30 else 2:02}T12:00:00Z', str(index),
                    league, 'Synthetic Alice' if index % 2 == 0 else 'Żółw', action,
                    'Special' if index == 3 else 'Main', item, '0', '0'])))
        (folder / 'reports/currentday.html').write_text(
            f'<!doctype html><html><body><h1>Archiwum {league}</h1>'
            '<button onclick="this.textContent=Number(this.textContent)+1">0</button></body></html>')
        manifest['leagues'].append({'name': league, 'directory': league, 'transactions': count,
            'files': {str(path.relative_to(data)): sha256(path) for path in folder.rglob('*') if path.is_file()}})
    (data / 'import-manifest.json').write_text(json.dumps(manifest))
    database = data / 'browser.sqlite'
    migrate(database)
    import_bundle(database, data)
    return database
