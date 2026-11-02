from pathlib import Path
import json
import tempfile
import unittest

from tests.auth_helpers import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dist = Path(self.temp.name)
        self.reference = self.dist / 'phase0.json'
        self.app = create_app({'TESTING': True, 'FRONTEND_DIST': self.dist,
                               'REFERENCE_FILE': self.reference})
        self.client = self.app.test_client()

    def test_health_identifies_new_service_without_a_frontend_build(self):
        self.assertEqual(self.client.get('/health').data, b'ok\n')
        self.assertEqual(self.client.get('/api/health').json,
                         {'message': 'Ready', 'service': 'poe2guild', 'status': 'ok'})
        self.assertEqual(self.client.get('/').status_code, 503)

    def test_html_and_hashed_assets_have_separate_cache_policies(self):
        (self.dist / 'index.html').write_text('<html>Hello World</html>')
        (self.dist / 'assets').mkdir()
        (self.dist / 'assets/app-123.js').write_text('console.log("hello")')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        response.close()
        response = self.client.get('/assets/app-123.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('immutable', response.headers['Cache-Control'])
        response.close()

    def test_unknown_api_assets_and_private_data_are_not_served_as_html(self):
        for route in ('/api/unknown', '/assets/missing.js', '/data/import-manifest.json',
                      '/assets/../../service.ini', '/poe2logger/private_config.py'):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 404, route)
            self.assertEqual(response.json, {'error': 'Not found'})

    def test_missing_or_broken_reference_has_actionable_error_without_paths(self):
        for contents in (None, 'broken JSON', '{"schema_version":99}'):
            if contents:
                self.reference.write_text(contents)
            response = self.client.get('/api/rework-readiness')
            self.assertEqual(response.status_code, 503)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertNotIn(str(self.reference), response.get_data(as_text=True))

    def test_readiness_uses_saved_snapshot_without_opening_archive_files(self):
        self.reference.write_text(json.dumps({
            'schema_version': 1, 'generated_at': '2026-11-02T00:00:00Z',
            'legacy_settings': {'SESSION_ID': 'SECRET'},
            'leagues': [{'name': 'Alpha', 'transactions': 1, 'oldest_at': None,
                         'newest_at': None, 'history_sha256': 'hash', 'issues': {},
                         'prices': [], 'source_matches': True,
                         'samples': {'Account': 'PRIVATE'}}]}))
        response = self.client.get('/api/rework-readiness')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['leagues'][0]['name'], 'Alpha')
        self.assertNotIn(b'SECRET', response.data)
        self.assertNotIn(b'PRIVATE', response.data)
