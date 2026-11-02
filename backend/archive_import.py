"""Atomic import of verified local archive bundles. No network or legacy code execution."""
import csv
import hashlib
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone

from .database import DatabaseError, connect, require_schema, utc_now
from .reference import FIELDS, sha256


NORMALIZATION_VERSION = 'csv-v1'


class ImportRejected(DatabaseError):
    def __init__(self, result):
        self.result = result
        super().__init__('Import rejected; previous transactions retained. Inspect the import run.')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def normalize(row, league):
    if None in row or any(not isinstance(row.get(key), str) or not row[key].strip() for key in FIELDS):
        raise ValueError('missing_or_extra_fields')
    values = {key: row[key].strip() for key in FIELDS}
    if values['League'] != league:
        raise ValueError('wrong_league')
    try:
        stamp = datetime.fromisoformat(values['Date'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('naive')
        values['Date'] = stamp.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except ValueError as error:
        raise ValueError('invalid_or_naive_date') from error
    if values['Action'] not in {'added', 'removed', 'modified'}:
        raise ValueError('unknown_action')
    try:
        values['X'], values['Y'] = int(values['X']), int(values['Y'])
        if values['X'] < 0 or values['Y'] < 0:
            raise ValueError('negative')
    except ValueError as error:
        raise ValueError('invalid_coordinates') from error
    return values


def load_bundle(archive_root, data_directory):
    archive_root, data_directory = Path(archive_root).resolve(), Path(data_directory).resolve()
    if not archive_root.is_relative_to(data_directory):
        raise DatabaseError('Archive bundle must be inside the data directory')
    manifest = json.loads((archive_root / 'import-manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('leagues'):
        raise DatabaseError('No leagues in archive manifest')
    names = set()
    bundles = []
    for entry in manifest['leagues']:
        name = entry['name']
        if name in names or not isinstance(name, str) or not name.strip():
            raise DatabaseError('Invalid or duplicate league in manifest')
        names.add(name)
        directory = (archive_root / 'leagues' / entry['directory']).resolve()
        if not directory.is_relative_to(archive_root / 'leagues'):
            raise DatabaseError('Invalid league path')
        files = []
        for relative, digest in entry['files'].items():
            path = (archive_root / relative).resolve()
            if not path.is_relative_to(directory):
                raise DatabaseError('Archive path escapes league directory')
            if path.name != 'history.csv' and not ('price_cache' in path.parts and path.suffix == '.json'):
                raise DatabaseError('Unsupported archive data file')
            if sha256(path) != digest:
                raise DatabaseError('Archive checksum differs from manifest')
            files.append((path, digest))
        history = directory / 'history.csv'
        if history not in {path for path, _ in files}:
            raise DatabaseError('History missing from archive manifest')
        inventory = {path.resolve() for path in directory.rglob('*') if path.is_file()
                     and (path.name == 'history.csv' or ('price_cache' in path.parts and path.suffix == '.json'))}
        if inventory != {path for path, _ in files}:
            raise DatabaseError('Archive inventory differs from manifest')
        bundles.append((entry, directory, history, files))
    return manifest, bundles


def import_bundle(database_path, archive_root, *, source_key='legacy-primary', game='poe2', realm='pc', settings=None):
    data_directory = Path(database_path).resolve().parent
    manifest, bundles = load_bundle(archive_root, data_directory)
    digest = hashlib.sha256(canonical(manifest['leagues']).encode()).hexdigest()
    run_id, started = str(uuid.uuid4()), utc_now()
    result = {'id': run_id, 'status': 'running', 'inserted': 0, 'duplicates': 0,
              'invalid': 0, 'conflicts': 0, 'errors': [], 'leagues': []}

    def error(name, line, code):
        if len(result['errors']) < 100:
            result['errors'].append({'league': name, 'line': line, 'code': code})

    with connect(database_path) as connection:
        require_schema(connection)
        connection.execute('INSERT OR IGNORE INTO sources(source_key,provider,created_at) VALUES (?,?,?)',
                           (source_key, 'legacy_csv', started))
        source = connection.execute('SELECT * FROM sources WHERE source_key=?', (source_key,)).fetchone()
        if source['provider'] != 'legacy_csv':
            raise DatabaseError('Source key belongs to a different provider')
        connection.execute('INSERT INTO import_runs(id,source_id,started_at,status,manifest_sha256) VALUES (?,?,?,?,?)',
                           (run_id, source['id'], started, 'running', digest))
        connection.execute('BEGIN IMMEDIATE')
        try:
            for entry, directory, history, files in bundles:
                name = entry['name']
                league_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical([game, realm, name])))
                candidate_settings = settings or {}
                connection.execute('INSERT OR IGNORE INTO leagues(id,game,realm,name,settings_json,settings_provenance) '
                                   'VALUES (?,?,?,?,?,?)', (league_id, game, realm, name, canonical(candidate_settings),
                                                          candidate_settings.get('provenance', 'unknown')))
                connection.execute('INSERT OR IGNORE INTO league_external_ids VALUES (?,?,?)',
                                   (league_id, 'legacy_csv', name))
                changed = False
                rows = 0
                inserted_before, duplicates_before = result['inserted'], result['duplicates']
                with history.open(encoding='utf-8-sig', newline='') as stream:
                    reader = csv.DictReader(stream)
                    if reader.fieldnames != list(FIELDS):
                        raise DatabaseError('Unexpected history columns')
                    for line, row in enumerate(reader, 2):
                        rows += 1
                        try:
                            values = normalize(row, name)
                        except ValueError as invalid:
                            result['invalid'] += 1
                            error(name, line, str(invalid))
                            continue
                        fingerprint = hashlib.sha256(canonical(values).encode()).hexdigest()
                        existing = connection.execute('SELECT normalized_sha256 FROM transactions '
                                                      'WHERE source_id=? AND league_id=? AND external_id=?',
                                                      (source['id'], league_id, values['Id'])).fetchone()
                        if existing:
                            if existing['normalized_sha256'] == fingerprint:
                                result['duplicates'] += 1
                            else:
                                result['conflicts'] += 1
                                error(name, line, 'conflicting_id')
                            continue
                        connection.execute('INSERT INTO transactions(source_id,league_id,external_id,occurred_at,account,'
                                           'action,stash,item,x,y,raw_json,normalized_sha256,normalization_version,import_id) '
                                           'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                           (source['id'], league_id, values['Id'], values['Date'], values['Account'],
                                            values['Action'], values['Stash'], values['Item'], values['X'], values['Y'],
                                            canonical(row), fingerprint, NORMALIZATION_VERSION, run_id))
                        result['inserted'] += 1
                        changed = True
                if rows != entry['transactions']:
                    raise DatabaseError('Transaction count differs from manifest')
                for path, expected in files:
                    if sha256(path) != expected:
                        raise DatabaseError('Archive changed while importing')
                    kind = 'history' if path == history else 'price_cache'
                    cursor = connection.execute('INSERT OR IGNORE INTO archive_files(source_id,league_id,archive_key,'
                                                'relative_path,kind,sha256,bytes,provenance_json,import_id) '
                                                'VALUES (?,?,?,?,?,?,?,?,?)',
                                                (source['id'], league_id, str(path.relative_to(directory)),
                                                 str(path.relative_to(data_directory)), kind, expected, path.stat().st_size,
                                                 canonical({'league': 'legacy_directory', 'data_time': 'unknown'}), run_id))
                    changed = changed or cursor.rowcount > 0
                if changed:
                    connection.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?)',
                                       (str(uuid.uuid4()), league_id, run_id, utc_now(), 'raw_import', NORMALIZATION_VERSION, None))
                result['leagues'].append({'name': name, 'rows': rows,
                                          'inserted': result['inserted'] - inserted_before,
                                          'duplicates': result['duplicates'] - duplicates_before})
            if result['invalid'] or result['conflicts']:
                raise ImportRejected(result)
            result['status'] = 'completed'
            connection.execute('UPDATE import_runs SET status=?,finished_at=?,inserted_count=?,duplicate_count=?,'
                               'details_json=? WHERE id=?', ('completed', utc_now(), result['inserted'], result['duplicates'],
                                                            canonical(result), run_id))
            connection.commit()
        except BaseException as failure:
            connection.rollback()
            result['status'] = 'failed'
            result['attempted_insertions'] = result['inserted']
            result['inserted'] = 0
            for league in result['leagues']:
                league['attempted_insertions'] = league['inserted']
                league['inserted'] = 0
            if not result['errors']:
                result['errors'].append({'code': 'import_aborted'})
            connection.execute('UPDATE import_runs SET status=?,finished_at=?,invalid_count=?,conflict_count=?,duplicate_count=?,'
                               'details_json=? WHERE id=?', ('failed', utc_now(), result['invalid'], result['conflicts'], result['duplicates'],
                                                            canonical(result), run_id))
            raise
    return result
