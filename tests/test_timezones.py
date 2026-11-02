import unittest
from backend.timezones import normalize_timezone
from backend.quantities import DEFAULTS, validate_settings


class TimezoneTests(unittest.TestCase):
    def test_offsets_and_aliases_are_canonical_and_idempotent(self):
        examples = {'UTC+2':'UTC+02:00', 'utc - 8':'UTC-08:00', 'UTC+05:30':'UTC+05:30',
                    'UTC+5.5':'UTC+05:30', 'UTC+5.75':'UTC+05:45', 'UTC-3.5':'UTC-03:30',
                    'UTC+14':'UTC+14:00', 'UTC-14':'UTC-14:00', 'UTC-0':'UTC',
                    'PST':'UTC-08:00', 'pdt':'UTC-07:00', 'EST':'UTC-05:00', 'EDT':'UTC-04:00',
                    'CST':'UTC-06:00', 'CET':'UTC+01:00', 'CEST':'UTC+02:00', 'GMT':'UTC',
                    'UTC':'UTC', 'Europe/Warsaw':'Europe/Warsaw', 'America/Los_Angeles':'America/Los_Angeles'}
        for original,expected in examples.items():
            with self.subTest(original=original):
                self.assertEqual(normalize_timezone(original),expected)
                self.assertEqual(normalize_timezone(expected),expected)
                self.assertEqual(validate_settings(dict(DEFAULTS,timezone=original))['timezone'],expected)

    def test_invalid_offsets_and_ambiguous_unsupported_short_names_are_rejected(self):
        for value in ('UTC+14:01','UTC+15','UTC-24','UTC+05:60','UTC+5.99','UTC+2:3','UTC++2',
                      'UTC+NaN','UTC+1e3','UTC+','IST','Mars/Here','',None,[],1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,'invalid_timezone'):normalize_timezone(value)
