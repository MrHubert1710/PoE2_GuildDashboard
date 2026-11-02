import unittest
from flask import Flask
from backend.text_search import MatchBudget, RegexMatcher


class TextSearchTests(unittest.TestCase):
    def test_unicode_full_casefold_backreference_and_cache(self):
        budget=MatchBudget()
        matcher=RegexMatcher(r'^straße$', 'item', budget)
        self.assertTrue(matcher.matches('STRASSE'))
        remaining=budget.remaining
        self.assertTrue(matcher.matches('STRASSE'))
        self.assertEqual(remaining,budget.remaining)
        matcher=RegexMatcher(r'^(\w+) \1$', 'item', budget)
        self.assertTrue(matcher.matches('Orb Orb'))
        self.assertFalse(matcher.matches('Orb Rune'))

    def test_expired_budget_and_catastrophic_backtracking_are_bounded(self):
        with Flask(__name__).app_context():
            with self.assertRaises(TimeoutError):RegexMatcher('.*','item',MatchBudget(0)).matches('Orb')
            with self.assertRaises(TimeoutError):RegexMatcher(r'(a+)+$','item',MatchBudget(.01)).matches('a'*10000+'!')

    def test_literal_whole_word_escapes_regex_symbols_and_respects_case(self):
        matcher=RegexMatcher('C++','item',MatchBudget(),whole_word=True,literal=True)
        self.assertTrue(matcher.matches('some C++ text'))
        self.assertFalse(matcher.matches('some XC++ text'))
        matcher=RegexMatcher('Orb','item',MatchBudget(),match_case=True,whole_word=True,literal=True)
        self.assertTrue(matcher.matches('Chaos Orb'))
        self.assertFalse(matcher.matches('Chaos orb'))
        self.assertFalse(matcher.matches('Chaos Orbital'))
