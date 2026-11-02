"""Legacy domain tests run explicitly as an authenticated administrator.

Security tests use backend.app directly, without this fixture.
"""
from flask.testing import FlaskClient
from backend.app import create_app as real_create_app


class AdminClient(FlaskClient):
    def open(self, *args, **kwargs):
        if getattr(self, 'csrf', None):
            kwargs['headers'] = {**dict(kwargs.get('headers') or {}), 'X-CSRF-Token': self.csrf}
        return super().open(*args, **kwargs)


def create_app(config):
    app = real_create_app({**config, 'AUTH_REQUIRE_HTTPS': False, 'AUTH_COOKIE_PATH': '/'})
    app.extensions['auth_store'].set_password('admin', 'test-only-password-123')
    app.test_client_class = AdminClient
    original = app.test_client
    def test_client(*args, **kwargs):
        client = original(*args, **kwargs)
        csrf = client.get('/api/auth/status').json['csrf_token']
        response = client.post('/api/auth/login', json={'password': 'test-only-password-123'}, headers={'X-CSRF-Token': csrf})
        assert response.status_code == 200
        client.csrf = response.json['csrf_token']
        return client
    app.test_client = test_client
    return app
