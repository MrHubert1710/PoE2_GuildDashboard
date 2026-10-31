import csv
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from poe2logger import processing, prices
from poe2logger.config import CSV_FIELDNAMES
from poe2logger.league_paths import league_directory_name, league_paths
from poe2logger.refresh import RefreshManager
from poe2logger.storage import migrate_legacy_data


def row(league, event_id='1', account='Player'):
    return dict(zip(CSV_FIELDNAMES, [
        '2026-01-01T12:00:00Z', event_id, league, account, 'added',
        'Test stash', 'Divine Orb', '0', '0',
    ]))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class LeagueStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.legacy = self.base / 'logs'
        self.report = self.base / 'GuildReport_Latest.html'

    def migrate(self, league):
        paths = league_paths(league, self.base)
        return migrate_legacy_data(league, paths, self.legacy, self.report)

    def merge(self, league):
        paths = league_paths(league, self.base)
        with patch.object(processing, 'LOG_DIR', str(paths.logs)), \
             patch.object(processing, 'LEAGUE_NAME', league):
            processing.merge_log_files()
        with (paths.logs / 'history.csv').open(encoding='utf-8-sig') as stream:
            return list(csv.DictReader(stream))

    def test_safe_distinct_names_and_path_traversal(self):
        self.assertEqual(league_directory_name('Example League'), 'Example League')
        names = ['A/B', 'A:B', 'A%2FB', '..', '.', 'CON', 'CON.txt', 'Example.',
                 'Example ', 'A\\B', 'Liga Żółć', 'x' * 500]
        directories = [league_directory_name(name) for name in names]
        self.assertEqual(len(set(directories)), len(names))
        for name, directory in zip(names, directories):
            self.assertNotIn('/', directory)
            self.assertNotIn('\\', directory)
            self.assertNotIn(directory, ('.', '..'))
            self.assertLessEqual(len(directory), 160)
            self.assertEqual(league_paths(name, self.base).logs.parent, self.base / 'logs')
        with self.assertRaises(ValueError):
            league_directory_name(' ')

    def test_mixed_legacy_history_is_copied_by_league_without_losing_sources(self):
        source = self.legacy / 'history.csv'
        write_csv(source, [row('Alpha'), row('Beta', account='Other player')])
        original = source.read_bytes()
        for league in ('Alpha', 'Beta'):
            self.assertTrue(self.migrate(league))
            rows = self.merge(league)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['League'], league)
            # Same ID in another league must never replace this row.
            self.assertEqual(rows[0]['Account'], 'Player' if league == 'Alpha' else 'Other player')
            self.assertFalse(self.migrate(league))
        self.assertEqual(source.read_bytes(), original)

    def test_updated_legacy_source_is_imported_and_deduplicated(self):
        source = self.legacy / 'history.csv'
        write_csv(source, [row('Alpha')])
        self.migrate('Alpha')
        self.merge('Alpha')
        write_csv(source, [row('Alpha'), row('Alpha', event_id='2'), row('Beta', event_id='3')])
        self.assertTrue(self.migrate('Alpha'))
        self.assertEqual([item['Id'] for item in self.merge('Alpha')], ['1', '2'])

    def test_only_exact_league_report_is_reused(self):
        league = 'Alpha & Friends'
        page = f'<div class="subtitle">League: {html.escape(league)} | Stashes: Test</div>'
        self.report.write_text(page, encoding='utf-8')
        self.migrate('Alpha')
        self.assertFalse(league_paths('Alpha', self.base).latest_dashboard.exists())
        self.migrate(league)
        self.assertEqual(league_paths(league, self.base).latest_dashboard.read_text(), page)
        self.assertEqual(self.report.read_text(), page)

    def test_prices_and_refresh_state_are_independent(self):
        alpha, beta = (league_paths(name, self.base) for name in ('Alpha', 'Beta'))
        alpha.prices.mkdir(parents=True)
        (alpha.prices / 'currency.json').write_text(json.dumps({'league': 'Alpha'}))
        with patch.object(prices, 'PRICE_CACHE_DIR', str(alpha.prices)):
            self.assertEqual(prices.load_cached_prices('Currency'), {'league': 'Alpha'})
        with patch.object(prices, 'PRICE_CACHE_DIR', str(beta.prices)):
            self.assertIsNone(prices.load_cached_prices('Currency', allow_stale=True))
        RefreshManager(alpha.reports).run(lambda: None)
        self.assertIsNotNone(RefreshManager(alpha.reports).status()['last_success'])
        self.assertEqual(RefreshManager(beta.reports).status(), {
            'running': False, 'failed': False, 'last_success': None,
        })

    def test_two_leagues_generate_separate_reports_using_real_pipeline(self):
        write_csv(self.legacy / 'history.csv', [
            row('Alpha', account='AlphaPlayer'), row('Beta', account='BetaPlayer'),
        ])
        # Load configuration afresh per process without modifying private_config
        # or calling external APIs; exercise the actual migration/render pipeline.
        program = '''
import sys, types
from datetime import timezone
private = types.ModuleType('poe2logger.private_config')
private.LEAGUE_NAME = sys.argv[1]
private.GUILD_ID = private.SESSION_ID = 'test'
private.TARGET_STASHES = {'Test stash'}
private.STASH_ALIASES = {}
private.DISPLAY_TIMEZONE = timezone.utc
sys.modules[private.__name__] = private
from poe2logger import cli, prices
prices.fetch_price_payload = lambda category: None
cli.generate_report()
'''
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        for league in ('Alpha', 'Beta'):
            result = subprocess.run([sys.executable, '-c', program, league],
                                    cwd=self.base, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            paths = league_paths(league, self.base)
            self.assertTrue((paths.logs / 'history.csv').is_file())
            self.assertTrue((paths.reports / 'GuildReport_0101.html').is_file())
            page = paths.latest_dashboard.read_text(encoding='utf-8')
            self.assertIn(f'League: {league} |', page)
            self.assertIn(f'{league}Player', page)
            self.assertNotIn('BetaPlayer' if league == 'Alpha' else 'AlphaPlayer', page)
        self.assertFalse(self.report.exists())

    def test_legacy_report_and_cursor_survive_failed_first_fetch(self):
        write_csv(self.legacy / 'history.csv', [row('Alpha'), row('Beta')])
        page = '<div class="subtitle">League: Alpha | Stashes: Test</div>'
        self.report.write_text(page, encoding='utf-8')
        from poe2logger import cli, fetcher
        paths = league_paths('Alpha', self.base)

        def fetch(_args):
            self.assertEqual(fetcher.read_latest_history_row()['League'], 'Alpha')
            raise ValueError('Session expired')

        with patch.object(cli, 'migrate_legacy_data', side_effect=lambda: self.migrate('Alpha')), \
             patch.object(processing, 'LOG_DIR', str(paths.logs)), \
             patch.object(processing, 'LEAGUE_NAME', 'Alpha'), \
             patch.object(fetcher, 'LOG_DIR', str(paths.logs)), \
             patch.object(cli, 'fetch_guild_history', side_effect=fetch):
            with self.assertRaisesRegex(ValueError, 'Session expired'):
                cli._generate_report(fetch_history=True)
        self.assertEqual(paths.latest_dashboard.read_text(), page)
        self.assertFalse(league_paths('Beta', self.base).latest_dashboard.exists())


if __name__ == '__main__':
    unittest.main()
