from pathlib import Path
import tempfile
import unittest

from backend.app import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dist = Path(self.temp.name)
        self.app = create_app({'TESTING': True, 'FRONTEND_DIST': self.dist})
        self.client = self.app.test_client()

    def test_health_identifies_new_service_without_a_frontend_build(self):
        self.assertEqual(self.client.get('/health').data, b'ok\n')
        self.assertEqual(self.client.get('/api/health').json,
                         {'message': 'Hello World', 'service': 'poe2guild', 'status': 'ok'})
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
