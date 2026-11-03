"""SQLite lifecycle. Reads are read-only; refresh POSTs/worker write jobs. Only CLI operations migrate."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import uuid


MIGRATIONS = Path(__file__).with_name('migrations')
SCHEMA_VERSION = 7


class DatabaseError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


@contextmanager
def connect(path, *, readonly=False):
    path = Path(path).resolve()
    if readonly:
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                                     isolation_level=None, timeout=5)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, isolation_level=None, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=5000')
        if not readonly:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
        yield connection
    finally:
        connection.close()


@contextmanager
def maintenance_lock(path):
    lock = Path(path).with_name(Path(path).name + '.maintenance.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DatabaseError('Another database maintenance operation is running') from error
        yield


def migrate(path):
    with connect(path) as connection:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise DatabaseError('Database schema is newer than this application')
        connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations '
                           '(version INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL)')
        applied = {row['version']: row for row in connection.execute('SELECT * FROM schema_migrations')}
        if set(applied) != set(range(1, version + 1)):
            raise DatabaseError('Migration ledger does not match schema version')
        for migration in sorted(MIGRATIONS.glob('*.sql')):
            number = int(migration.name.split('_', 1)[0])
            script = migration.read_text(encoding='utf-8')
            digest = hashlib.sha256(script.encode()).hexdigest()
            if number in applied:
                if applied[number]['sha256'] != digest:
                    raise DatabaseError('Applied migration has changed')
                continue
            if number != version + 1:
                raise DatabaseError('Migration sequence has a gap')
            try:
                connection.executescript(
                    'BEGIN IMMEDIATE;\n' + script +
                    f"\nINSERT INTO schema_migrations VALUES ({number}, '{migration.name}', '{digest}');"
                    f'\nPRAGMA user_version={number};\nCOMMIT;')
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            version = number
        connection.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('instance_id', str(uuid.uuid4())))


def require_schema(connection):
    if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
        raise DatabaseError('Database schema needs migration')


def verify(path):
    with connect(path) as connection:
        require_schema(connection)
        connection.execute('BEGIN IMMEDIATE')
        try:
            if [row[0] for row in connection.execute('PRAGMA integrity_check')] != ['ok']:
                raise DatabaseError('SQLite integrity check failed')
            if connection.execute('PRAGMA foreign_key_check').fetchone():
                raise DatabaseError('Foreign key check failed')
            count = connection.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
            stamp = utc_now()
            latest = connection.execute("SELECT id FROM import_runs WHERE status='completed' ORDER BY rowid DESC LIMIT 1").fetchone()
            connection.execute('INSERT INTO database_checks(checked_at,transaction_count,last_completed_import_id,result) VALUES (?,?,?,?)',
                               (stamp, count, latest[0] if latest else None, 'ok'))
            connection.commit()
            return {'result': 'ok', 'transactions': count, 'checked_at': stamp}
        except BaseException:
            connection.rollback()
            raise


def ensure_services_stopped(run_directory):
    if run_directory is None:
        return
    for path in Path(run_directory).glob('*.pid'):
        try:
            pid = int(path.read_text().strip())
            if pid <= 0:
                raise ValueError('Invalid PID')
        except ValueError as error:
            raise DatabaseError('Invalid service process record; inspect before rebuilding') from error
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        raise DatabaseError('Stop web/worker services before rebuilding the database')
