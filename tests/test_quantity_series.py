import unittest
from tests.test_quantities import QuantityApiTests as Fixture,event
from backend.database import connect
from backend.quantities import DEFAULTS
from backend.quantity_series import sample_extrema

class SeriesTests(unittest.TestCase):
    setUp=Fixture.setUp
    insert=Fixture.insert
    build=Fixture.build
    config=Fixture.config
    save=Fixture.save

    def series(self,**query):
        response=self.client.get('/api/leagues/A/quantity-series',query_string=query)
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def test_balances_carry_previous_history_into_filtered_days_and_viewports(self):
        self.build()
        data=self.series(series_item='Token',**{'from':'2026-01-02','to':'2026-01-02'})
        self.assertEqual(data['totals'],dict(added=0,removed=5,net=-5,inferred=0))
        series=data['series'][0]
        self.assertEqual(series['opening_balance'],20)
        self.assertEqual(series['closing_balance'],15)
        self.assertEqual(series['points'][0]['balance'],20)
        viewport=self.series(series_item='Token',window_start=1767312000000,window_end=1767398400000)
        self.assertEqual(viewport['series'][0]['opening_balance'],20)
        self.assertEqual(viewport['series'][0]['closing_balance'],15)

    def test_players_and_stashes_show_separate_cumulative_series(self):
        self.insert(event(30,'added',4,stash='Special',x=6,account='Trader'),'A');self.build()
        summary=self.series(series_item='Token')
        players=self.series(view='players',series_item='Token')
        stashes=self.series(view='stashes',series_item='Token')
        self.assertEqual({s['name']:s['closing_balance'] for s in players['series']},{'Alice':20,'Buyer':-5,'Trader':4})
        self.assertEqual({s['name']:s['closing_balance'] for s in stashes['series']},{'Main':15,'Special':4})
        self.assertEqual(summary['series'][0]['closing_balance'],19)
        self.assertEqual(sum(s['closing_balance'] for s in stashes['series']),19)

    def test_immediate_add_remove_survives_even_at_the_same_timestamp(self):
        for index,action in ((30,'added'),(31,'removed')):
            self.insert(event(index,action,10,'Flash',x=5,occurred_at='2026-01-02T02:00:00.000000Z'),'A')
        self.build();data=self.series(series_item='Flash')
        self.assertEqual([p['balance'] for p in data['series'][0]['points']],[0,10,0,0])
        self.assertEqual(data['series'][0]['points'][1]['timestamp'],data['series'][0]['points'][2]['timestamp'])
        self.assertEqual(data['totals']['net'],0)
        self.assertFalse(data['sampled'])

    def test_sampling_preserves_extrema_and_zoom_returns_exact_operations(self):
        for index in range(100):
            self.insert(event(index+100,'added' if index%2==0 else 'removed',10,'Flash',x=5,
                              occurred_at=f'2026-01-02T02:{index//60:02}:{index%60:02}.000000Z'),'A')
        self.build()
        coarse=self.series(series_item='Flash',max_points=24)
        self.assertTrue(coarse['sampled']);self.assertLessEqual(len(coarse['series'][0]['points']),24)
        self.assertEqual(max(p['balance'] for p in coarse['series'][0]['points']),10)
        self.assertEqual(min(p['balance'] for p in coarse['series'][0]['points']),0)
        lower=coarse['bounds']['start']+1
        zoom=self.series(series_item='Flash',max_points=24,window_start=lower,window_end=lower+5000)
        self.assertFalse(zoom['sampled']);self.assertEqual(zoom['series'][0]['event_count'],5)
        self.assertEqual(zoom['series'][0]['closing_balance'],10)
        self.assertLess(len(zoom['series'][0]['points']),len(coarse['series'][0]['points']))

    def test_overview_is_stable_across_disjoint_detail_windows(self):
        for index,(moment,action) in enumerate((('01:00:00','added'),('01:00:01','removed'),('20:00:00','added'),('20:00:01','removed'))):
            self.insert(event(100+index,action,10,'Flash',x=5,occurred_at=f'2026-01-02T{moment}.000000Z'),'A')
        self.build()
        full=self.series(series_item='Flash')
        early=self.series(series_item='Flash',window_start=1767315600000,window_end=1767315610000)
        late=self.series(series_item='Flash',window_start=1767384000000,window_end=1767384010000)
        self.assertEqual(early['series'][0]['overview'],full['series'][0]['overview'])
        self.assertEqual(late['series'][0]['overview'],full['series'][0]['overview'])
        self.assertEqual(early['bounds'],late['bounds'])
        self.assertEqual(early['series'][0]['event_count'],2)
        self.assertEqual(late['series'][0]['event_count'],2)
        for data in (early,late):
            self.assertEqual(max(point['balance'] for point in data['series'][0]['points']),10)
            self.assertEqual(data['series'][0]['closing_balance'],0)
            self.assertLessEqual(len(data['series'][0]['overview']),data['max_points'])

    def test_calendar_filters_select_details_without_truncating_either_navigator(self):
        self.insert(event(40,'added',100,stash='Special',x=8,occurred_at='2026-01-05T12:00:00.000000Z'),'A')
        self.build()
        full=self.series(series_item='Token')
        for day in ('2025-12-31','2026-01-01','2026-01-02','2026-01-06'):
            filtered=self.series(series_item='Token',**{'from':day,'to':day})
            self.assertEqual(filtered['navigator'],full['navigator'])
            self.assertEqual(filtered['window']['end']-filtered['window']['start'],86400000)
        early=self.series(series_item='Token',**{'from':'2026-01-01','to':'2026-01-01'})
        self.assertEqual(early['series'][0]['closing_balance'],20)
        self.assertEqual(full['navigator']['series'][0]['closing_balance'],115)
        # An exact selection can leave the initially selected calendar day.
        late=self.series(series_item='Token',window_start=1767614400000,window_end=1767700800000,
                         **{'from':'2026-01-01','to':'2026-01-01'})
        self.assertEqual(late['series'][0]['event_count'],1)
        self.assertEqual(late['totals']['net'],100)
        self.assertEqual(late['series'][0]['closing_balance'],115)
        self.assertEqual(late['navigator'],full['navigator'])

    def test_non_date_filters_still_change_navigator_data_and_respect_league_settings(self):
        self.insert(event(40,'added',100,stash='Special',x=8,account='Trader',occurred_at='2026-01-05T12:00:00.000000Z'),'A')
        self.build()
        full=self.series(view='stashes',series_item='Token')
        main=self.series(view='stashes',series_item='Token',stash='Main')
        self.assertEqual([series['name'] for series in main['navigator']['series']],['Main'])
        self.assertNotEqual(main['navigator'],full['navigator'])
        buyer=self.series(view='players',series_item='Token',account='Buyer')
        self.assertEqual([series['name'] for series in buyer['navigator']['series']],['Buyer'])
        self.assertEqual(buyer['navigator']['series'][0]['closing_balance'],-5)
        self.assertEqual(self.series(series_item='Token',item='No matching item')['navigator']['series'],[])
        self.save(dict(DEFAULTS,target_stashes=['Main']));self.build()
        hidden=self.series(view='stashes',series_item='Token')
        self.assertEqual([series['name'] for series in hidden['navigator']['series']],['Main'])

    def test_combined_balance_matches_summary_and_retains_opening_balance(self):
        self.insert(event(30,'added',4,stash='Special',x=6,account='Trader'),'A');self.build()
        summary=self.series(series_item='Token')
        for view in ('players','stashes'):
            grouped=self.series(series_item='Token',view=view)
            total=grouped['total_series']
            self.assertTrue(total['aggregate'])
            self.assertEqual(total['points'],summary['series'][0]['points'])
            self.assertEqual(total['closing_balance'],sum(series['closing_balance'] for series in grouped['series']))
            self.assertEqual(grouped['navigator']['total_series']['overview'],summary['navigator']['series'][0]['overview'])
            day=self.series(series_item='Token',view=view,**{'from':'2026-01-02','to':'2026-01-02'})
            self.assertEqual(day['total_series']['opening_balance'],24)
            self.assertEqual(day['total_series']['closing_balance'],19)
            self.assertEqual(day['navigator']['total_series'],grouped['navigator']['total_series'])
            buyer=self.series(series_item='Token',view=view,account='Buyer')
            self.assertEqual(buyer['total_series']['closing_balance'],-5)
        self.assertIsNone(summary['total_series'])

    def test_combined_balance_is_sampled_after_summing_operations_not_series_extrema(self):
        for index in range(100):
            alice=index%4<2
            self.insert(event(100+index,'added' if index%2==0 else 'removed',50 if alice else 70,'Pulse',
                              account='Alice' if alice else 'Trader',stash='Main' if alice else 'Special',x=9,
                              occurred_at=f'2026-01-02T02:{index//60:02}:{index%60:02}.000000Z'),'A')
        self.build()
        data=self.series(series_item='Pulse',view='players',max_points=24)
        self.assertTrue(data['sampled'])
        total=data['total_series'];self.assertLessEqual(len(total['points']),24)
        self.assertEqual(max(point['balance'] for point in total['points']),70)
        self.assertEqual(total['closing_balance'],0)
        self.assertEqual(sum(max(point['balance'] for point in series['points']) for series in data['series']),120)
        low=data['bounds']['start']+1
        zoom=self.series(series_item='Pulse',view='players',max_points=24,window_start=low,window_end=low+4000)
        self.assertEqual(zoom['total_series']['event_count'],4)
        self.assertEqual([point['balance'] for point in zoom['total_series']['points']],[0,50,0,70,0,0])

    def test_combined_balance_includes_groups_beyond_display_limit(self):
        for index in range(101):
            self.insert(event(1000+index,'added',1,'Many',account=f'Player {index:03}',x=index,
                              occurred_at='2026-01-02T02:00:00.000000Z'),'A')
        self.build();data=self.series(series_item='Many',view='players')
        self.assertTrue(data['series_truncated']);self.assertEqual(len(data['series']),100)
        self.assertEqual(data['total_series']['closing_balance'],101)
        self.assertEqual(data['navigator']['total_series']['closing_balance'],101)

    def test_all_items_sums_quantities_and_still_respects_text_and_stash_filters(self):
        self.insert(event(30,'added',7,'Other',x=7,stash='Special'),'A');self.build()
        data=self.series(all_items='1')
        self.assertTrue(data['all_items']);self.assertIsNone(data['item'])
        self.assertEqual(data['series'][0]['closing_balance'],27)
        self.assertEqual(self.series(all_items='1',stash='Special')['series'][0]['closing_balance'],7)
        self.assertEqual(self.series(all_items='1',item='Token')['series'][0]['closing_balance'],15)
        grouped=self.series(all_items='1',view='players')
        self.assertEqual(grouped['total_series']['closing_balance'],27)

    def test_cursor_state_is_exact_between_changes_and_has_one_row_per_series(self):
        self.build()
        before=self.series(series_item='Token',view='players',at=0)
        self.assertTrue(all(row['balance']==0 for row in before['balances']))
        # No snapshot at noon on day one: the previously established balance persists.
        middle=self.series(series_item='Token',view='players',at=1767268800123)
        self.assertEqual(middle['timestamp'],1767268800123)
        self.assertEqual(next(row['balance'] for row in middle['balances'] if row['id']=='combined'),20)
        self.assertEqual(len({row['id'] for row in middle['balances']}),len(middle['balances']))
        later=self.series(series_item='Token',view='players',at=1767441600000)
        self.assertEqual(next(row['balance'] for row in later['balances'] if row['id']=='combined'),15)
        filtered=self.series(series_item='Token',view='players',account='Buyer',at=1767441600000)
        self.assertEqual([row['balance'] for row in filtered['balances']],[-5,-5])

    def test_cursor_uses_final_operation_at_a_shared_millisecond_and_all_item_mode(self):
        for index,action in ((30,'added'),(31,'removed')):
            self.insert(event(index,action,10,'Flash',x=5,occurred_at='2026-01-02T02:00:00.000000Z'),'A')
        self.build()
        state=self.series(series_item='Flash',view='players',at=1767319200000)
        self.assertTrue(all(row['balance']==0 for row in state['balances']))
        all_state=self.series(all_items='1',at=1767319200123)
        self.assertEqual(all_state['balances'][0]['balance'],20)
        for query in ('all_items=wrong','at=NaN','at=8640000000000000'):
            self.assertEqual(self.client.get('/api/leagues/A/quantity-series?'+query).status_code,400)

    def test_client_timezone_does_not_change_utc_filters_or_write_settings(self):
        self.build();before=self.config()
        with connect(self.path) as c:jobs=c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        queries={'from':'2026-01-01T00:00:00.000Z','to':'2026-01-02T00:00:00.000Z'}
        expected=None
        for zone in ('UTC','UTC+13','America/Los_Angeles','Europe/Warsaw'):
            source=self.client.get('/api/leagues/A/transactions',query_string=dict(queries,timezone=zone)).json
            report=self.client.get('/api/leagues/A/quantities',query_string=dict(queries,timezone=zone)).json
            chart=self.series(series_item='Token',timezone=zone,**queries)
            result=([row['id'] for row in source['rows']],report['stats'],chart['series'][0]['points'])
            if expected is None:expected=result
            self.assertEqual(result,expected)
            self.assertEqual(chart['window']['start'],1767225600000)
            self.assertEqual(chart['window']['end'],1767312000000)
        self.assertEqual(self.config(),before)
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],jobs)
        for endpoint in ('transactions','quantities','quantity-series'):
            self.assertEqual(self.client.get('/api/leagues/A/'+endpoint+'?timezone=invalid-zone').status_code,400)

    def test_extrema_sampler_keeps_order_and_limit(self):
        points=[dict(timestamp=i,balance=(50 if i==123 else -30 if i==234 else i%10)) for i in range(1000)]
        result,resolution=sample_extrema(points,24)
        self.assertLessEqual(len(result),24);self.assertIsNotNone(resolution)
        self.assertEqual(max(p['balance'] for p in result),50)
        self.assertEqual(min(p['balance'] for p in result),-30)
        self.assertEqual([p['timestamp'] for p in result],sorted(p['timestamp'] for p in result))
        self.assertEqual(result[0],points[0]);self.assertEqual(result[-1],points[-1])

    def test_hidden_aliases_leagues_and_regex_are_isolated(self):
        self.build();self.build('B')
        self.assertEqual(self.client.get('/api/leagues/B/quantity-series?series_item=Token').json['series'][0]['closing_balance'],90)
        self.save(dict(DEFAULTS,stash_aliases={'Main':'Shared'},target_stashes=['Shared']));self.build()
        one=self.series(stash='Main',series_item='Token')
        both=self.client.get('/api/leagues/A/quantity-series',query_string=[('stash','Main'),('stash','Shared'),('series_item','Token')]).json
        self.assertEqual(one['series'],both['series'])
        regex=self.series(account='^buyer$',account_regex='1',series_item='Token')
        self.assertEqual(regex['series'][0]['closing_balance'],-5)
        self.save(dict(DEFAULTS,target_stashes=[]));self.build()
        self.assertEqual(self.series()['series'],[])

    def test_validation_empty_stale_and_read_only(self):
        self.assertEqual(self.series()['projection']['state'],'missing')
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
        self.build();self.assertEqual(self.series(series_item='absent')['series'],[])
        for query in ('max_points=23','max_points=601','view=state','window_start=3','window_start=2&window_end=1','window_start=NaN&window_end=4','max_points=24&max_points=50','from=2026-02-30','from=2026-02-01&to=2026-01-01','item_regex=wrong','item_regex=1&item=%5B'):
            self.assertEqual(self.client.get('/api/leagues/A/quantity-series?'+query).status_code,400,query)
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?revision=old').status_code,409)
        self.assertEqual(self.client.get('/api/leagues/A/quantity-series?projection_id=old').status_code,409)
        self.assertEqual(self.client.get('/api/leagues/missing/quantity-series').status_code,404)

    def test_timezone_filters_agree_between_source_report_and_chart(self):
        self.insert(event(30,'added',3,'Edge',x=5,occurred_at='2026-01-01T23:30:00.000000Z'),'A')
        self.save(dict(DEFAULTS,timezone='UTC+2'));self.build()
        source=self.client.get('/api/leagues/A/transactions?from=2026-01-02&to=2026-01-02&item=Edge').json
        report=self.client.get('/api/leagues/A/quantities?from=2026-01-02&to=2026-01-02&item=Edge').json
        chart=self.series(series_item='Edge',**{'from':'2026-01-02','to':'2026-01-02'})
        self.assertEqual(source['total'],1);self.assertEqual(report['rows'][0]['net'],3)
        self.assertEqual(chart['totals']['net'],3)
        self.assertEqual(chart['bounds']['start'],1767304800000)
        self.assertEqual(chart['bounds']['end']-chart['bounds']['start'],86400000)

    def test_iana_daylight_saving_day_has_23_hours(self):
        self.save(dict(DEFAULTS,timezone='Europe/Warsaw'));self.build()
        data=self.series(series_item='Token',**{'from':'2026-03-29','to':'2026-03-29'})
        self.assertEqual(data['bounds']['end']-data['bounds']['start'],23*3600000)
        self.assertEqual(data['series'][0]['opening_balance'],15)
        self.assertEqual(data['series'][0]['closing_balance'],15)

    def test_microsecond_boundary_is_included_in_the_correct_day(self):
        self.insert(event(30,'added',3,x=5,occurred_at='2026-01-01T23:59:59.999999Z'),'A');self.build()
        data=self.series(series_item='Token',**{'from':'2026-01-01','to':'2026-01-01'})
        self.assertEqual(data['totals']['added'],23)
        self.assertEqual(data['series'][0]['points'][-2]['timestamp'],1767311999999)
        self.assertEqual(data['series'][0]['closing_balance'],23)

del Fixture
