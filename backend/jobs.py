"""SQLite queue. Every policy decision and publication is serialized by BEGIN IMMEDIATE.

Adapters perform slow work outside the transaction. Only a live lease holder may
publish its staged result, cursor and successful job state in one transaction.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import time
import uuid

from .database import connect, require_schema


class LeaseLost(Exception):
    pass


class JobRejected(Exception):
    def __init__(self, code):
        self.code = code


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def scope_key(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Queue:
    def __init__(self, path, *, clock=time.time, lease_seconds=30, cooldown=30,
                 history_scope=('ggg', 'unconfigured', 'guild_history'), history_available=False, fresh_seconds=1800, prices_available=True, catalog_available=False, connection_file=None):
        self.path, self.clock, self.lease_seconds, self.cooldown = path, clock, lease_seconds, cooldown
        self.history_scope, self.history_available = history_scope, history_available
        self.fresh_seconds = fresh_seconds
        self.prices_available = prices_available
        self.catalog_available = catalog_available
        self.connection_file = connection_file

    @contextmanager
    def transaction(self):
        with connect(self.path) as connection:
            require_schema(connection)
            connection.execute('BEGIN IMMEDIATE')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def scope(self, league_id, kind):
        if kind=='league_catalog':return scope_key(('catalog','poe2','pc'))
        if kind=='history' and self.connection_file:
            from .ggg_connection import GGGConnectionStore
            configuration=GGGConnectionStore(self.connection_file).get()
            if configuration['guild_id']:return scope_key(('ggg',configuration['guild_id'],'guild_history'))
        return scope_key(self.history_scope if kind == 'history' else ('local', str(league_id), 'verify' if kind == 'local_verify' else kind))

    @staticmethod
    def league(connection, league_id):
        row = connection.execute('SELECT * FROM leagues WHERE id=?', (league_id,)).fetchone()
        if not row:
            raise JobRejected('league_not_found')
        return row

    def restriction(self, league, kind):
        if kind=='league_catalog':return None if self.catalog_available else 'source_unavailable'
        if kind in {'history','prices'} and not dict(league).get('monitored',1):return 'not_monitored'
        if kind=='history' and self.connection_file:
            from .ggg_connection import GGGConnectionStore
            configuration=GGGConnectionStore(self.connection_file).get()
            if configuration['enabled'] and configuration['session_id']:
                return 'history_auth_failed' if configuration['state']=='rejected' else None
        if kind == 'prices' and not self.prices_available:return 'source_unavailable'
        if kind == 'history':
            if dict(league).get('lifecycle','unknown')=='ended':
                return 'archived'
            if not self.history_available or not league['fetch_available']:
                return 'source_unavailable'
        return None

    @staticmethod
    def budget(connection, key, now):
        rows = connection.execute('SELECT attempted_at FROM automatic_attempts WHERE scope_key=? AND attempted_at>? '
                                  'ORDER BY attempted_at', (key, now - 3600)).fetchall()
        return rows[0][0] + 3600 if len(rows) >= 2 else None

    @staticmethod
    def recover(connection, now):
        # Retain fencing history in the old token; claim replaces it before execution.
        connection.execute("UPDATE jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,"
                           "available_at=?,error_code='lease_expired',finished_at=CASE WHEN attempts>=3 THEN ? ELSE NULL END "
                           "WHERE state='running' AND CAST(lease_until AS REAL)<=?", (now, stamp(now), now))

    def enqueue(self, league_id, kind='history', trigger='automatic'):
        if kind not in {'history', 'local_verify', 'quantities', 'prices', 'valuations', 'league_catalog'} or trigger not in {'automatic', 'manual'}:
            raise JobRejected('invalid_refresh_request')
        if kind == 'local_verify' and trigger != 'manual':
            raise JobRejected('invalid_refresh_request')
        key, now = self.scope(league_id, kind), self.clock()
        with self.transaction() as connection:
            league = None if kind=='league_catalog' else self.league(connection, league_id)
            reason = self.restriction(league, kind)
            if reason:
                return {'outcome': 'unavailable', 'reason': reason, 'job_id': None}
            if kind == 'quantities':
                from .quantities import current_run
                if current_run(connection, league):
                    return {'outcome': 'fresh', 'reason': 'fresh', 'job_id': None}
            if kind == 'valuations':
                from .valuation import current_valuation
                if current_valuation(connection, league)[0]:
                    return {'outcome':'fresh','reason':'fresh','job_id':None}
            if kind in {'prices','league_catalog'}:
                scope=connection.execute('SELECT last_success_at FROM refresh_scopes WHERE scope_key=?',(key,)).fetchone()
                if scope and scope[0] and datetime.fromisoformat(scope[0].replace('Z','+00:00')).timestamp()+3600>now:
                    return {'outcome':'fresh','reason':'fresh','job_id':None}
            self.recover(connection, now)
            current = connection.execute("SELECT * FROM jobs WHERE scope_key=? AND state IN ('queued','running')", (key,)).fetchone()
            if current:
                if trigger == 'manual' and current['state'] == 'queued' and current['trigger_kind'] == 'automatic':
                    # Promote the existing job, never create a duplicate or bypass source cooldown.
                    cooldown = connection.execute('SELECT not_before FROM refresh_scopes WHERE scope_key=?', (key,)).fetchone()[0]
                    if not current['attempts']:
                        connection.execute('DELETE FROM automatic_attempts WHERE job_id=?', (current['id'],))
                    connection.execute("UPDATE jobs SET trigger_kind='manual',available_at=?,error_code=CASE WHEN error_code='automatic_limit' THEN NULL ELSE error_code END WHERE id=?",
                                       (max(now, cooldown), current['id']))
                return {'outcome': 'coalesced', 'reason': None, 'job_id': current['id']}
            if trigger == 'automatic' and kind == 'history':
                scope = connection.execute('SELECT last_success_at FROM refresh_scopes WHERE scope_key=?', (key,)).fetchone()
                if scope and scope['last_success_at']:
                    fresh_until = datetime.fromisoformat(scope['last_success_at'].replace('Z', '+00:00')).timestamp() + self.fresh_seconds
                    if fresh_until > now:
                        return {'outcome': 'fresh', 'reason': 'fresh', 'job_id': None, 'retry_at': stamp(fresh_until)}
                limited_until = self.budget(connection, key, now)
                if limited_until:
                    return {'outcome': 'limited', 'reason': 'automatic_limit', 'job_id': None, 'retry_at': stamp(limited_until)}
            connection.execute('INSERT OR IGNORE INTO refresh_scopes(scope_key) VALUES (?)', (key,))
            cooldown = connection.execute('SELECT not_before FROM refresh_scopes WHERE scope_key=?', (key,)).fetchone()[0]
            job = str(uuid.uuid4())
            connection.execute('INSERT INTO jobs(id,resource,state,trigger_kind,created_at,scope_key,kind,league_id,available_at) '
                               "VALUES (?,?,'queued',?,?,?,?,?,?)", (job, 'guild_history' if kind == 'history' else kind,
                               trigger, stamp(now), key, kind, league_id, max(now, cooldown)))
            if trigger == 'automatic' and kind == 'history':
                connection.execute('INSERT INTO automatic_attempts(scope_key,job_id,attempted_at) VALUES (?,?,?)', (key, job, now))
            return {'outcome': 'queued', 'reason': 'cooldown' if cooldown > now else None, 'job_id': job,
                    'retry_at': stamp(max(now, cooldown))}

    def claim(self, worker_id):
        now = self.clock()
        with self.transaction() as connection:
            self.recover(connection, now)
            for row in connection.execute("SELECT * FROM jobs WHERE state='queued' AND available_at<=? ORDER BY created_at,id", (now,)).fetchall():
                reason = self.restriction(None if row['kind']=='league_catalog' else self.league(connection, row['league_id']), row['kind'])
                if reason:
                    connection.execute("UPDATE jobs SET state='failed',error_code=?,finished_at=? WHERE id=?", (reason, stamp(now), row['id']))
                    continue
                cooldown = connection.execute('SELECT not_before FROM refresh_scopes WHERE scope_key=?', (row['scope_key'],)).fetchone()[0]
                if cooldown > now:
                    connection.execute('UPDATE jobs SET available_at=? WHERE id=?', (cooldown, row['id']))
                    continue
                if row['trigger_kind'] == 'automatic' and row['kind'] == 'history':
                    if not row['attempts']:
                        connection.execute('DELETE FROM automatic_attempts WHERE job_id=?', (row['id'],))
                    limited_until = self.budget(connection, row['scope_key'], now)
                    if limited_until:
                        connection.execute("UPDATE jobs SET available_at=?,error_code='automatic_limit' WHERE id=?", (limited_until, row['id']))
                        continue
                    connection.execute('INSERT INTO automatic_attempts(scope_key,job_id,attempted_at) VALUES (?,?,?)', (row['scope_key'], row['id'], now))
                token = str(uuid.uuid4())
                connection.execute("UPDATE jobs SET state='running',lease_token=?,lease_until=?,worker_id=?,attempts=attempts+1 WHERE id=?",
                                   (token, now + self.lease_seconds, worker_id, row['id']))
                return dict(connection.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())
        return None

    def assert_lease(self, connection, lease):
        row = connection.execute('SELECT * FROM jobs WHERE id=?', (lease['id'],)).fetchone()
        if not row or row['state'] != 'running' or row['lease_token'] != lease['lease_token'] or float(row['lease_until']) <= self.clock():
            raise LeaseLost()
        return row

    def renew(self, lease):
        with self.transaction() as connection:
            self.assert_lease(connection, lease)
            connection.execute('UPDATE jobs SET lease_until=? WHERE id=?', (self.clock() + self.lease_seconds, lease['id']))

    def complete(self, lease, publish):
        """publish(connection) is a short, transactional callback over already staged data."""
        with self.transaction() as connection:
            row = self.assert_lease(connection, lease)
            reason = self.restriction(None if row['kind']=='league_catalog' else self.league(connection, row['league_id']), row['kind'])
            if reason:
                connection.execute("UPDATE jobs SET state='failed',error_code=?,finished_at=? WHERE id=?", (reason, stamp(self.clock()), row['id']))
                return
            result = publish(connection)
            # Never publish after a lease expires even during a slow callback.
            self.assert_lease(connection, lease)
            now = self.clock()
            payload = json.dumps(result, separators=(',', ':'))
            connection.execute("UPDATE jobs SET state='completed',error_code=NULL,result_json=?,finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",
                               (payload, stamp(now), row['id']))
            connection.execute('UPDATE refresh_scopes SET last_success_at=?,last_result_json=?,not_before=? WHERE scope_key=?',
                               (stamp(now), payload, now + self.cooldown, row['scope_key']))
            return result

    def fail(self, lease, error_code='adapter_error', *, retryable=True, retry_after=0):
        # Codes are internal constants. Never persist exceptions/requests/credentials.
        if error_code not in {'adapter_error', 'source_unavailable', 'local_data_invalid', 'interrupted', 'provider_limited', 'data_changed', 'history_auth_failed', 'history_source_failed', 'history_invalid_response', 'history_cursor_repeated', 'history_page_limit', 'history_conflict'}:
            error_code = 'adapter_error'
        with self.transaction() as connection:
            row = self.assert_lease(connection, lease)
            now = self.clock()
            retry = retryable and row['attempts'] < 3
            delay = max(self.cooldown, 5 * 2 ** (row['attempts'] - 1), retry_after)
            connection.execute('UPDATE jobs SET state=?,error_code=?,available_at=?,finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?',
                               ('queued' if retry else 'failed', error_code, now + delay, None if retry else stamp(now), row['id']))
            connection.execute('UPDATE refresh_scopes SET not_before=MAX(not_before,?) WHERE scope_key=?', (now + delay, row['scope_key']))

    def heartbeat(self, worker_id, state='running'):
        with self.transaction() as connection:
            connection.execute('INSERT INTO worker_status VALUES (1,?,?,?,?) ON CONFLICT(singleton) DO UPDATE '
                               'SET worker_id=excluded.worker_id,pid=excluded.pid,heartbeat_at=excluded.heartbeat_at,state=excluded.state',
                               (worker_id, os.getpid(), self.clock(), state))

    def status(self, league_id):
        from .browsing import revision
        now = self.clock()
        with connect(self.path, readonly=True) as connection:
            require_schema(connection)
            connection.execute('BEGIN')
            league = self.league(connection, league_id)
            worker = connection.execute('SELECT * FROM worker_status WHERE singleton=1').fetchone()
            worker_online = bool(worker and worker['state'] == 'running' and worker['heartbeat_at'] > now - 15)
            result = {'league_id': league_id, 'revision': revision(connection, league_id),
                      'worker': 'online' if worker_online else 'offline', 'history': {}, 'local_verify': {}}
            for kind in ('history', 'local_verify', 'quantities', 'prices', 'valuations'):
                key = self.scope(league_id, kind)
                job = connection.execute('SELECT id,state,trigger_kind,attempts,error_code,available_at,finished_at FROM jobs '
                                         'WHERE scope_key=? ORDER BY rowid DESC LIMIT 1', (key,)).fetchone()
                scope = connection.execute('SELECT * FROM refresh_scopes WHERE scope_key=?', (key,)).fetchone()
                limited = self.budget(connection, key, now) if kind == 'history' else None
                result[kind] = {'available': self.restriction(league, kind) is None,
                                'reason': self.restriction(league, kind),
                                'last_success_at': scope['last_success_at'] if scope else None,
                                'last_result': json.loads(scope['last_result_json']) if scope and scope['last_result_json'] else None,
                                'cooldown_until': stamp(scope['not_before']) if scope and scope['not_before'] > now else None,
                                'automatic_retry_at': stamp(limited) if limited else None,
                                'job': dict(job) if job else None}
                if job:
                    result[kind]['job']['available_at'] = stamp(job['available_at'])
            generated = connection.execute("SELECT MAX(created_at) FROM revisions WHERE league_id=? AND kind='report'", (league_id,)).fetchone()[0]
            quantity_date = connection.execute('SELECT MAX(created_at) FROM quantity_runs WHERE league_id=?', (league_id,)).fetchone()[0]
            from .quantities import effective_settings, projection_hash, settings_hash
            result['quantity_settings_hash'] = projection_hash(league, connection)
            result['display_settings_hash'] = settings_hash(effective_settings(league, connection))
            result['last_generated_at'] = max(filter(None, (generated, quantity_date)), default=None)
            return result
