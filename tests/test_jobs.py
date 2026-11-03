import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import time
import unittest
import fcntl
import sqlite3
from backend.database import MIGRATIONS, SCHEMA_VERSION

from tests.auth_helpers import create_app
from backend.archive_import import canonical, normalize
from backend.browsing import revision
from backend.database import connect, migrate
from backend.jobs import Queue, JobRejected, LeaseLost
from backend.worker import Worker, LocalVerification, AdapterFailure


def enqueue_process(path, league, output):
    output.put(Queue(path, history_available=True).enqueue(league, trigger='automatic'))


def blocking_worker(path, notification):
    class BlockingAdapter:
        def stage(self, queue, job, stop):
            notification.put(job)
            stop.wait(30)
            return lambda c: {}
    Worker(Queue(path, lease_seconds=.2, cooldown=0), adapters={'local_verify': BlockingAdapter()}).run()


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'queue.sqlite'
        migrate(self.path)
        self.now = 100000.0
        self.queue = Queue(self.path, clock=lambda: self.now, history_available=True, cooldown=0, fresh_seconds=0)
        with connect(self.path) as c:
            for league, archive in [('A', 0), ('B', 0), ('Archive', 1)]:
                c.execute("INSERT INTO leagues(id,name,game,realm,archived,fetch_available) VALUES (?,?,'poe2','poe2',?,1)", (league, league, archive))
                c.execute('UPDATE leagues SET lifecycle=? WHERE id=?',('ended' if archive else 'active',league))
            c.execute("INSERT INTO sources(id,source_key,provider,created_at) VALUES (1,'test','test','2026-01-01T00:00:00Z')")
            c.execute("INSERT INTO import_runs(id,source_id,started_at,status,manifest_sha256) VALUES ('import',1,'2026-01-01T00:00:00Z','completed','hash')")
            c.execute("INSERT INTO revisions VALUES ('baseline','A','import','2026-01-01T00:00:00Z','raw_import','test',NULL)")
        self.client = create_app({'TESTING': True, 'DATABASE_FILE': self.path, 'HISTORY_AVAILABLE': True}).test_client()

    def enqueue(self, league='A', trigger='manual', kind='history'):
        return self.queue.enqueue(league, kind, trigger)

    def lease(self):
        return self.queue.claim('worker')

    def test_cross_league_scope_deduplication_and_manual_promotes_existing_queued_job(self):
        first = self.enqueue(trigger='automatic')
        second = self.enqueue('B')
        self.assertEqual(second['outcome'], 'coalesced')
        self.assertEqual(first['job_id'], second['job_id'])
        self.assertEqual(self.lease()['trigger_kind'], 'manual')

    def test_two_processes_enqueue_exactly_one_job(self):
        context = multiprocessing.get_context('fork')
        output = context.Queue()
        processes = [context.Process(target=enqueue_process, args=(self.path, league, output)) for league in ('A', 'B')]
        for process in processes: process.start()
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        results = [output.get(timeout=2) for _ in processes]
        self.assertEqual({r['outcome'] for r in results}, {'queued', 'coalesced'})
        self.assertEqual(len({r['job_id'] for r in results}), 1)

    def test_automatic_limit_is_shared_and_manual_bypasses_only_that_limit(self):
        for _ in range(2):
            self.enqueue(trigger='automatic')
            self.queue.complete(self.lease(), lambda c: {'ok': True})
        self.assertEqual(self.enqueue('B', 'automatic')['reason'], 'automatic_limit')
        manual = self.enqueue('B')
        self.assertEqual(manual['outcome'], 'queued')
        self.queue.complete(self.lease(), lambda c: {'ok': True})
        self.now += 3600
        self.assertEqual(self.enqueue(trigger='automatic')['outcome'], 'queued')

    def test_retries_consume_shared_automatic_budget(self):
        self.enqueue(trigger='automatic')
        self.queue.fail(self.lease())
        self.now += 5
        second = self.lease()
        self.assertEqual(second['attempts'], 2)
        self.queue.fail(second)
        self.now += 10
        self.assertIsNone(self.lease())
        job = self.queue.status('A')['history']['job']
        self.assertEqual(job['error_code'], 'automatic_limit')
        self.now += 3600
        self.assertEqual(self.lease()['attempts'], 3)

    def test_backoff_exhaustion_retains_previous_success_and_sanitizes_error(self):
        self.enqueue()
        self.queue.complete(self.lease(), lambda c: {'old': True})
        self.enqueue()
        for attempt, delay in [(1, 5), (2, 10), (3, 20)]:
            job = self.lease()
            self.assertEqual(job['attempts'], attempt)
            self.queue.fail(job, 'PRIVATE_TOKEN=secret')
            self.assertIsNone(self.lease())
            self.now += delay
        status = self.queue.status('A')['history']
        self.assertEqual(status['job']['state'], 'failed')
        self.assertEqual(status['job']['error_code'], 'adapter_error')
        self.assertEqual(status['last_result'], {'old': True})
        self.assertNotIn('PRIVATE', json.dumps(status))

    def test_manual_respects_provider_retry_after_and_deduplication(self):
        self.enqueue()
        lease = self.lease()
        self.queue.fail(lease, 'provider_limited', retry_after=120)
        self.assertEqual(self.enqueue()['outcome'], 'coalesced')
        self.now += 119
        self.assertIsNone(self.lease())
        self.now += 1
        self.assertIsNotNone(self.lease())

    def test_completed_cooldown_applies_to_new_manual_jobs(self):
        self.queue.cooldown = 30
        self.enqueue()
        self.queue.complete(self.lease(), lambda c: {})
        self.assertEqual(self.enqueue()['reason'], 'cooldown')
        self.assertIsNone(self.lease())
        self.now += 30
        self.assertIsNotNone(self.lease())

    def test_restart_reclaims_expired_lease_and_fences_all_old_operations(self):
        self.enqueue()
        old = self.lease()
        self.now += 31
        restarted = Queue(self.path, clock=lambda: self.now, history_available=True)
        current = restarted.claim('replacement')
        self.assertNotEqual(old['lease_token'], current['lease_token'])
        for call in (lambda: self.queue.renew(old), lambda: self.queue.fail(old), lambda: self.queue.complete(old, lambda c: {})):
            with self.assertRaises(LeaseLost): call()
        restarted.complete(current, lambda c: {'new': True})
        self.assertEqual(self.queue.status('A')['history']['last_result'], {'new': True})

    def test_expired_publication_rolls_back_data_cursor_and_revision(self):
        self.enqueue()
        lease = self.lease()
        def slow_publish(c):
            c.execute("INSERT INTO metadata VALUES ('should_rollback','yes')")
            self.now += 31
            return {}
        with self.assertRaises(LeaseLost): self.queue.complete(lease, slow_publish)
        with connect(self.path) as c:
            self.assertIsNone(c.execute("SELECT * FROM metadata WHERE key='should_rollback'").fetchone())

    def test_renewal_prevents_reclaim(self):
        self.enqueue()
        old = self.lease()
        self.now += 20
        self.queue.renew(old)
        self.now += 20
        self.assertIsNone(self.lease())
        self.queue.complete(old, lambda c: {})

    def test_queue_survives_restart_before_claim(self):
        first = self.enqueue()
        queue = Queue(self.path, clock=lambda: self.now, history_available=True)
        self.assertEqual(queue.claim('after-restart')['id'], first['job_id'])

    def test_ended_status_blocks_enqueue_claim_and_publish_without_session_adapter(self):
        self.assertEqual(self.enqueue('Archive')['reason'], 'not_monitored')
        self.enqueue()
        with connect(self.path) as c: c.execute("UPDATE leagues SET lifecycle='ended' WHERE id='A'")
        self.assertIsNone(self.lease())
        with connect(self.path) as c: c.execute("UPDATE leagues SET lifecycle='active' WHERE id='A'")
        self.enqueue()
        lease = self.lease()
        with connect(self.path) as c: c.execute("UPDATE leagues SET lifecycle='ended' WHERE id='A'")
        self.queue.complete(lease, lambda c: self.fail('Archived publication ran'))
        self.assertEqual(self.queue.status('A')['history']['job']['error_code'], 'not_monitored')

    def test_no_adapter_means_unavailable_not_fake_success(self):
        queue = Queue(self.path)
        self.assertEqual(queue.enqueue('A', trigger='manual')['reason'], 'source_unavailable')
        self.assertIsNone(queue.status('A')['history']['last_success_at'])

    def test_legacy_local_archive_flag_does_not_disable_an_active_league(self):
        with connect(self.path) as c:
            c.execute("UPDATE leagues SET archived=1,lifecycle='active' WHERE id='A'")
        self.assertEqual(self.enqueue()['outcome'],'queued')

    def test_local_verification_does_not_fetch_change_revision_or_generate_report(self):
        self.add_record('A')
        before = self.queue.status('A')['revision']
        self.enqueue(kind='local_verify')
        self.assertTrue(Worker(self.queue).run_once())
        status = self.queue.status('A')
        self.assertEqual(status['local_verify']['job']['state'], 'completed')
        self.assertEqual(status['local_verify']['last_result']['transactions'], 1)
        self.assertEqual(status['revision'], before)
        self.assertIsNone(status['history']['last_success_at'])
        self.assertIsNone(status['last_generated_at'])

    def add_record(self, league):
        raw = dict(Date='2026-01-01T00:00:00Z', Id='1', League=league, Account='Alice', Action='added', Stash='Main', Item='Token', X='0', Y='0')
        values = normalize(raw, league)
        with connect(self.path) as c:
            c.execute('INSERT INTO transactions(source_id,league_id,external_id,occurred_at,account,action,stash,item,x,y,raw_json,normalized_sha256,normalization_version,import_id) '
                      "VALUES (1,?,'1',?,'Alice','added','Main','Token',0,0,?,?,'1','import')", (league, values['Date'], json.dumps(raw), hashlib.sha256(canonical(values).encode()).hexdigest()))

    def test_invalid_local_data_fails_without_overwriting_good_result(self):
        self.add_record('A')
        self.enqueue(kind='local_verify')
        Worker(self.queue).run_once()
        original = self.queue.status('A')['local_verify']['last_result']
        with connect(self.path) as c: c.execute("UPDATE transactions SET item='corrupted'")
        self.enqueue(kind='local_verify')
        Worker(self.queue).run_once()
        result = self.queue.status('A')['local_verify']
        self.assertEqual(result['job']['error_code'], 'local_data_invalid')
        self.assertEqual(result['last_result'], original)

    def test_worker_publication_can_atomically_update_revision_and_cursor(self):
        self.enqueue()
        class TestAdapter:
            def stage(adapter, queue, job, stop):
                def publish(c):
                    c.execute("INSERT INTO revisions VALUES ('new','A','import','2026-01-02T00:00:00Z','raw_import','test',NULL)")
                    c.execute("INSERT INTO source_cursors VALUES (1,'guild_history','next','2026-01-02T00:00:00Z')")
                    return {'revision': revision(c, 'A')}
                return publish
        before = self.queue.status('A')['revision']
        Worker(self.queue, adapters={'history': TestAdapter()}).run_once()
        after = self.queue.status('A')
        self.assertNotEqual(before, after['revision'])
        self.assertEqual(after['history']['last_result']['revision'], after['revision'])
        with connect(self.path) as c: self.assertEqual(c.execute('SELECT cursor FROM source_cursors').fetchone()[0], 'next')

    def test_worker_renews_lease_while_adapter_is_running(self):
        queue = Queue(self.path, lease_seconds=.15, history_available=True, cooldown=0, fresh_seconds=0)
        queue.enqueue('A', trigger='manual')
        class SlowAdapter:
            def stage(adapter, queue, job, stop):
                time.sleep(.4)
                return lambda c: {'ok': True}
        Worker(queue, adapters={'history': SlowAdapter()}).run_once()
        self.assertEqual(queue.status('A')['history']['job']['state'], 'completed')

    def test_http_validation_archives_and_offline_worker_status(self):
        url = '/api/leagues/Archive/refresh'
        response = self.client.post(url, json={'trigger': 'manual'})
        self.assertEqual((response.status_code, response.json['reason']), (200, 'not_monitored'))
        self.assertEqual(self.client.get(url).json['worker'], 'offline')
        for body in ([], {'kind': []}, {'trigger': 'invalid'}, {'unexpected': 1}, {'kind': 'local_verify', 'trigger': 'automatic'}):
            self.assertEqual(self.client.post(url, json=body).status_code, 400)
        self.assertEqual(self.client.post(url, data='{}').status_code, 415)
        self.assertEqual(self.client.post(url, json={}, headers={'Origin': 'https://other.test'}).status_code, 403)
        self.assertEqual(self.client.get('/api/leagues/missing/refresh').status_code, 404)
        self.assertEqual(self.client.post('/api/leagues/missing/refresh', json={}).status_code, 404)
        response = self.client.post(url, json={'kind': 'local_verify', 'trigger': 'manual'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.post(url, json={'kind': 'local_verify', 'trigger': 'manual'}).json['job_id'], response.json['job_id'])
        self.queue.heartbeat('test')
        self.assertEqual(self.queue.status('Archive')['worker'], 'online')
        self.now += 16
        self.assertEqual(self.queue.status('Archive')['worker'], 'offline')

    def test_local_automatic_requests_are_rejected(self):
        with self.assertRaises(JobRejected): self.queue.enqueue('A', 'local_verify', 'automatic')

    def test_manual_promotes_limited_retry_but_preserves_provider_wait(self):
        self.enqueue(trigger='automatic')
        self.queue.fail(self.lease())
        self.now += 5
        self.queue.fail(self.lease(), 'provider_limited', retry_after=120)
        self.now += 120
        self.assertIsNone(self.lease())  # automatic budget exhausted
        previous = self.queue.status('A')['history']['job']['id']
        self.assertEqual(self.enqueue()['job_id'], previous)
        self.assertEqual(self.lease()['trigger_kind'], 'manual')

    def test_upgrade_from_phase1_preserves_data_and_rejects_placeholder_jobs(self):
        path = Path(self.temp.name) / 'old.sqlite'
        script = (MIGRATIONS / '001_initial.sql').read_text()
        with sqlite3.connect(path) as c:
            c.executescript(script)
            c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,sha256 TEXT)')
            c.execute('INSERT INTO schema_migrations VALUES (1,?,?)', ('001_initial.sql', hashlib.sha256(script.encode()).hexdigest()))
            c.execute('PRAGMA user_version=1')
            c.execute("INSERT INTO metadata VALUES ('instance_id','preserved')")
            c.execute("INSERT INTO jobs(id,resource,state,trigger_kind,created_at) VALUES ('old','unknown','queued','manual','2026-01-01')")
        migrate(path)
        migrate(path)
        with connect(path) as c:
            self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()[0], 'preserved')
            self.assertEqual(c.execute('SELECT state,error_code FROM jobs').fetchone()[:], ('failed', 'legacy_job'))
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)

    def test_singleton_worker_lock_rejects_second_loop(self):
        lock = self.path.with_suffix('.worker.lock')
        with lock.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'already owns'):
                Worker(self.queue).run()

    def test_real_process_crash_keeps_job_and_restart_fences_old_token(self):
        self.enqueue(kind='local_verify')
        context = multiprocessing.get_context('fork')
        notification = context.Queue()
        process = context.Process(target=blocking_worker, args=(self.path, notification))
        process.start()
        try:
            old = notification.get(timeout=5)
        finally:
            process.kill()
            process.join(5)
        self.now = float(old['lease_until']) + .1
        self.assertTrue(Worker(self.queue).run_once())
        self.assertEqual(self.queue.status('A')['local_verify']['job']['state'], 'completed')
        with self.assertRaises(LeaseLost): self.queue.complete(old, lambda c: {'stale': True})

    def test_delayed_first_attempt_moves_reservation_to_actual_start(self):
        self.enqueue(trigger='automatic')
        self.now += 3601
        self.queue.complete(self.lease(), lambda c: {})
        self.enqueue(trigger='automatic')
        self.queue.complete(self.lease(), lambda c: {})
        self.assertEqual(self.enqueue(trigger='automatic')['reason'], 'automatic_limit')

    def test_manual_promotion_still_waits_for_provider_cooldown(self):
        self.enqueue(trigger='automatic')
        self.queue.fail(self.lease(), 'provider_limited', retry_after=120)
        self.assertEqual(self.enqueue()['outcome'], 'coalesced')
        self.assertIsNone(self.lease())
        self.now += 120
        self.assertEqual(self.lease()['trigger_kind'], 'manual')

    def test_fresh_success_skips_automatic_work_without_spending_attempt(self):
        self.queue.fresh_seconds = 1800
        self.enqueue(trigger='automatic')
        self.queue.complete(self.lease(), lambda c: {})
        self.assertEqual(self.enqueue('B', 'automatic')['outcome'], 'fresh')
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM automatic_attempts').fetchone()[0], 1)
        self.now += 1800
        self.assertEqual(self.enqueue('B', 'automatic')['outcome'], 'queued')
