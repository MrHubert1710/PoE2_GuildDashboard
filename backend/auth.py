"""Local administrator identity, opaque revocable sessions and request policy.

Kept separate from league history: no credentials appear in report databases.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import secrets
import sqlite3
import time

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

SESSION = 'poa_admin'
CSRF = 'poa_csrf'
auth = Blueprint('auth', __name__)


class AuthStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS accounts(username TEXT PRIMARY KEY, password_hash TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS attempts(address TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def set_password(self, username, password):
        if not isinstance(username, str) or not username.strip() or len(username) > 100:
            raise ValueError('Username must contain 1–100 characters.')
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise ValueError('Password must contain 12–1024 characters.')
        hashed = generate_password_hash(password)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO accounts VALUES(?,?)', (username.strip(), hashed))
            db.execute('DELETE FROM sessions WHERE username=?', (username.strip(),))

    def identity(self, token):
        if not token or len(token) > 200:
            return None
        with self.connect() as db:
            row = db.execute('SELECT username FROM sessions WHERE token_hash=? AND expires>?',
                             (digest(token), time.time())).fetchone()
        return row[0] if row else None

    def login(self, username, password, address):
        now = time.time()
        # Serialize rate accounting across all gunicorn processes; hash outside lock.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE started<?', (now - 900,))
            db.execute('DELETE FROM sessions WHERE expires<=?', (now,))
            row = db.execute('SELECT count FROM attempts WHERE address=?', (address,)).fetchone()
            if row and row[0] >= 10:
                return None, 'login_limited'
            db.execute('INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(address) DO UPDATE SET count=count+1', (address, now))
            row = db.execute('SELECT password_hash FROM accounts WHERE username=?', (username,)).fetchone()
        # Same cost for an unknown username (one precomputed dummy hash per process).
        if not check_password_hash(row[0] if row else current_app.extensions['auth_dummy'], password) or not row:
            return None, 'invalid_credentials'
        token = secrets.token_urlsafe(48)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), username, now + 8 * 3600))
            db.execute('DELETE FROM attempts WHERE address=?', (address,))
        return token, None

    def revoke(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token or ''),))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def store():
    return current_app.extensions['auth_store']


def is_admin():
    return bool(getattr(g, 'admin', None))


def secure_transport():
    return request.is_secure or not current_app.config['AUTH_REQUIRE_HTTPS']


def cookie_options():
    return dict(httponly=True, secure=request.is_secure, samesite='Strict',
                path=current_app.config['AUTH_COOKIE_PATH'])


def csrf_valid():
    cookie = request.cookies.get(CSRF, '')
    header = request.headers.get('X-CSRF-Token', '')
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
        return False
    return len(cookie) >= 32 and secrets.compare_digest(cookie, header)


@auth.get('/api/auth/status')
def status():
    response = jsonify(role='Admin' if is_admin() else 'Player',
                       username=g.admin, login_available=secure_transport(),
                       csrf_token=request.cookies.get(CSRF) or secrets.token_urlsafe(32))
    response.set_cookie(CSRF, response.get_json()['csrf_token'], **cookie_options())
    return response


@auth.post('/api/auth/login')
def login():
    if not secure_transport():
        return jsonify(error='https_required'), 403
    if not csrf_valid():
        return jsonify(error='csrf_rejected'), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'username', 'password'} or any(
            not isinstance(payload[key], str) or len(payload[key]) > 1024 for key in ('username', 'password')):
        return jsonify(error='invalid_credentials'), 400
    token, error = store().login(payload['username'], payload['password'], request.remote_addr or '')
    if error:
        response = jsonify(error=error)
        response.status_code = 429 if error == 'login_limited' else 401
        if response.status_code == 429:
            response.headers['Retry-After'] = '900'
        return response
    store().revoke(request.cookies.get(SESSION))
    csrf = secrets.token_urlsafe(32)
    response = jsonify(role='Admin', username=payload['username'], csrf_token=csrf, login_available=True)
    response.set_cookie(SESSION, token, max_age=8 * 3600, **cookie_options())
    response.set_cookie(CSRF, csrf, **cookie_options())
    return response


@auth.post('/api/auth/logout')
def logout():
    if not csrf_valid():
        return jsonify(error='csrf_rejected'), 403
    store().revoke(request.cookies.get(SESSION))
    response = jsonify(role='Player')
    response.delete_cookie(SESSION, **cookie_options())
    response.delete_cookie(CSRF, **cookie_options())
    return response


def init_auth(app):
    app.config.setdefault('AUTH_REQUIRE_HTTPS', True)
    app.config.setdefault('AUTH_COOKIE_PATH', '/poe2guild')
    if 'AUTH_DATABASE_FILE' not in app.config:
        if app.testing:
            from tempfile import TemporaryDirectory
            temporary = TemporaryDirectory(prefix='poa-test-auth-')
            app.extensions['auth_temporary'] = temporary
            app.config['AUTH_DATABASE_FILE'] = Path(temporary.name) / 'admin.sqlite'
        else:
            app.config['AUTH_DATABASE_FILE'] = Path(app.config['DATA_DIRECTORY']) / 'auth/admin.sqlite'
    app.extensions['auth_store'] = AuthStore(app.config['AUTH_DATABASE_FILE'])
    app.extensions['auth_dummy'] = generate_password_hash(secrets.token_urlsafe(24))
    # Gunicorn listens on loopback only. Trust exactly its one nginx reverse proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.register_blueprint(auth)

    @app.before_request
    def authorize():
        g.admin = store().identity(request.cookies.get(SESSION)) if secure_transport() else None
        private = request.endpoint in {'rework_readiness', 'database_readiness', 'quantities.get_settings', 'quantities.put_settings'}
        # Match by URL as well to avoid coupling policy to blueprint function names.
        private = private or request.path.endswith('/quantity-settings')
        if request.endpoint == 'refresh.enqueue':
            body = request.get_json(silent=True)
            private = isinstance(body, dict) and body.get('kind') == 'local_verify'
        if private:
            if not is_admin():
                return jsonify(error='admin_required'), 401
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not csrf_valid():
                return jsonify(error='csrf_rejected'), 403

    @app.after_request
    def security_headers(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        return response
