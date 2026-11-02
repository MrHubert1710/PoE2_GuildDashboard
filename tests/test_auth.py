from pathlib import Path
import tempfile
import time
import unittest
from backend.app import create_app
from backend.auth import digest, SESSION


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'admin.sqlite'
        self.app = create_app({'TESTING': True, 'AUTH_DATABASE_FILE': self.path,
                               'AUTH_COOKIE_PATH': '/', 'AUTH_REQUIRE_HTTPS': True})
        self.store = self.app.extensions['auth_store']
        self.store.set_password('admin', 'long-test-password')
        self.client = self.app.test_client()

    def status(self, secure=True):
        return self.client.get('/api/auth/status', base_url='https://localhost' if secure else 'http://localhost').json

    def login(self, password='long-test-password', secure=True):
        token = self.status(secure)['csrf_token']
        return self.client.post('/api/auth/login', json={'password':password},
                                headers={'X-CSRF-Token':token}, base_url='https://localhost' if secure else 'http://localhost')

    def test_public_cannot_read_diagnostics_or_server_settings_and_verification(self):
        for path in ['/api/database-status','/api/rework-readiness','/api/leagues/anything/quantity-settings']:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.put('/api/leagues/anything/quantity-settings',json={}).status_code,401)
        self.assertEqual(self.client.post('/api/leagues/anything/refresh',json={'kind':'local_verify'}).status_code,401)
        self.assertEqual(self.client.get('/health').status_code,200)

    def test_https_is_required_and_cookies_are_secure(self):
        self.assertFalse(self.status(False)['login_available'])
        self.assertEqual(self.login(secure=False).json['error'],'https_required')
        response=self.login()
        self.assertEqual(response.status_code,200)
        cookie=next(value for value in response.headers.getlist('Set-Cookie') if value.startswith(SESSION+'='))
        for value in ['Secure','HttpOnly','SameSite=Strict','Max-Age=28800']:
            self.assertIn(value,cookie)
        # Even stolen cookies sent over HTTP cannot grant privileges.
        self.assertEqual(self.client.get('/api/auth/status').json['role'],'Player')

    def test_csrf_and_foreign_origin_are_rejected(self):
        self.status()
        self.assertEqual(self.client.post('/api/auth/login',json={'password':'long-test-password'},base_url='https://localhost').status_code,403)
        self.login()
        token=self.status()['csrf_token']
        path='/api/leagues/anything/quantity-settings'
        self.assertEqual(self.client.put(path,json={},base_url='https://localhost').status_code,403)
        self.assertEqual(self.client.put(path,json={},headers={'X-CSRF-Token':token,'Origin':'https://foreign.test'},base_url='https://localhost').status_code,403)

    def test_logout_revokes_token_even_if_replayed(self):
        response=self.login()
        cookie=self.client.get_cookie(SESSION)
        token=self.status()['csrf_token']
        self.assertEqual(self.client.post('/api/auth/logout',headers={'X-CSRF-Token':token},base_url='https://localhost').status_code,200)
        self.assertIsNone(self.store.identity(cookie.value))
        self.client.set_cookie(SESSION,cookie.value,secure=True)
        self.assertEqual(self.status()['role'],'Player')

    def test_expiration_reset_and_hash_storage(self):
        self.login()
        cookie=self.client.get_cookie(SESSION)
        raw=self.path.read_bytes()
        self.assertNotIn(b'long-test-password',raw)
        self.assertNotIn(cookie.value.encode(),raw)
        with self.store.connect() as db:
            db.execute('UPDATE sessions SET expires=?',(time.time()-1,))
        self.assertEqual(self.status()['role'],'Player')
        self.login()
        self.store.set_password('admin','another-test-password')
        self.assertEqual(self.status()['role'],'Player')
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_persistent_rate_limit_survives_new_application_instance(self):
        for _ in range(10):
            self.assertEqual(self.login('wrong-password').status_code,401)
        self.assertEqual(self.login().status_code,429)
        app=create_app({'TESTING':True,'AUTH_DATABASE_FILE':self.path,'AUTH_COOKIE_PATH':'/'})
        client=app.test_client()
        token=client.get('/api/auth/status',base_url='https://localhost').json['csrf_token']
        self.assertEqual(client.post('/api/auth/login',json={'password':'long-test-password'},headers={'X-CSRF-Token':token},base_url='https://localhost').status_code,429)

    def test_session_survives_process_restart(self):
        self.login()
        cookie=self.client.get_cookie(SESSION)
        app=create_app({'TESTING':True,'AUTH_DATABASE_FILE':self.path,'AUTH_COOKIE_PATH':'/'})
        client=app.test_client()
        client.set_cookie(SESSION,cookie.value,secure=True)
        self.assertEqual(client.get('/api/auth/status',base_url='https://localhost').json['role'],'Admin')

    def test_only_fixed_admin_account_can_authenticate(self):
        self.store.set_password('other','another-account-password')
        csrf=self.status()['csrf_token']
        response=self.client.post('/api/auth/login',json={'username':'other','password':'another-account-password'},headers={'X-CSRF-Token':csrf},base_url='https://localhost')
        self.assertEqual(response.status_code,400)
        with self.store.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest('legacy-token'),'other',time.time()+3600))
        self.assertIsNone(self.store.identity('legacy-token'))
