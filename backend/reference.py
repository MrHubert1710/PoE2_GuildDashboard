"""Offline audit of phase 0 archives; no imports of legacy application code."""
import ast
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


FIELDS = ('Date', 'Id', 'League', 'Account', 'Action', 'Stash', 'Item', 'X', 'Y')


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def capture_settings(path):
    """Read only allowlisted literals. Never execute or import private_config."""
    result = {'target_stashes': [], 'stash_aliases': {}, 'timezone_expression': None,
              'provenance': 'current_legacy_config_not_verified_for_each_historical_league'}
    for node in ast.parse(Path(path).read_text(encoding='utf-8')).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        name = getattr(node.targets[0], 'id', '')
        if name == 'TARGET_STASHES':
            result['target_stashes'] = sorted(ast.literal_eval(node.value))
        elif name == 'STASH_ALIASES':
            result['stash_aliases'] = ast.literal_eval(node.value)
        elif name == 'DISPLAY_TIMEZONE':
            result['timezone_expression'] = ast.unparse(node.value)
    return result


def inspect_history(path, expected_league):
    issues = Counter()
    actions = Counter()
    stashes = Counter()
    seen = {}
    dates = []
    samples = {}
    accounts = set()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError('Unexpected history columns')
        count = 0
        for line, row in enumerate(reader, 2):
            count += 1
            if None in row or any(not row.get(field, '').strip() for field in FIELDS):
                issues['missing_or_extra_fields'] += 1
                continue
            if row['League'] != expected_league:
                issues['wrong_league'] += 1
            try:
                stamp = datetime.fromisoformat(row['Date'].replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    raise ValueError('Naive date')
                dates.append(stamp.astimezone(timezone.utc))
            except ValueError:
                issues['invalid_or_naive_date'] += 1
            key = row['Id']
            if key in seen:
                issues['duplicate_id' if seen[key] == row else 'conflicting_id'] += 1
            else:
                seen[key] = row
            if row['Action'] not in {'added', 'removed', 'modified'}:
                issues['unknown_action'] += 1
            actions[row['Action']] += 1
            stashes[row['Stash']] += 1
            accounts.add(row['Account'])
            sample = {field: row[field] for field in FIELDS if field != 'Account'}
            sample.update(line=line, row_sha256=hashlib.sha256(
                json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
            samples.setdefault(row['Action'], sample)
            if '×' in row['Item']:
                samples.setdefault('quantity_multiplication_sign', sample)
            if row['X'] == '0' and row['Y'] == '0':
                samples.setdefault('zero_coordinates', sample)
    return {'transactions': count, 'unique_ids': len(seen), 'accounts_count': len(accounts),
            'oldest_at': min(dates).isoformat() if dates else None,
            'newest_at': max(dates).isoformat() if dates else None,
            'actions': dict(sorted(actions.items())), 'stashes': dict(sorted(stashes.items())),
            'issues': dict(sorted(issues.items())), 'samples': samples,
            'history_sha256': sha256(path), 'ids': set(seen)}


def build_reference(data_root, legacy_root):
    data_root, legacy_root = Path(data_root).resolve(), Path(legacy_root).resolve()
    manifest = json.loads((data_root / 'import-manifest.json').read_text(encoding='utf-8'))
    result = {'schema_version': 1, 'phase': 0,
              'generated_at': datetime.now(timezone.utc).isoformat(), 'leagues': [],
              'legacy_settings': capture_settings(legacy_root / 'poe2logger/private_config.py')}
    result['legacy_code_sha256'] = {
        name: sha256(legacy_root / 'poe2logger' / name)
        for name in ('utils.py', 'processing.py', 'prices.py', 'dashboard.py')
        if (legacy_root / 'poe2logger' / name).is_file()}
    id_sets = []
    for entry in manifest['leagues']:
        name, directory = entry['name'], entry['directory']
        raw_root = data_root / 'leagues' / directory
        league_root = raw_root.resolve()
        if not league_root.is_relative_to(data_root / 'leagues') or raw_root.is_symlink():
            raise ValueError('Invalid league directory')
        verified = []
        for relative, expected in entry['files'].items():
            local = (data_root / relative).resolve()
            if not local.is_relative_to(league_root):
                raise ValueError('Archive path escapes league')
            suffix = local.relative_to(league_root)
            original = (legacy_root / 'logs' / directory / 'history.csv' if str(suffix) == 'history.csv'
                        else legacy_root / 'stash_reports' / directory / suffix.relative_to('reports'))
            if not original.resolve().is_relative_to(legacy_root):
                raise ValueError('Source path escapes legacy checkout')
            if sha256(local) != expected or sha256(original) != expected:
                raise ValueError('Archive differs from its source or import manifest')
            verified.append({'file': str(suffix), 'sha256': expected})
        if 'history.csv' not in {entry['file'] for entry in verified}:
            raise ValueError('History missing from import manifest')
        archive_files = {str(path.relative_to(league_root)) for path in league_root.rglob('*')
                         if path.is_file() and path.suffix in {'.csv', '.html', '.svg', '.json'}}
        if archive_files != {entry['file'] for entry in verified}:
            raise ValueError('Archive inventory differs from import manifest')
        stats = inspect_history(league_root / 'history.csv', name)
        if stats['transactions'] != entry['transactions']:
            raise ValueError('Transaction count differs from import manifest')
        id_sets.append(stats.pop('ids'))
        reports = []
        for report in sorted((league_root / 'reports').glob('*.html')):
            reports.append({'name': report.name, 'sha256': sha256(report), 'bytes': report.stat().st_size})
        prices = []
        for price in sorted((league_root / 'reports/price_cache').glob('*.json')):
            payload = json.loads(price.read_text(encoding='utf-8'))
            prices.append({'category_file': price.name, 'sha256': sha256(price),
                           'lines': len(payload.get('lines', [])),
                           'timestamp_provenance': 'unknown', 'league_provenance': 'legacy_directory'})
        result['leagues'].append({'name': name, **stats, 'reports': reports, 'prices': prices,
                                  'verified_files': verified, 'source_matches': True})
    counts = Counter(event_id for ids in id_sets for event_id in ids)
    result['cross_league_shared_ids'] = sum(count > 1 for count in counts.values())
    return result


def public_reference(reference):
    """Explicit allowlist: accounts, samples and config are not a public API."""
    if reference.get('schema_version') != 1 or not reference.get('leagues'):
        raise ValueError('Invalid reference snapshot')
    return {'schema_version': 1, 'phase': 0, 'generated_at': reference['generated_at'],
            'providers': json.loads(Path(__file__).with_name('provider_findings.json').read_text(encoding='utf-8')),
            'leagues': [{key: league[key] for key in (
                'name', 'transactions', 'oldest_at', 'newest_at', 'history_sha256',
                'issues', 'reports', 'prices', 'source_matches')} for league in reference['leagues']]}
