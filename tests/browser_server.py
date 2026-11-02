"""Disposable browser-test server; mirrors nginx stripping /poe2guild/."""
from pathlib import Path
import sys
import tempfile
import multiprocessing
import signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple
from werkzeug.wrappers import Response
from backend.app import create_app
from backend.jobs import Queue
from backend.worker import Worker
from browser_fixture_data import build_browsing_fixture


def run_worker(database, stop):
    Worker(Queue(database, cooldown=.1), stop=stop).run()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='poe2guild-browser-data-') as temporary:
        database = build_browsing_fixture(temporary)
        app = create_app({'REFERENCE_FILE': ROOT / 'tests/fixtures/browser-reference.json',
                          'DATABASE_FILE': database, 'DATA_DIRECTORY': temporary, 'AUTH_REQUIRE_HTTPS': False})
        app.extensions['auth_store'].set_password('admin', 'test-only-password-123')
        mounted = DispatcherMiddleware(Response('Not found', status=404), {'/poe2guild': app})
        # Deterministic initial projections keep existing UI tests independent of background timing.
        from backend.database import connect
        with connect(database, readonly=True) as c:
            league_ids = [row[0] for row in c.execute('SELECT id FROM leagues')]
        projection_queue = Queue(database, cooldown=0)
        for league_id in league_ids:
            projection_queue.enqueue(league_id, 'quantities', 'automatic')
        worker_once = Worker(projection_queue)
        while worker_once.run_once():
            pass
        stop = multiprocessing.Event()
        worker = multiprocessing.Process(target=run_worker, args=(database, stop))
        worker.start()
        def terminate(*_args):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, terminate)
        try:
            run_simple('127.0.0.1', 19003, mounted, use_reloader=False)
        finally:
            stop.set()
            worker.join(5)
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
