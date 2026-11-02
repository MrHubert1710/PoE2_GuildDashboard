"""Single worker process. No external game requests are implemented in phase 3."""
import argparse
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import threading
import uuid

from .archive_import import canonical, normalize
from .browsing import revision
from .database import connect, require_schema
from .jobs import Queue, LeaseLost, stamp

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger('poe2guild.worker')


class AdapterFailure(Exception):
    def __init__(self, code, *, retryable=True, retry_after=0):
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


class LocalVerification:
    """Verify stored rows against their raw records, without fetching or generating reports."""
    def stage(self, queue, job, stop):
        with connect(queue.path, readonly=True) as connection:
            require_schema(connection)
            connection.execute('BEGIN')
            league = queue.league(connection, job['league_id'])
            expected = revision(connection, league['id'])
            digest, count = hashlib.sha256(), 0
            fields = {'external_id': 'Id', 'occurred_at': 'Date', 'account': 'Account', 'action': 'Action',
                      'stash': 'Stash', 'item': 'Item', 'x': 'X', 'y': 'Y'}
            for row in connection.execute('SELECT * FROM transactions WHERE league_id=? ORDER BY id', (league['id'],)):
                if stop.is_set():
                    raise AdapterFailure('interrupted')
                try:
                    values = normalize(json.loads(row['raw_json']), league['name'])
                    fingerprint = hashlib.sha256(canonical(values).encode()).hexdigest()
                    if fingerprint != row['normalized_sha256'] or any(row[column] != values[field] for column, field in fields.items()):
                        raise ValueError('Mismatch')
                except (ValueError, TypeError, KeyError):
                    raise AdapterFailure('local_data_invalid', retryable=False) from None
                digest.update(f"{row['source_id']}:{row['external_id']}:{fingerprint}\n".encode())
                count += 1
            result = {'revision': expected, 'transactions': count, 'sha256': digest.hexdigest()}
        def publish(connection):
            if revision(connection, job['league_id']) != expected:
                raise AdapterFailure('data_changed')
            return result
        return publish


class UnavailableHistory:
    def stage(self, queue, job, stop):
        raise AdapterFailure('source_unavailable', retryable=False)


class Worker:
    def __init__(self, queue, *, adapters=None, stop=None):
        self.queue = queue
        from .quantities import QuantityAdapter
        from .prices import PricesAdapter
        from .valuation import ValuationAdapter
        self.adapters = adapters or {'local_verify': LocalVerification(), 'history': UnavailableHistory(), 'quantities': QuantityAdapter(), 'prices': PricesAdapter(), 'valuations': ValuationAdapter()}
        self.stop = stop or threading.Event()
        self.id = str(uuid.uuid4())

    def run_once(self):
        job = self.queue.claim(self.id)
        if not job:
            return False
        finished, lost = threading.Event(), threading.Event()
        def renew():
            while not finished.wait(max(.05, self.queue.lease_seconds / 3)):
                try:
                    self.queue.renew(job)
                except (LeaseLost, sqlite3.Error):
                    lost.set()
                    return
        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            publish = self.adapters[job['kind']].stage(self.queue, job, self.stop)
            if not lost.is_set():
                self.queue.complete(job, publish)
                if job['kind'] in {'prices','quantities'}:
                    with connect(self.queue.path, readonly=True) as c:
                        prices_available=c.execute('SELECT 1 FROM price_snapshots WHERE league_id=? LIMIT 1',(job['league_id'],)).fetchone()
                    if prices_available:self.queue.enqueue(job['league_id'],'valuations','automatic')
                log.info('Job finished kind=%s', job['kind'])
        except LeaseLost:
            log.warning('Lease lost; staged result discarded')
        except Exception as error:
            failure = error if isinstance(error, AdapterFailure) else AdapterFailure('adapter_error')
            try:
                self.queue.fail(job, failure.code, retryable=failure.retryable, retry_after=failure.retry_after)
            except LeaseLost:
                pass
            log.warning('Job did not complete kind=%s code=%s', job['kind'], failure.code)
        finally:
            finished.set()
            thread.join()
        return True

    def run(self):
        # flock prevents two live worker loops on the same DB, even across checkouts.
        lock = Path(self.queue.path).resolve().with_suffix('.worker.lock')
        with lock.open('a+b') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A worker already owns this database') from None
            heartbeat_done = threading.Event()
            def heartbeat():
                while not heartbeat_done.wait(2):
                    try:
                        self.queue.heartbeat(self.id)
                    except sqlite3.Error:
                        log.warning('Worker heartbeat temporarily unavailable')
            self.queue.heartbeat(self.id)
            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            try:
                log.info('Worker ready')
                while not self.stop.is_set():
                    try:
                        worked = self.run_once()
                    except sqlite3.Error:
                        log.warning('Queue temporarily unavailable')
                        worked = False
                    if not worked:
                        self.stop.wait(.5)
            finally:
                heartbeat_done.set()
                thread.join()
                self.queue.heartbeat(self.id, 'stopped')
                log.info('Worker stopped')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=os.environ.get('POE2GUILD_DATABASE', ROOT / 'data/poe2guild.sqlite'))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    worker = Worker(Queue(args.database))
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_args: worker.stop.set())
    worker.run()


if __name__ == '__main__':
    main()
