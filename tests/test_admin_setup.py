"""Bootstrap, install prompts and GUI password changes use disposable auth stores."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from backend.app import create_app
from backend.auth import AuthStore, DEFAULT_PASSWORD, SESSION

spec=importlib.util.spec_from_file_location('admin_setup',Path(__file__).resolve().parents[1]/'scripts/admin.py')
admin_setup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin_setup)


class AdminSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'auth.sqlite'
        self.app=create_app({'TESTING':True,'AUTH_DATABASE_FILE':self.path,'AUTH_COOKIE_PATH':'/'})
        self.store=self.app.extensions['auth_store']
        self.client=self.app.test_client()

    def status(self, client=None):
        return (client or self.client).get('/api/auth/status',base_url='https://localhost').json

    def login(self, password=DEFAULT_PASSWORD, client=None):
        client=client or self.client
        csrf=self.status(client)['csrf_token']
        return client.post('/api/auth/login',json={'password':password},headers={'X-CSRF-Token':csrf},base_url='https://localhost')

    def test_bootstrap_login_and_restart_do_not_reset_changed_password(self):
        self.assertTrue(self.status()['default_password'])
        self.assertEqual(self.login().status_code,200)
        self.assertNotIn(DEFAULT_PASSWORD.encode(),self.path.read_bytes())
        self.store.set_password('admin','my-new-password-123')
        AuthStore(self.path)
        self.assertFalse(self.status()['default_password'])
        self.assertEqual(self.login().status_code,401)
        self.assertEqual(self.login('my-new-password-123').status_code,200)

    def test_migration_preserves_existing_administrator(self):
        path=Path(self.temporary.name)/'legacy.sqlite'
        from werkzeug.security import generate_password_hash
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE accounts(username TEXT PRIMARY KEY,password_hash TEXT NOT NULL)')
            db.execute('INSERT INTO accounts VALUES(?,?)',('admin',generate_password_hash('original-password')))
        store=AuthStore(path)
        self.assertFalse(store.default_password_active())
        self.assertIsNone(store.change_password('admin','original-password','another-password'))

    def test_install_skip_and_reinstall_preserve_password(self):
        with patch('getpass.getpass',return_value=''),patch('builtins.print') as output:
            admin_setup.configure(self.store,installation=True)
            self.assertTrue(any('not recommended' in str(call) for call in output.call_args_list))
        self.assertTrue(self.store.default_password_active())
        with patch('getpass.getpass',side_effect=['new-secret-password','new-secret-password']):
            admin_setup.configure(self.store,installation=True)
        with patch('getpass.getpass') as prompt:
            admin_setup.configure(self.store,installation=True)
            prompt.assert_not_called()
        self.assertFalse(self.store.default_password_active())

    def test_gui_password_change_requires_auth_csrf_and_current_password(self):
        payload={'current_password':DEFAULT_PASSWORD,'password':'new-secret-password'}
        self.assertEqual(self.client.post('/api/auth/password',json=payload,base_url='https://localhost').status_code,401)
        self.login()
        self.assertEqual(self.client.post('/api/auth/password',json=payload,base_url='https://localhost').status_code,403)
        csrf=self.status()['csrf_token']
        for data in [{'current_password':'wrong','password':'new-secret-password'}, {'current_password':DEFAULT_PASSWORD,'password':'short'}]:
            self.assertEqual(self.client.post('/api/auth/password',json=data,headers={'X-CSRF-Token':csrf},base_url='https://localhost').status_code,400)
        self.assertTrue(self.store.default_password_active())

    def test_gui_password_change_revokes_all_sessions_and_old_password(self):
        self.login()
        other=self.app.test_client()
        self.login(client=other)
        old_cookie=self.client.get_cookie(SESSION).value
        csrf=self.status()['csrf_token']
        response=self.client.post('/api/auth/password',json={'current_password':DEFAULT_PASSWORD,'password':'new-secret-password'},headers={'X-CSRF-Token':csrf},base_url='https://localhost')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json['default_password'])
        self.assertEqual(self.status()['role'],'Player')
        self.assertEqual(self.status(other)['role'],'Player')
        self.assertIsNone(self.store.identity(old_cookie))
        self.assertEqual(self.login().status_code,401)
        self.assertEqual(self.login('new-secret-password').status_code,200)

    def test_login_started_before_password_reset_cannot_create_a_new_session(self):
        from werkzeug.security import check_password_hash
        def verify_then_reset(hashed, password):
            result=check_password_hash(hashed,password)
            self.store.set_password('admin','new-secret-password')
            return result
        with patch('backend.auth.check_password_hash',side_effect=verify_then_reset):
            self.assertEqual(self.login().status_code,401)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
