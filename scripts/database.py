#!/usr/bin/env python3
"""Database maintenance. Only this CLI migrates/imports; phase 3 HTTP writes jobs."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.archive_import import import_bundle, ImportRejected
from backend.database import DatabaseError, maintenance_lock, migrate, verify
from backend.database_lifecycle import rebuild, snapshot_legacy
from backend.repositories import database_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'migrate', 'import', 'verify', 'status', 'rebuild'))
    parser.add_argument('--database', type=Path, default=ROOT / 'data/poe2guild.sqlite')
    parser.add_argument('--archives', type=Path, default=ROOT / 'data')
    parser.add_argument('--legacy-source', type=Path)
    parser.add_argument('--source-key', default='legacy-primary')
    args = parser.parse_args()
    if args.legacy_source and args.command not in {'import', 'rebuild'}:
        parser.error('--legacy-source is supported only for import/rebuild')
    if args.command == 'status':
        return database_status(args.database)
    with maintenance_lock(args.database):
        if args.command in {'init', 'migrate'}:
            migrate(args.database)
            return database_status(args.database)
        if args.command == 'verify':
            return verify(args.database)
        archives, settings = args.archives, None
        if args.legacy_source:
            archives, settings = snapshot_legacy(args.legacy_source, args.database.resolve().parent)
        else:
            reference = args.archives / 'reference/phase0.json'
            if reference.exists():
                settings = json.loads(reference.read_text(encoding='utf-8')).get('legacy_settings')
            captured = args.archives / 'legacy-settings.json'
            if captured.exists():
                settings = json.loads(captured.read_text(encoding='utf-8'))
        if args.command == 'rebuild':
            return rebuild(args.database, archives, source_key=args.source_key, settings=settings,
                           run_directory=ROOT / '.run')
        migrate(args.database)
        result = import_bundle(args.database, archives, source_key=args.source_key, settings=settings)
        return {'import': result, 'verification': verify(args.database)}


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False, indent=2))
    except ImportRejected as error:
        print(json.dumps(error.result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except (DatabaseError, OSError, sqlite3.Error, ValueError, KeyError) as error:
        print(f'Database operation failed: {error}', file=sys.stderr)
        sys.exit(1)
