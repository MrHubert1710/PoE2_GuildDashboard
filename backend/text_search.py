"""Per-request, Unicode-aware text filters with bounded regex matching time."""
from time import monotonic
import regex
from flask import g
from .browsing import ReadError, one_argument


class MatchBudget:
    def __init__(self, seconds=.5):
        self.remaining = seconds


class RegexMatcher:
    def __init__(self, pattern, field, budget, *, match_case=False, whole_word=False, literal=False):
        self.budget, self.cache = budget, {}
        if literal:
            pattern = regex.escape(pattern)
        if whole_word:
            pattern = r'(?<!\w)(?:' + pattern + r')(?!\w)'
        flags = regex.VERSION0 | (0 if match_case else regex.IGNORECASE | regex.FULLCASE)
        try:
            self.pattern = regex.compile(pattern, flags)
        except (regex.error, OverflowError, RecursionError):
            raise ReadError(f'invalid_{field}_regex') from None

    def matches(self, value):
        if value in self.cache:
            return self.cache[value]
        if self.budget.remaining <= 0:
            g.regex_error = 'regex_timeout'
            raise TimeoutError()
        started = monotonic()
        try:
            result = int(self.pattern.search(value, timeout=min(.025, self.budget.remaining)) is not None)
        except TimeoutError:
            g.regex_error = 'regex_timeout'
            raise
        finally:
            self.budget.remaining -= monotonic() - started
        if len(self.cache) >= 4096:
            self.cache.pop(next(iter(self.cache)))
        self.cache[value] = result
        return result


class TextFilters:
    def __init__(self):
        self.values, self.matchers, self.modes, self.match_case = {}, {}, {}, {}
        budget = MatchBudget()
        for field in ('account', 'item'):
            mode = one_argument(field + '_regex', '0')
            if mode not in {'0', '1'}:
                raise ReadError('invalid_regex_mode')
            case = one_argument(field + '_case', '0')
            word = one_argument(field + '_word', '0')
            if case not in {'0', '1'} or word not in {'0', '1'}:
                raise ReadError('invalid_search_mode')
            self.match_case[field] = case == '1'
            self.modes[field] = mode == '1'
            value = one_argument(field)
            self.values[field] = value if self.modes[field] else value.strip()
            if (self.modes[field] or word == '1') and self.values[field]:
                self.matchers[field] = RegexMatcher(self.values[field], field, budget, match_case=self.match_case[field], whole_word=word == '1', literal=not self.modes[field])

    def bind(self, connection):
        for field, matcher in self.matchers.items():
            connection.create_function('filter_regex_' + field, 1, matcher.matches)

    def predicate(self, field, column):
        if field in self.matchers:
            return f'filter_regex_{field}({column})=1', []
        if self.match_case[field]:
            return f'instr({column},?)>0', [self.values[field]]
        return f'instr(casefold({column}),casefold(?))>0', [self.values[field]]
