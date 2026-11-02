import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from backend.contracts import StoredCredential
from backend.reference import FIELDS, build_reference, capture_settings, inspect_history, public_reference

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('archive_import', ROOT / 'scripts/import-legacy-data.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.data = self.root / 'old', self.root / 'data'
        config = self.source / 'poe2logger/private_config.py'
        config.parent.mkdir(parents=True)
        config.write_text("SESSION_ID = 'DO_NOT_EXPOSE'\n"
                          "TARGET_STASHES = {'Test'}\nSTASH_ALIASES = {'Typo': 'Test'}\n"
                          "DISPLAY_TIMEZONE = timezone(timedelta(hours=2))\n"
                          "raise RuntimeError('Never execute config')\n")
        for league in ('Alpha', 'Beta'):
            self.write_history(self.source / 'logs' / league / 'history.csv', [
                ['2026-01-01T12:00:00Z', '1', league, 'PRIVATE_PLAYER', 'added', 'Test', 'Chaos Orb', '0', '0']])
            reports = self.source / 'stash_reports' / league
            (reports / 'price_cache').mkdir(parents=True)
            (reports / 'currentday.html').write_text('<html>saved report</html>')
            (reports / 'price_cache/currency.json').write_text('{"lines": [{"id": "one"}]}')
        importer.import_archives(self.source, self.data)

    def write_history(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(FIELDS)
            writer.writerows(rows)

    def test_audit_verifies_files_counts_reports_and_uncertain_price_provenance(self):
        result = build_reference(self.data, self.source)
        self.assertEqual(result['cross_league_shared_ids'], 1)
        for league in result['leagues']:
            self.assertEqual(league['transactions'], 1)
            self.assertEqual(league['issues'], {})
            self.assertTrue(league['source_matches'])
            self.assertEqual(len(league['verified_files']), 3)
            self.assertEqual(league['prices'][0]['timestamp_provenance'], 'unknown')
        self.assertEqual(result['legacy_settings']['stash_aliases'], {'Typo': 'Test'})

    def test_source_or_archive_mutation_fails_validation(self):
        for path in (self.source / 'stash_reports/Alpha/currentday.html',
                     self.data / 'leagues/Alpha/reports/currentday.html'):
            original = path.read_bytes()
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'differs'):
                build_reference(self.data, self.source)
            path.write_bytes(original)

    def test_manifest_path_cannot_escape_archive(self):
        path = self.data / 'import-manifest.json'
        manifest = json.loads(path.read_text())
        manifest['leagues'][0]['directory'] = '../../outside'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Invalid league directory'):
            build_reference(self.data, self.source)

    def test_untracked_archive_file_cannot_be_claimed_as_verified(self):
        extra = self.data / 'leagues/Alpha/reports/extra.html'
        extra.write_text('not in manifest')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            build_reference(self.data, self.source)

    def test_synthetic_edge_cases_are_reported_without_normalizing_raw_data(self):
        fixture = json.loads((ROOT / 'tests/fixtures/reference-cases.json').read_text())
        path = self.root / 'edge.csv'
        self.write_history(path, fixture['rows'])
        before = path.read_bytes()
        result = inspect_history(path, fixture['league'])
        self.assertEqual(result['transactions'], 8)
        self.assertEqual(result['issues'], fixture['expected_issues'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['samples']['zero_coordinates']['X'], '0')
        self.assertIn('Abbys/Expediton', result['stashes'])

    def test_public_payload_excludes_accounts_samples_settings_and_source_paths(self):
        reference = build_reference(self.data, self.source)
        payload = public_reference(reference)
        text = json.dumps(payload)
        for private in ('PRIVATE_PLAYER', 'DO_NOT_EXPOSE', 'legacy_settings', 'samples', str(self.source)):
            self.assertNotIn(private, text)
        self.assertEqual(len(payload['providers']['items']), 5)

    def test_config_allowlist_does_not_execute_or_copy_secrets(self):
        result = capture_settings(self.source / 'poe2logger/private_config.py')
        self.assertEqual(result['target_stashes'], ['Test'])
        self.assertNotIn('SESSION_ID', result)
        self.assertNotIn('DO_NOT_EXPOSE', json.dumps(result))

    def test_offset_dates_compare_in_utc_and_zero_coordinates_are_valid(self):
        path = self.root / 'offset.csv'
        self.write_history(path, [
            ['2026-01-01T23:30:00Z', '1', 'Alpha', 'A', 'added', 'Test', 'Unknown Item', '0', '0'],
            ['2026-01-02T01:30:00+02:00', '2', 'Alpha', 'A', 'removed', 'Test', 'Unknown Item', '0', '0']])
        result = inspect_history(path, 'Alpha')
        self.assertEqual(result['oldest_at'], result['newest_at'])
        self.assertEqual(result['issues'], {})


class ContractSafetyTests(unittest.TestCase):
    def test_credentials_are_redacted_from_repr(self):
        credential = StoredCredential('r1', None, None, 'ACCESS_SECRET', 'REFRESH_SECRET')
        self.assertNotIn('SECRET', repr(credential))
