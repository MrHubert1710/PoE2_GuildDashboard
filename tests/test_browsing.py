import csv
import json
from pathlib import Path
import tempfile
import unittest

from backend.app import create_app
from backend.archive_import import import_bundle
from backend.database import connect, migrate
from backend.database_lifecycle import rebuild
from backend.reference import FIELDS, sha256


class BrowsingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.database = self.data / 'test.sqlite'
        manifest = {'leagues': []}
        self.alpha = []
        for index in range(1, 61):
            self.alpha.append(dict(zip(FIELDS, [
                f'2026-01-{1 if index <= 30 else 2:02}T12:00:00Z', str(index), 'Alpha',
                'Żółw' if index == 1 else 'Alice' if index % 2 == 0 else 'Bob', 'added',
                'Tab %_' if index == 3 else 'Main', 'Literal %_ Orb' if index == 3 else 'Chaos Orb', '0', '0'])))
        for league, rows in (('Alpha', self.alpha), ('Beta', [dict(self.alpha[0], League='Beta', Item='Beta Token')])):
            folder = self.data / 'leagues' / league
            (folder / 'reports').mkdir(parents=True)
            with (folder / 'history.csv').open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            (folder / 'reports/currentday.html').write_text(f'<html><body>{league}</body></html>')
            manifest['leagues'].append({'name': league, 'directory': league, 'transactions': len(rows),
                'files': {str(path.relative_to(self.data)): sha256(path) for path in folder.rglob('*') if path.is_file()}})
        (self.data / 'import-manifest.json').write_text(json.dumps(manifest))
        migrate(self.database)
        import_bundle(self.database, self.data)
        self.client = create_app({'TESTING': True, 'DATABASE_FILE': self.database, 'DATA_DIRECTORY': self.data}).test_client()
        self.leagues = self.client.get('/api/leagues').json['leagues']
        self.league = self.leagues[0]
        self.url = f"/api/leagues/{self.league['id']}/transactions"

    def test_list_has_counts_stashes_reports_and_separate_revision_per_league(self):
        self.assertEqual([(row['name'], row['transactions']) for row in self.leagues], [('Alpha', 60), ('Beta', 1)])
        self.assertEqual(self.league['stashes'], ['Main', 'Tab %_'])
        self.assertEqual(len(self.league['reports']), 1)
        self.assertNotEqual(self.leagues[0]['revision'], self.leagues[1]['revision'])
        self.assertNotIn(str(self.data), json.dumps(self.leagues))

    def test_pagination_is_bounded_stable_and_never_mixes_leagues(self):
        first = self.client.get(self.url, query_string={'page_size': 25, 'page': 1}).json
        second = self.client.get(self.url, query_string={'page_size': 25, 'page': 2}).json
        self.assertEqual(first['total'], 60)
        self.assertEqual(len(first['rows']), 25)
        self.assertEqual([row['external_id'] for row in first['rows']], [str(i) for i in range(60, 35, -1)])
        self.assertFalse({row['id'] for row in first['rows']} & {row['id'] for row in second['rows']})
        self.assertNotIn('Beta Token', json.dumps(first))
        final = self.client.get(self.url, query_string={'page_size': 25, 'page': 999}).json
        self.assertEqual((final['page'], final['pages'], len(final['rows'])), (3, 3, 10))
        self.assertNotIn('raw_json', json.dumps(first))

    def test_account_item_stash_and_combined_filters_are_literal_and_unicode_aware(self):
        self.assertEqual(self.client.get(self.url, query_string={'account': 'ŻÓŁW'}).json['total'], 1)
        self.assertEqual(self.client.get(self.url, query_string={'item': '%_'}).json['total'], 1)
        self.assertEqual(self.client.get(self.url, query_string={'stash': 'Tab %_'}).json['total'], 1)
        self.assertEqual(self.client.get(self.url, query_string={'account': 'bob', 'item': '%_', 'stash': 'Tab %_'}).json['total'], 1)
        result = self.client.get(self.url, query_string={'account': 'Alice', 'stash': 'Tab %_'}).json
        self.assertEqual((result['total'], result['rows'], result['page']), (0, [], 1))

    def test_date_range_includes_both_whole_utc_days(self):
        self.assertEqual(self.client.get(self.url, query_string={'from': '2026-01-01', 'to': '2026-01-01'}).json['total'], 30)
        self.assertEqual(self.client.get(self.url, query_string={'from': '2026-01-02', 'to': '2026-01-02'}).json['total'], 30)
        self.assertEqual(self.client.get(self.url, query_string={'from': '2026-01-01', 'to': '2026-01-02'}).json['total'], 60)

    def test_each_sort_is_stable_in_both_directions(self):
        for sort in ('date', 'account', 'stash', 'item', 'action'):
            for direction in ('asc', 'desc'):
                response = self.client.get(self.url, query_string={'sort': sort, 'direction': direction, 'page_size': 100})
                self.assertEqual(response.status_code, 200)
                ids = [row['id'] for row in response.json['rows']]
                self.assertEqual(len(set(ids)), 60)
                again = self.client.get(self.url, query_string={'sort': sort, 'direction': direction, 'page_size': 100}).json
                self.assertEqual(ids, [row['id'] for row in again['rows']])

    def test_invalid_and_ambiguous_query_parameters_are_rejected(self):
        for params in ({'page': '0'}, {'page': '-1'}, {'page': 'abc'}, {'page_size': '1000'}, {'page_size': '1'},
                       {'sort': 'id; DROP TABLE leagues'}, {'direction': 'sideways'}, {'from': '2026-02-31'},
                       {'to': '9999-12-31'}, {'from': '2026-01-03', 'to': '2026-01-01'}, {'unknown': 'x'},
                       {'account': 'x' * 201}):
            self.assertEqual(self.client.get(self.url, query_string=params).status_code, 400, params)
        self.assertEqual(self.client.get(self.url + '?page=1&page=2').status_code, 400)
        safe = self.client.get(self.url, query_string={'item': "'; DROP TABLE transactions; --"})
        self.assertEqual(safe.status_code, 200)
        self.assertEqual(safe.json['total'], 0)
        self.assertEqual(self.client.get(self.url).json['total'], 60)

    def test_revision_change_after_new_import_or_rebuild_is_explicit(self):
        old_revision = self.league['revision']
        with connect(self.database) as connection:
            connection.execute("INSERT INTO revisions SELECT 'new-revision',league_id,import_id,created_at,kind,algorithm_version,NULL "
                               'FROM revisions WHERE league_id=? LIMIT 1', (self.league['id'],))
        self.assertEqual(self.client.get(self.url, query_string={'revision': old_revision}).status_code, 409)
        latest = self.client.get('/api/leagues').json['leagues'][0]['revision']
        self.assertEqual(self.client.get(self.url, query_string={'revision': latest}).status_code, 200)
        rebuild(self.database, self.data)
        self.assertEqual(self.client.get(self.url, query_string={'revision': latest}).status_code, 409)

    def test_unknown_league_is_not_replaced_with_another_league(self):
        self.assertEqual(self.client.get('/api/leagues/missing/transactions').status_code, 404)

    def test_empty_database_and_empty_league_are_supported(self):
        with connect(self.database) as connection:
            connection.execute("INSERT INTO leagues(id,game,realm,name) VALUES ('empty','poe2','pc','Empty')")
        response = self.client.get('/api/leagues/empty/transactions')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json['total'], response.json['pages']), (0, 1))
        empty = self.data / 'empty.sqlite'
        migrate(empty)
        client = create_app({'TESTING': True, 'DATABASE_FILE': empty}).test_client()
        self.assertEqual(client.get('/api/leagues').json, {'leagues': []})

    def test_missing_database_does_not_create_files_or_leak_paths(self):
        missing = self.data / 'missing.sqlite'
        client = create_app({'TESTING': True, 'DATABASE_FILE': missing}).test_client()
        response = client.get('/api/leagues')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(missing.exists())
        self.assertNotIn(str(self.data), response.get_data(as_text=True))

    def test_registered_html_is_isolated_and_other_data_is_not_served(self):
        archive_id = self.league['reports'][0]['id']
        response = self.client.get(f'/archives/{archive_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Alpha', response.data)
        policy = response.headers['Content-Security-Policy']
        self.assertIn('sandbox allow-scripts;', policy)
        self.assertNotIn('allow-same-origin', policy)
        self.assertIn("connect-src 'none'", policy)
        self.assertIn('no-store', response.headers['Cache-Control'])
        with connect(self.database, readonly=True) as connection:
            history = connection.execute("SELECT id FROM archive_files WHERE kind='history' LIMIT 1").fetchone()[0]
        self.assertEqual(self.client.get(f'/archives/{history}').status_code, 404)
        self.assertEqual(self.client.get('/archives/999999').status_code, 404)
        self.assertEqual(self.client.get('/data/poe2guild.sqlite').status_code, 404)

    def test_archive_missing_tampered_or_escaping_data_directory_is_rejected(self):
        archive_id = self.league['reports'][0]['id']
        path = self.data / 'leagues/Alpha/reports/currentday.html'
        original = path.read_bytes()
        path.write_text('tampered')
        self.assertEqual(self.client.get(f'/archives/{archive_id}').status_code, 409)
        path.unlink()
        self.assertEqual(self.client.get(f'/archives/{archive_id}').status_code, 404)
        outside = self.data.parent / ('outside-' + self.data.name + '.html')
        outside.write_bytes(original)
        self.addCleanup(outside.unlink)
        with connect(self.database) as connection:
            connection.execute('UPDATE archive_files SET relative_path=? WHERE id=?', ('../' + outside.name, archive_id))
        self.assertEqual(self.client.get(f'/archives/{archive_id}').status_code, 404)

    def test_multiple_stashes_use_union_without_duplicate_rows(self):
        result = self.client.get(self.url, query_string=[('stash', 'Main'), ('stash', 'Tab %_'), ('page_size', '100')])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['total'], 60)
        self.assertEqual(len({row['id'] for row in result.json['rows']}), 60)
        duplicate = self.client.get(self.url, query_string=[('stash', 'Tab %_'), ('stash', 'Tab %_')])
        self.assertEqual(duplicate.json['total'], 1)
        combined = self.client.get(self.url, query_string=[('stash', 'Main'), ('stash', 'Tab %_'), ('account', 'Alice')])
        self.assertEqual(combined.json['total'], 30)
        self.assertEqual(self.client.get(self.url + '?stash=&stash=').json['total'], 60)

    def test_stash_list_limits_are_validated(self):
        response = self.client.get(self.url, query_string=[('stash', 'Main')] * 101)
        self.assertEqual((response.status_code, response.json['error']), (400, 'too_many_stashes'))
        response = self.client.get(self.url, query_string=[('stash', 'Main'), ('stash', 'x' * 201)])
        self.assertEqual((response.status_code, response.json['error']), (400, 'parameter_too_long'))
