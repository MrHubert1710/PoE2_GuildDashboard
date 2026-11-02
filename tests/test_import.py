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
            report = self.source / 'stash_reports' / league / 'price_cache/currency.json'
            report.parent.mkdir(parents=True)
            report.write_text('{"lines":[]}')

    def test_import_is_repeatable_preserves_source_and_separates_leagues(self):
        result = module.import_archives(self.source, self.destination)
        self.assertEqual([entry['transactions'] for entry in result['leagues']], [1, 1])
        module.import_archives(self.source, self.destination)
        for league in ('Alpha', 'Beta'):
            self.assertEqual((self.destination / 'leagues' / league / 'history.csv').read_bytes(),
                             (self.source / 'logs' / league / 'history.csv').read_bytes())
            self.assertEqual((self.destination / 'leagues' / league / 'reports/price_cache/currency.json').read_text(),
                             '{"lines":[]}')

    def test_import_does_not_overwrite_modified_archives(self):
        module.import_archives(self.source, self.destination)
        history = self.destination / 'leagues/Alpha/history.csv'
        history.write_text('local changes')
        with self.assertRaisesRegex(ValueError, 'Existing archive differs'):
            module.import_archives(self.source, self.destination)
        self.assertEqual(history.read_text(), 'local changes')

    def test_import_ignores_generated_presentation_files(self):
        source=self.source/'stash_reports/Alpha'
        (source/'retired.html').write_text('unused presentation')
        (source/'retired.svg').write_text('unused presentation')
        manifest=module.import_archives(self.source,self.destination)
        files=manifest['leagues'][0]['files']
        self.assertTrue(all(path.endswith(('.csv','.json')) for path in files))
        self.assertEqual(list(self.destination.rglob('*.html')),[])
        self.assertEqual(list(self.destination.rglob('*.svg')),[])
