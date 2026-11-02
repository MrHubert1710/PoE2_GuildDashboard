import csv
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tests.auth_helpers import create_app
from backend.archive_import import import_bundle, ImportRejected, normalize
from backend.database import connect, migrate, verify, maintenance_lock, DatabaseError, SCHEMA_VERSION
from backend.database_lifecycle import rebuild, snapshot_legacy
from backend.reference import FIELDS, sha256
from backend.repositories import database_status


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.database = self.data / 'test.sqlite'
        self.manifest = {'leagues': []}
        for name in ('Alpha', 'Beta'):
            directory = self.data / 'leagues' / name
            directory.mkdir(parents=True)
            self.write_history(directory / 'history.csv', [self.row(name)])
            (directory / 'reports').mkdir()
            (directory / 'reports/price_cache').mkdir()
            (directory / 'reports/price_cache/currency.json').write_text('{"lines":[]}')
            files = {str(path.relative_to(self.data)): sha256(path) for path in directory.rglob('*') if path.is_file()}
            self.manifest['leagues'].append({'name': name, 'directory': name, 'transactions': 1, 'files': files})
        self.save_manifest()
        migrate(self.database)

    def test_data_only_migration_preserves_history_prices_and_rejects_presentation_files(self):
        import_bundle(self.database,self.data)
        with connect(self.database) as c:
            before=[tuple(row) for row in c.execute('SELECT * FROM transactions ORDER BY id')]
            files=[tuple(row) for row in c.execute('SELECT * FROM archive_files ORDER BY id')]
            initial=(Path(__file__).resolve().parents[1]/'backend/migrations/001_initial.sql').read_text()
            definition=initial[initial.index('CREATE TABLE archive_files'):initial.index('CREATE TABLE revisions')]
            c.executescript('ALTER TABLE archive_files RENAME TO current_files;'+definition+
                            'INSERT INTO archive_files SELECT * FROM current_files; DROP TABLE current_files;')
            c.execute("INSERT INTO archive_files SELECT id+1000,source_id,league_id,archive_key||'.retired',relative_path||'.retired','report',sha256,bytes,provenance_json,import_id FROM archive_files WHERE kind='history'")
            c.execute('DELETE FROM schema_migrations WHERE version=4')
            c.execute('PRAGMA user_version=3')
        migrate(self.database)
        migrate(self.database)
        with connect(self.database) as c:
            self.assertEqual([tuple(row) for row in c.execute('SELECT * FROM transactions ORDER BY id')],before)
            self.assertEqual([tuple(row) for row in c.execute('SELECT * FROM archive_files ORDER BY id')],files)
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE archive_files SET kind='report' WHERE kind='history'")

    def row(self, league='Alpha', event_id='1', **changes):
        result = dict(zip(FIELDS, ['2026-01-01T23:30:00Z', event_id, league, 'PRIVATE_ACCOUNT',
                                  'added', 'Typo stash', '8× Unknown Item', '0', '0']))
        result.update(changes)
        return result

    def write_history(self, path, rows):
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def change_history(self, league, rows):
        path = self.data / 'leagues' / league / 'history.csv'
        self.write_history(path, rows)
        entry = next(entry for entry in self.manifest['leagues'] if entry['name'] == league)
        entry['files'][str(path.relative_to(self.data))] = sha256(path)
        entry['transactions'] = len(rows)
        self.save_manifest()

    def save_manifest(self):
        (self.data / 'import-manifest.json').write_text(json.dumps(self.manifest))

    def test_migration_is_repeatable_and_enforces_foreign_keys_and_wal(self):
        migrate(self.database)
        with connect(self.database) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], SCHEMA_VERSION)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO league_external_ids VALUES ('missing','test','id')")

    def test_changed_applied_migration_is_rejected(self):
        from backend.database import MIGRATIONS
        directory = self.root / 'migrations'
        shutil.copytree(MIGRATIONS, directory)
        path = directory / '001_initial.sql'
        path.write_text(path.read_text() + '\n-- changed after application\n')
        with patch('backend.database.MIGRATIONS', directory):
            with self.assertRaisesRegex(DatabaseError, 'migration has changed'):
                migrate(self.database)

    def test_repeat_import_is_deduplicated_and_keeps_revision(self):
        first = import_bundle(self.database, self.data)
        self.assertEqual(first['inserted'], 2)
        with connect(self.database, readonly=True) as connection:
            revisions = [row[0] for row in connection.execute('SELECT id FROM revisions ORDER BY id')]
        second = import_bundle(self.database, self.data)
        self.assertEqual((second['inserted'], second['duplicates']), (0, 2))
        with connect(self.database, readonly=True) as connection:
            self.assertEqual([row[0] for row in connection.execute('SELECT id FROM revisions ORDER BY id')], revisions)
        status = database_status(self.database)
        self.assertEqual(status['transactions'], 2)
        self.assertEqual([league['transactions'] for league in status['leagues']], [1, 1])
        self.assertEqual([league['files']['history'] for league in status['leagues']], [1, 1])

    def test_external_id_is_scoped_by_league_and_source(self):
        import_bundle(self.database, self.data)
        result = import_bundle(self.database, self.data, source_key='another-guild')
        self.assertEqual(result['inserted'], 2)
        self.assertEqual(database_status(self.database)['transactions'], 4)

    def test_raw_data_settings_and_uncertain_metadata_are_retained(self):
        row = self.row(Date='2026-01-02T01:30:00+02:00', Item=' 8× Unknown Item ')
        self.change_history('Alpha', [row])
        settings = {'stash_aliases': {'Typo stash': 'Correct'}, 'provenance': 'unverified_legacy'}
        import_bundle(self.database, self.data, settings=settings)
        with connect(self.database, readonly=True) as connection:
            record = connection.execute("SELECT * FROM transactions WHERE league_id=(SELECT id FROM leagues WHERE name='Alpha')").fetchone()
            self.assertEqual(record['occurred_at'], '2026-01-01T23:30:00.000000Z')
            self.assertEqual(json.loads(record['raw_json']), row)
            self.assertEqual(record['item'], '8× Unknown Item')
            self.assertEqual(record['stash'], 'Typo stash')
            league = connection.execute("SELECT * FROM leagues WHERE name='Alpha'").fetchone()
            self.assertEqual(json.loads(league['settings_json']), settings)
            self.assertIsNone(league['history_complete'])
            self.assertEqual(league['lifecycle'], 'unknown')
            self.assertEqual(league['fetch_available'], 0)
        import_bundle(self.database, self.data, settings={'provenance': 'different'})
        with connect(self.database, readonly=True) as connection:
            self.assertEqual(json.loads(connection.execute('SELECT settings_json FROM leagues LIMIT 1').fetchone()[0]), settings)

    def test_conflict_rolls_back_every_league_and_records_failure(self):
        import_bundle(self.database, self.data)
        original = database_status(self.database)
        self.change_history('Alpha', [self.row(event_id='2'), self.row(Item='Changed Item')])
        self.change_history('Beta', [self.row('Beta'), self.row('Beta', '3')])
        with self.assertRaises(ImportRejected) as rejected:
            import_bundle(self.database, self.data)
        self.assertEqual(rejected.exception.result['inserted'], 0)
        self.assertEqual(rejected.exception.result['conflicts'], 1)
        status = database_status(self.database)
        self.assertEqual(status['transactions'], original['transactions'])
        self.assertEqual(status['last_import']['status'], 'failed')
        self.assertEqual(status['last_import']['conflict_count'], 1)
        with connect(self.database, readonly=True) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM revisions').fetchone()[0], 2)

    def test_invalid_rows_abort_and_are_reported(self):
        rows = [self.row(), self.row(event_id='2', X='-1'), self.row(event_id='3', Date='2026-01-01'),
                self.row(event_id='4', League='Other'), self.row(event_id='5', Account='')]
        self.change_history('Alpha', rows)
        with self.assertRaises(ImportRejected) as rejected:
            import_bundle(self.database, self.data)
        self.assertEqual(rejected.exception.result['invalid'], 4)
        self.assertEqual(database_status(self.database)['transactions'], 0)
        self.assertEqual(database_status(self.database)['last_import']['invalid_count'], 4)

    def test_checksum_failure_prevents_import_writes(self):
        (self.data / 'leagues/Alpha/history.csv').write_text('changed without manifest')
        with self.assertRaisesRegex(DatabaseError, 'checksum'):
            import_bundle(self.database, self.data)
        self.assertIsNone(database_status(self.database)['last_import'])

    def test_two_equivalent_dates_are_duplicates_not_corrections(self):
        import_bundle(self.database, self.data)
        self.change_history('Alpha', [self.row(Date='2026-01-02T01:30:00+02:00')])
        result = import_bundle(self.database, self.data)
        self.assertEqual((result['inserted'], result['duplicates'], result['conflicts']), (0, 2, 0))

    def test_reader_sees_previous_snapshot_during_import(self):
        observed = []

        def inspect(row, league):
            observed.append(database_status(self.database)['transactions'])
            return normalize(row, league)

        with patch('backend.archive_import.normalize', side_effect=inspect):
            import_bundle(self.database, self.data)
        self.assertEqual(observed, [0, 0])
        self.assertEqual(database_status(self.database)['transactions'], 2)

    def test_verification_tracks_the_last_successful_import(self):
        import_bundle(self.database, self.data)
        self.assertEqual(verify(self.database)['transactions'], 2)
        self.assertTrue(database_status(self.database)['integrity']['current'])
        import_bundle(self.database, self.data)
        self.assertFalse(database_status(self.database)['integrity']['current'])
        verify(self.database)
        self.assertTrue(database_status(self.database)['integrity']['current'])

    def test_rebuild_replaces_only_after_successful_validation(self):
        import_bundle(self.database, self.data)
        original_id = database_status(self.database)['instance_id']
        rebuild(self.database, self.data)
        result = database_status(self.database)
        self.assertNotEqual(result['instance_id'], original_id)
        self.assertEqual(result['transactions'], 2)
        self.assertTrue(result['integrity']['current'])
        self.assertEqual(result['journal_mode'], 'wal')
        original_id = result['instance_id']
        self.change_history('Alpha', [self.row(Date='invalid')])
        with self.assertRaises(ImportRejected):
            rebuild(self.database, self.data)
        self.assertEqual(database_status(self.database)['instance_id'], original_id)
        self.assertEqual(database_status(self.database)['transactions'], 2)
        self.assertEqual(list(self.data.glob('.rebuild-*')), [])

    def test_rebuild_refuses_live_service_records(self):
        run = self.root / 'run'
        run.mkdir()
        (run / 'gunicorn.pid').write_text(str(os.getpid()))
        identity = database_status(self.database)['instance_id']
        with self.assertRaisesRegex(DatabaseError, 'Stop web/worker'):
            rebuild(self.database, self.data, run_directory=run)
        self.assertEqual(database_status(self.database)['instance_id'], identity)

    def test_failed_file_replacement_preserves_existing_database_and_wal(self):
        import_bundle(self.database, self.data)
        identity = database_status(self.database)['instance_id']
        with patch('backend.database_lifecycle.os.replace', side_effect=OSError('Cannot replace')):
            with self.assertRaises(OSError):
                rebuild(self.database, self.data)
        status = database_status(self.database)
        self.assertEqual(status['instance_id'], identity)
        self.assertEqual(status['transactions'], 2)
        self.assertEqual(status['journal_mode'], 'wal')

    def test_maintenance_is_exclusive(self):
        with maintenance_lock(self.database):
            with self.assertRaisesRegex(DatabaseError, 'maintenance'):
                with maintenance_lock(self.database):
                    self.fail('Concurrent maintenance was allowed')

    def test_readonly_status_does_not_create_missing_database(self):
        missing = self.data / 'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError):
            database_status(missing)
        self.assertFalse(missing.exists())
        client = create_app({'TESTING': True, 'DATABASE_FILE': missing}).test_client()
        response = client.get('/api/database-status')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(missing.exists())
        self.assertNotIn(str(missing), response.get_data(as_text=True))

    def test_newer_schema_is_rejected_by_migration_and_api(self):
        with connect(self.database) as connection:
            connection.execute('PRAGMA user_version=99')
        with self.assertRaisesRegex(DatabaseError, 'newer'):
            migrate(self.database)
        client = create_app({'TESTING': True, 'DATABASE_FILE': self.database}).test_client()
        response = client.get('/api/database-status')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(str(self.database), response.get_data(as_text=True))

    def test_status_api_compares_baseline_without_exposing_accounts_or_paths(self):
        import_bundle(self.database, self.data)
        verify(self.database)
        reference = self.root / 'reference.json'
        reference.write_text(json.dumps({'leagues': [dict(league, history_sha256=sha256(self.data / 'leagues' / league['name'] / 'history.csv'))
                                                    for league in database_status(self.database)['leagues']]}))
        client = create_app({'TESTING': True, 'DATABASE_FILE': self.database, 'REFERENCE_FILE': reference}).test_client()
        response = client.get('/api/database-status')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(league['baseline_match'] for league in response.json['leagues']))
        for private in ('PRIVATE_ACCOUNT', str(self.data), 'raw_json', 'settings_json'):
            self.assertNotIn(private, response.get_data(as_text=True))
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_legacy_snapshot_is_independent_repeatable_and_does_not_execute_config(self):
        legacy = self.root / 'legacy'
        for name in ('Alpha', 'Beta'):
            logs = legacy / 'logs' / name
            reports = legacy / 'stash_reports' / name
            logs.mkdir(parents=True)
            shutil.copy2(self.data / 'leagues' / name / 'history.csv', logs / 'history.csv')
            shutil.copytree(self.data / 'leagues' / name / 'reports', reports)
        config = legacy / 'poe2logger/private_config.py'
        config.parent.mkdir()
        config.write_text("TARGET_STASHES={'Test'}\nSTASH_ALIASES={}\nSESSION_ID='SECRET'\nraise RuntimeError('Do not execute')\n")
        original = sha256(legacy / 'logs/Alpha/history.csv')
        snapshot, settings = snapshot_legacy(legacy, self.data)
        again, _ = snapshot_legacy(legacy, self.data)
        self.assertEqual(snapshot, again)
        self.assertNotIn('SECRET', json.dumps(settings))
        self.assertEqual(sha256(legacy / 'logs/Alpha/history.csv'), original)
        result = import_bundle(self.database, snapshot, settings=settings)
        self.assertEqual(result['inserted'], 2)
        shutil.rmtree(legacy)
        self.assertEqual(import_bundle(self.database, snapshot)['duplicates'], 2)
