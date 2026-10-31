"""Non-destructive import of the old, unpartitioned data layout."""
import csv
import hashlib
import html
import io
import json
from pathlib import Path

from .config import (CSV_FIELDNAMES, LEAGUE_NAME, LEAGUE_PATHS,
                     LEGACY_LOG_DIR, LEGACY_DASHBOARD_FILE)
from .refresh import atomic_write
from .utils import get_csv_league, get_csv_value


def migrate_legacy_data(league=LEAGUE_NAME, paths=LEAGUE_PATHS,
                        legacy_logs=LEGACY_LOG_DIR,
                        legacy_dashboard=LEGACY_DASHBOARD_FILE):
    """Copy only the active league; keep all legacy sources for other leagues.

    Called under the report lock. Content fingerprints make the import restart
    safe even after merge_log_files has removed the imported temporary CSVs.
    Prices and refresh metadata cannot be attributed reliably and are not copied.
    """
    manifest_path = paths.logs / 'legacy_imports.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        manifest = {}
    imported = False
    for source in sorted(Path(legacy_logs).glob('*.csv')):
        if not source.is_file():
            continue
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if manifest.get(source.name) == digest:
            continue
        reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        count = 0
        for row in reader:
            if get_csv_league(row, reader.fieldnames) != league:
                continue
            normalized = {field: get_csv_value(row, field).strip() for field in CSV_FIELDNAMES}
            normalized['League'] = league
            if not all(normalized.values()):
                continue
            writer.writerow(normalized)
            count += 1
        if count:
            atomic_write(paths.logs / f'legacy_{digest}.csv', output.getvalue())
            imported = True
        manifest[source.name] = digest
        atomic_write(manifest_path, json.dumps(manifest))

    legacy_report = Path(legacy_dashboard)
    if not paths.latest_dashboard.exists() and legacy_report.is_file():
        page = legacy_report.read_text(encoding='utf-8')
        # Require the exact league field from the old renderer, not a substring
        # that might occur in a player name, item or another league's title.
        marker = f'<div class="subtitle">League: {html.escape(league)} | Stashes:'
        if marker in page:
            atomic_write(paths.latest_dashboard, page)
    return imported
