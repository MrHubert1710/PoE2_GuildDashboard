import unittest
from tests.test_quantities import QuantityApiTests as Fixture, event
from backend.database import connect
from backend.quantities import DEFAULTS


class SeriesTests(unittest.TestCase):
    setUp = Fixture.setUp
    insert = Fixture.insert
    build = Fixture.build
    config = Fixture.config
    save = Fixture.save

    def test_series_sums_match_report_and_filters_replay_prior_history(self):
        self.build()
        response=self.client.get('/api/leagues/A/quantity-series?series_item=Token&account=Buyer&from=2026-01-02&to=2026-01-02')
        self.assertEqual(response.status_code,200)
        data=response.json
        self.assertEqual(data['totals'],dict(added=0,removed=5,net=-5,inferred=0))
        self.assertLessEqual(len(data['points']),240)
        self.assertEqual(sum(row['removed'] for row in data['points']),5)
        self.assertEqual(data['unit'],'item_count')
        self.assertEqual(data['bounds']['end']-data['bounds']['start'],86400000)

    def test_series_are_bounded_and_zero_filled_without_mixing_items(self):
        self.build()
        data=self.client.get('/api/leagues/A/quantity-series?series_item=Token&max_points=24&from=2025-01-01&to=2026-02-01').json
        self.assertLessEqual(len(data['points']),24)
        self.assertEqual(data['totals']['added'],20)
        self.assertEqual(data['totals']['removed'],5)
        self.assertTrue(any(row['added']==row['removed']==0 for row in data['points']))
        self.assertEqual(data['totals']['net'],15)
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?series_item=Other').json['totals']['added'],5)

    def test_stale_empty_invalid_and_read_only_requests(self):
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series').json['projection']['state'],'missing')
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
        self.build()
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?series_item=absent').json['points'],[])
        for query in ('max_points=23','max_points=601','max_points=24&max_points=50','view=state','from=2026-02-30','from=2026-02-01&to=2026-01-01','item_regex=wrong','item_regex=1&item=%5B'):
            self.assertEqual(self.client.get('/api/leagues/A/quantity-series?'+query).status_code,400,query)
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?revision=old').status_code,409)
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?projection_id=old').status_code,409)
        self.assertEqual(self.client.get('/api/leagues/missing/quantity-series').status_code,404)

    def test_hidden_aliases_and_leagues_have_independent_series(self):
        self.build('A');self.build('B')
        self.assertEqual(self.client.get('/api/leagues/B/quantity-series?series_item=Token').json['totals']['added'],100)
        self.save(dict(DEFAULTS,stash_aliases={'Main':'Shared'},target_stashes=['Shared']))
        self.build()
        one=self.client.get('/api/leagues/A/quantity-series?stash=Main&series_item=Token').json
        both=self.client.get('/api/leagues/A/quantity-series?stash=Main&stash=Shared&series_item=Token').json
        self.assertEqual(one['points'],both['points'])
        self.save(dict(DEFAULTS,target_stashes=[]));self.build()
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series').json['points'],[])

    def test_regex_case_modes_and_unresolved_events_are_explicit(self):
        for index,external in ((40,'opaque-a'),(41,'opaque-b')):
            self.insert(event(index,'modified',8,x=8,external_id=external,occurred_at='2026-01-02T05:00:00.000000Z'),'A')
        self.build()
        data=self.client.get('/api/leagues/A/quantity-series?series_item=Token').json
        self.assertEqual(data['unresolved_events'],2)
        self.assertEqual(data['totals']['net'],15)
        data=self.client.get('/api/leagues/A/quantity-series?series_item=Token&account=%5Ebuyer%24&account_regex=1').json
        self.assertEqual(data['totals']['removed'],5)
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?account=BUYER&account_case=1').json['points'],[])
        data=self.client.get('/api/leagues/A/quantity-series?item=%5Etoken%24&item_regex=1&series_item=Token').json
        self.assertEqual(data['totals']['net'],15)

    def test_catalog_is_limited_and_timezone_never_changes_utc_buckets(self):
        for index in range(50):
            self.insert(event(index+100,'added',1,item='Different '+str(index),x=index+20,occurred_at='2026-01-03T00:00:00.000000Z'),'A')
        self.save(dict(DEFAULTS,timezone='PST'));self.build()
        data=self.client.get('/api/leagues/A/quantity-series').json
        self.assertEqual(len(data['items']),50)
        self.assertEqual(data['timezone'],'UTC-08:00')
        self.assertEqual(data['bounds']['start'],1767225600000)
        self.assertEqual(data['points'][0]['timestamp'],data['bounds']['start'])
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?from=0001-01-01&to=9999-12-30').status_code,200)

    def test_last_microsecond_of_day_is_not_rounded_into_the_next_bucket(self):
        self.insert(event(30,'added',3,x=5,occurred_at='2026-01-01T23:59:59.999999Z'),'A')
        self.build()
        data=self.client.get('/api/leagues/A/quantity-series?series_item=Token&from=2026-01-01&to=2026-01-01').json
        self.assertEqual(data['totals']['added'],23)
        self.assertEqual(data['points'][-1]['added'],3)
        self.assertEqual(data['points'][-1]['end'],1767312000000)

# Fixture is imported only to share setup helpers, not its test suite.
del Fixture
