import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('archive_import', Path(__file__).resolve().parents[1] /
                                            'scripts/import-legacy-data.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source, self.destination = base / 'old', base / 'new'
        for league in ('Alpha', 'Beta'):
            history = self.source / 'logs' / league / 'history.csv'
            history.parent.mkdir(parents=True)
            history.write_text(f'League,Id\n{league},1\n')
            report = self.source / 'stash_reports' / league / 'currentday.html'
            report.parent.mkdir(parents=True)
            report.write_text(f'<html>{league}</html>')

    def test_import_is_repeatable_preserves_source_and_separates_leagues(self):
        result = module.import_archives(self.source, self.destination)
        self.assertEqual([entry['transactions'] for entry in result['leagues']], [1, 1])
        module.import_archives(self.source, self.destination)
        for league in ('Alpha', 'Beta'):
            self.assertEqual((self.destination / 'leagues' / league / 'history.csv').read_bytes(),
                             (self.source / 'logs' / league / 'history.csv').read_bytes())
            self.assertEqual((self.destination / 'leagues' / league / 'reports/currentday.html').read_text(),
                             f'<html>{league}</html>')

    def test_import_does_not_overwrite_modified_archives(self):
        module.import_archives(self.source, self.destination)
        history = self.destination / 'leagues/Alpha/history.csv'
        history.write_text('local changes')
        with self.assertRaisesRegex(ValueError, 'Existing archive differs'):
            module.import_archives(self.source, self.destination)
        self.assertEqual(history.read_text(), 'local changes')
