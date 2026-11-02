#!/usr/bin/env python3
"""Rebuild local archive copies from the legacy checkout without using its code/API."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def import_archives(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == ROOT or source in destination.parents or destination in source.parents:
        raise ValueError('Source and destination must be independent directories')
    histories = sorted((source / 'logs').glob('*/history.csv'))
    if not histories:
        raise ValueError('No league histories found in the legacy checkout')
    manifest = {'imported_at': datetime.now(timezone.utc).isoformat(), 'leagues': []}
    for history in histories:
        league_directory = history.parent.name
        with history.open(encoding='utf-8-sig', newline='') as stream:
            count = 0
            leagues = set()
            for row in csv.DictReader(stream):
                leagues.add(row['League'])
                count += 1
        if len(leagues) != 1 or not count:
            raise ValueError(f'Expected non-empty single-league history: {history}')
        target = destination / 'leagues' / league_directory
        files = [(history, target / 'history.csv')]
        reports = source / 'stash_reports' / league_directory
        if reports.exists():
            files.extend((path, target / 'reports' / path.relative_to(reports))
                         for path in sorted(reports.rglob('*'))
                         if path.is_file() and not path.is_symlink()
                         and 'price_cache' in path.parts and path.suffix == '.json')
        hashes = {}
        for original, copied in files:
            expected = checksum(original)
            if copied.exists() and checksum(copied) != expected:
                raise ValueError(f'Existing archive differs; remove/rebuild data first: {copied}')
            copied.parent.mkdir(parents=True, exist_ok=True)
            if not copied.exists():
                shutil.copy2(original, copied)
            if checksum(copied) != expected:
                raise ValueError(f'Copy verification failed: {copied}')
            hashes[str(copied.relative_to(destination))] = expected
        manifest['leagues'].append({'name': leagues.pop(), 'directory': league_directory,
                                   'transactions': count, 'files': hashes})
        print(f'Imported {league_directory}: {count} transactions, {len(files)} verified files')
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / 'import-manifest.json.tmp'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(destination / 'import-manifest.json')
    return manifest


