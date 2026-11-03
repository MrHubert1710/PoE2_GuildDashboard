"""Offline archive snapshots and verified atomic database replacement."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from .archive_import import canonical, import_bundle
from .archive_files import import_archives
from .database import connect, ensure_services_stopped, migrate, verify, DatabaseError
from .reference import capture_settings


ROOT = Path(__file__).resolve().parents[1]


def snapshot_legacy(source, data_directory):
    """Copy legacy input into an immutable, content-addressed local bundle."""
    source, data_directory = Path(source).resolve(), Path(data_directory).resolve()
    destination = data_directory / 'source-imports'
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=destination))
    try:
        manifest = import_archives(source, staging)
        settings = capture_settings(source / 'poe2logger/private_config.py')
        identity = {'files': manifest['leagues'], 'settings': settings}
        digest = hashlib.sha256(canonical(identity).encode()).hexdigest()
        target = destination / digest
        (staging / 'legacy-settings.json').write_text(canonical(settings) + '\n', encoding='utf-8')
        if not target.exists():
            staging.rename(target)
        return target, settings
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def rebuild(database_path, archive_root, *, source_key='legacy-primary', settings=None, run_directory=None):
    """Caller holds the target maintenance lock. Writers/services must be stopped."""
    database_path = Path(database_path).resolve()
    ensure_services_stopped(run_directory)
    temporary = database_path.with_name('.rebuild-' + str(uuid.uuid4()) + '.sqlite')
    restore_journal = False
    try:
        migrate(temporary)
        result = import_bundle(temporary, archive_root, source_key=source_key, settings=settings)
        # Observed market prices are source facts, not a disposable derived cache.
        # Keep them across a history rebuild; refuse to silently orphan a league.
        if database_path.exists():
            with connect(database_path, readonly=True) as old, connect(temporary) as fresh:
                if old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_snapshots'").fetchone():
                    known={row[0] for row in fresh.execute('SELECT id FROM leagues')}
                    priced={row[0] for row in old.execute('SELECT DISTINCT league_id FROM price_snapshots')}
                    if not priced <= known:
                        raise DatabaseError('Rebuild would discard a league with price observations; retain its history or restore a full backup')
                    fresh.execute('BEGIN IMMEDIATE')
                    try:
                        for table in ('price_http_cache','price_catalogs','price_categories','price_snapshots','price_quotes','price_aliases'):
                            rows=old.execute('SELECT * FROM '+table).fetchall()
                            if rows:
                                columns=','.join(rows[0].keys())
                                fresh.executemany('INSERT INTO '+table+'('+columns+') VALUES ('+','.join('?' for _ in rows[0])+')',[tuple(row) for row in rows])
                        fresh.commit()
                    except BaseException:fresh.rollback();raise
        check = verify(temporary)
        with connect(temporary) as connection:
            if connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise DatabaseError('Temporary database checkpoint is busy')
            connection.execute('PRAGMA journal_mode=DELETE')
        ensure_services_stopped(run_directory)
        if database_path.exists():
            with connect(database_path) as connection:
                if connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                    raise DatabaseError('Database checkpoint is busy; stop readers and writers')
                connection.execute('PRAGMA journal_mode=DELETE')
                restore_journal = True
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, database_path)
        with connect(database_path):
            pass
        restore_journal = False
        descriptor = os.open(database_path.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {'import': result, 'verification': check}
    finally:
        if restore_journal and database_path.exists():
            with connect(database_path):
                pass
        for path in (temporary, Path(str(temporary) + '-wal'), Path(str(temporary) + '-shm')):
            path.unlink(missing_ok=True)
