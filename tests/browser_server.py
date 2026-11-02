"""Disposable browser-test server; mirrors nginx stripping /poe2guild/."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple
from werkzeug.wrappers import Response
from backend.app import create_app


if __name__ == '__main__':
    app = create_app({'REFERENCE_FILE': ROOT / 'tests/fixtures/browser-reference.json',
                      'DATABASE_FILE': ROOT / 'tests/fixtures/absent-test-database.sqlite'})
    mounted = DispatcherMiddleware(Response('Not found', status=404), {'/poe2guild': app})
    run_simple('127.0.0.1', 19003, mounted, use_reloader=False)
