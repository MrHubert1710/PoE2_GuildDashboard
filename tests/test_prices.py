import copy
import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from backend.database import connect,migrate
from backend.jobs import Queue
from backend.ninja import parse_catalog,NinjaClient,DOCS,PriceError
from backend.prices import normalize,snapshot,save_snapshot,PriceIndex,price_revision,ATOMIC,import_legacy
from backend.valuation import ValuationAdapter,current_valuation
from backend.worker import Worker,AdapterFailure
from tests import test_quantities as quantity_fixture
from tests.test_quantities import event


def exchange(price=2,name='Token'):
    return {'core':{'primary':'divine','rates':{'exalted':100},'items':[{'id':'divine','name':'Divine Orb'}]},
            'items':[{'id':'token','name':name,'category':'Currency'}],'lines':[{'id':'token','primaryValue':price}]}


class AdapterTests(TestCase):
    def test_catalog_is_dynamic_scoped_to_poe2_and_requires_both_valid_feeds(self):
        doc='<code>/poe2/api/economy/exchange/current/overview</code><h3>Accepted type values</h3><h4>PoE 1</h4><table><tr><td>WrongGame</td><td>Ignore</td></tr></table><h4>PoE 2</h4><table><tr><th>Value</th><th>Category</th></tr><tr><td>NewCategory42</td><td>New items</td></tr></table><h3>Response</h3><code>/poe2/api/economy/stash/current/item/overview</code><h3>Accepted type values</h3><h4>PoE 2</h4><table><tr><td>UniqueNewItems</td><td>Uniques</td></tr></table>'
        self.assertEqual(parse_catalog(doc),[dict(feed='exchange',category='NewCategory42',label='New items'),dict(feed='stash',category='UniqueNewItems',label='Uniques')])
        for invalid in ['<html>layout changed</html>',doc.replace('PoE 2','PoE 1')]:
            with self.assertRaises(PriceError):parse_catalog(invalid)

    def test_exchange_names_currency_conversion_and_no_sparkline_backdating(self):
        data=exchange('0.000000001')
        quotes=normalize(data,'exchange')
        self.assertEqual(int(quotes[0]['price_atomic']),1000)
        self.assertEqual(next(q for q in quotes if q['name']=='Divine Orb')['price_atomic'],str(ATOMIC))
        data['core']['primary']='exalted';data['core']['rates']={'divine':'.01'}
        data['lines'][0]['primaryValue']=2
        self.assertEqual(int(normalize(data,'exchange')[0]['price_atomic']),ATOMIC//50)
        for bad in [float('nan'),-1,float('inf'),None]:
            data['lines'][0]['primaryValue']=bad
            with self.assertRaises(PriceError):normalize(data,'exchange')

    def test_stash_format_retains_variants_and_rejects_unknown_currency(self):
        payload={'core':{'primary':'divine'},'lines':[{'id':1,'itemId':'unique-A','name':'Unique A','variant':'Strong','primaryValue':4}]}
        quotes=normalize(payload,'stash');self.assertEqual(quotes[0]['name'],'Unique A');self.assertIsNotNone(quotes[0]['variant'])
        payload['core']={}
        with self.assertRaises(PriceError):normalize(payload,'stash')

    def test_cache_etag_304_and_error_cooldown_are_shared_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'prices.sqlite';migrate(path);now=[1000];calls=[]
            class Response:
                status=200;headers={'ETag':'public-etag','Cache-Control':'max-age=600'}
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,*args):return b'cached response'
            def opener(request,**kwargs):calls.append(request);return Response()
            client=NinjaClient(path,opener=opener,clock=lambda:now[0])
            self.assertEqual(client.fetch(DOCS,60),'cached response')
            self.assertEqual(NinjaClient(path,opener=opener,clock=lambda:now[0]).fetch(DOCS,60),'cached response');self.assertEqual(len(calls),1)
            now[0]+=601
            def unchanged(request,**kwargs):
                calls.append(request);self.assertEqual(request.get_header('If-none-match'),'public-etag');raise HTTPError(DOCS,304,'Not modified',{},None)
            client.opener=unchanged;self.assertEqual(client.fetch(DOCS,60),'cached response')
            now[0]+=601
            client.opener=lambda *a,**kw:(_ for _ in ()).throw(HTTPError(DOCS,429,'Limited',{'Retry-After':'1200'},None))
            with self.assertRaises(PriceError):client.fetch(DOCS,60)
            client.opener=opener
            with self.assertRaises(PriceError):client.fetch(DOCS,60)
            with connect(path,readonly=True) as c:self.assertEqual(c.execute('SELECT body FROM price_http_cache').fetchone()[0],'cached response')


class ValuationTests(TestCase):
    setUp=quantity_fixture.QuantityApiTests.setUp
    insert=quantity_fixture.QuantityApiTests.insert
    build=quantity_fixture.QuantityApiTests.build
    def put(self,price,at=None,league='A',name='Token',category='Currency',provenance=None):
        data=snapshot(league,'exchange',category,exchange(price,name),effective_at=at,provenance=provenance or ('observed' if at else 'legacy_undated'))
        with connect(self.path) as c:save_snapshot(c,data)
        return data['id']
    def value(self):
        self.queue.enqueue('A','valuations','manual')
        worker=Worker(self.queue)
        for _ in range(10):
            if not worker.run_once():break
        with connect(self.path,readonly=True) as c:
            league=c.execute("SELECT * FROM leagues WHERE id='A'").fetchone()
            run,_=current_valuation(c,league,'historical');self.assertIsNotNone(run)
    def series(self,**params):
        response=self.client.get('/api/leagues/A/quantity-series',query_string={'mode':'value','view':'players',**params})
        self.assertEqual(response.status_code,200,response.json);return response.json

    def test_historical_never_uses_future_or_undated_prices_and_latest_is_explicit(self):
        self.build();self.put(99);self.put(3,'2026-01-03T00:00:00Z');self.value()
        historical=self.series()
        self.assertEqual(historical['series'],[])
        self.assertEqual(historical['pricing']['coverage'],'none')
        latest=self.series(pricing='latest')
        self.assertEqual(latest['total_series']['closing_balance'],45)
        self.assertEqual(latest['pricing']['estimated_operations'],0)

    def test_per_operation_historical_rates_do_not_revalue_previous_contributions(self):
        early=self.put(2,'2026-01-01T00:00:00Z');later=self.put(3,'2026-01-02T00:00:00Z');self.build();self.value()
        historical=self.series();latest=self.series(pricing='latest')
        self.assertEqual(historical['total_series']['closing_balance'],25) # +20*2 -5*3
        self.assertEqual(latest['total_series']['closing_balance'],45) # (20-5)*3
        self.assertEqual(set(historical['pricing']['snapshot_ids']),{early,later})
        cursor=self.series(at=1798761600000)
        self.assertEqual(cursor['balances'][-1]['balance'],25)
        report=self.client.get('/api/leagues/A/valuations?mode=historical&view=players').json
        self.assertEqual(sum(row['net'] for row in report['rows']),25)
        with connect(self.path,readonly=True) as c:
            self.assertTrue(all(row[0] for row in c.execute('SELECT snapshot_id FROM valuation_lines WHERE value_atomic IS NOT NULL')))

    def test_undated_estimates_are_flagged_and_imports_are_repeatable(self):
        identity=self.put(2);self.assertEqual(identity,self.put(2));self.build();self.value()
        latest=self.series(pricing='latest')
        self.assertEqual(latest['total_series']['closing_balance'],30)
        self.assertGreater(latest['pricing']['estimated_operations'],0)
        self.assertEqual(self.series()['pricing']['coverage'],'none')

    def test_old_category_name_cannot_make_dated_prices_ambiguous(self):
        self.put(99,category='currency')
        self.put(2,'2026-01-01T00:00:00Z',category='Currency')
        self.build();self.value()
        latest=self.series(pricing='latest',item='Token')
        self.assertEqual(latest['pricing']['coverage'],'complete')
        self.assertEqual(latest['pricing']['estimated_operations'],0)
        self.assertEqual(latest['total_series']['closing_balance'],30)

    def test_missing_is_not_zero_and_leagues_never_share_prices(self):
        self.put(0,league='B');self.build();self.value()
        self.assertEqual(self.series(pricing='latest')['pricing']['coverage'],'none')
        self.put(0,'2026-01-01T00:00:00Z');self.value()
        zero=self.series(item='Token')
        self.assertEqual(zero['pricing']['coverage'],'complete')
        self.assertEqual(zero['total_series']['closing_balance'],0)

    def test_ambiguous_variants_are_unpriced_and_aliases_are_league_scoped(self):
        self.put(2,'2026-01-01T00:00:00Z',name='Canonical token')
        with connect(self.path) as c:c.execute('INSERT INTO price_aliases VALUES(?,?,?)',('A','token','canonical token'))
        self.build();self.value();self.assertEqual(self.series()['total_series']['closing_balance'],30)
        self.put(9,'2026-01-01T00:00:00Z',name='Canonical token',category='Other')
        self.value();self.assertEqual(self.series()['pricing']['coverage'],'none')
        report=self.client.get('/api/leagues/A/valuations').json
        self.assertEqual(next(row for row in report['unpriced'] if row['item_name']=='Token')['reason'],'price_ambiguous')

    def test_revision_pinning_and_stale_publication_keep_last_good_results(self):
        self.put(2,'2026-01-01T00:00:00Z');self.build();self.value()
        version=self.series()['pricing']['revision']
        self.put(3,'2026-01-02T00:00:00Z')
        response=self.client.get('/api/leagues/A/quantity-series',query_string={'mode':'value','price_revision':version})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.series()['pricing']['state'],'missing')
        self.value();self.assertEqual(self.series()['total_series']['closing_balance'],25)

    def test_staged_valuation_cannot_publish_after_price_revision_changes(self):
        import threading
        self.put(2,'2026-01-01T00:00:00Z');self.build()
        job=self.queue.claim('valuation-race')
        self.assertEqual(job['kind'],'valuations')
        publish=ValuationAdapter().stage(self.queue,job,threading.Event())
        self.put(3,'2026-01-02T00:00:00Z')
        with self.assertRaises(AdapterFailure):self.queue.complete(job,publish)
        with connect(self.path,readonly=True) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM valuation_runs').fetchone()[0],0)

    def test_category_discovery_keeps_old_snapshots_and_failure_keeps_last_catalog(self):
        import threading
        from backend.prices import PricesAdapter
        self.put(2,'2026-01-01T00:00:00Z')
        with connect(self.path) as c:
            c.execute("INSERT INTO price_catalogs VALUES('old','2026-01-01','[]')")
            c.execute("INSERT INTO price_categories VALUES('exchange','OldCategory','Old',1,'old')")
        class Client:
            def __init__(self,*args):pass
            def catalog(self):return [dict(feed='exchange',category='NewCategory',label='New')]
            def league_id(self,name):return name
            def prices(self,*args):return exchange(5)
        with patch('backend.prices.NinjaClient',Client):
            publish=PricesAdapter().stage(self.queue,{'league_id':'A'},threading.Event())
            with connect(self.path) as c:publish(c)
        with connect(self.path,readonly=True) as c:
            self.assertEqual(c.execute("SELECT active FROM price_categories WHERE category='OldCategory'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT active FROM price_categories WHERE category='NewCategory'").fetchone()[0],1)
            count=c.execute('SELECT COUNT(*) FROM price_snapshots').fetchone()[0]
        with patch('backend.prices.NinjaClient') as client:
            client.return_value.catalog.side_effect=PriceError('category_catalog_invalid')
            with self.assertRaises(AdapterFailure):PricesAdapter().stage(self.queue,{'league_id':'A'},threading.Event())
        with connect(self.path,readonly=True) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM price_snapshots').fetchone()[0],count)
            self.assertEqual(c.execute("SELECT active FROM price_categories WHERE category='NewCategory'").fetchone()[0],1)

    def test_corrections_are_valued_and_sampling_filters_and_cursor_remain_consistent(self):
        self.insert(event(40,'added',10,'Tracked',x=8,account='Donor'),'A')
        self.insert(event(41,'removed',4,'Reported',x=8,account='Collector'),'A')
        self.put(2,'2026-01-01T00:00:00Z',name='Tracked',category='Tracked')
        self.put(3,'2026-01-01T00:00:00Z',name='Reported',category='Reported')
        self.build();self.value()
        data=self.series(view='players',item='Reported')
        self.assertEqual({row['name']:row['closing_balance'] for row in data['series']},{'Collector':-12,'__poa_reconstruction__':12})
        self.assertEqual(data['total_series']['closing_balance'],0)
        stash=self.series(view='stashes',item='Reported')
        self.assertTrue(all(p['balance']==0 for p in stash['series'][0]['points']))


    def test_daily_history_values_old_operations_without_future_or_cross_item_leakage(self):
        fixture=DailyHistoryTests()
        daily=fixture.make(fixture.exchange_history([('2026-01-01T00:00:00Z',2),('2026-01-02T00:00:00Z',3)]))
        other=fixture.make(dict(payload={'item':{'id':'other'},'pairs':[{'id':'divine','history':[{'timestamp':'2026-01-03T00:00:00Z','rate':100}]}]},headers={}),item=dict(id='other',name='Other'))
        with connect(self.path) as c:
            save_snapshot(c,daily);save_snapshot(c,other)
            index=PriceIndex(c,'A')
            self.assertEqual(index.resolve('Token','2025-12-31T00:00:00.000000Z','historical'),(None,'historical_price_missing'))
            self.assertEqual(index.resolve('Token','2026-01-04T00:00:00.000000Z','historical')[0][1]['price_atomic'],str(3*ATOMIC))
        self.build();self.value()
        self.assertEqual(self.series(view='stashes',item='Token')['total_series']['closing_balance'],45)
        self.assertEqual(self.series(view='stashes',item='Token')['pricing']['estimated_operations'],0)
        self.put(4,'2026-11-01T00:00:00Z');self.value()
        self.assertEqual(self.series(view='stashes',item='Token',pricing='latest')['total_series']['closing_balance'],60)
        self.assertEqual(self.series(view='stashes',item='Token')['total_series']['closing_balance'],60)


    def test_inventory_revalues_without_operation_and_player_cash_flow_does_not(self):
        self.put(2,'2026-01-01T00:00:00Z');self.put(3,'2026-01-02T00:00:00Z');self.put(4,'2026-01-03T00:00:00Z')
        self.build();self.value()
        player=self.series(view='players',item='Token')
        stash=self.series(view='stashes',item='Token')
        self.assertEqual(player['total_series']['closing_balance'],25)
        self.assertEqual(stash['total_series']['closing_balance'],60)
        self.assertEqual(self.series(view='summary',item='Token')['series'][0]['closing_balance'],60)
        at=1767398400000 # Jan 3, midnight: only a price change, no operation.
        self.assertTrue(any(p['timestamp']==at and p['balance']==60 for p in stash['series'][0]['points']))
        cursor=self.series(view='stashes',item='Token',at=at+43200000)
        self.assertEqual(cursor['balances'][0]['balance'],60)
        report=self.client.get('/api/leagues/A/valuations?view=stashes&item=Token').json
        self.assertEqual(report['model'],'inventory');self.assertEqual(report['rows'][0]['quantity'],15)
        self.assertEqual(report['rows'][0]['net'],60)

    def test_withdrawal_leaves_empty_stash_and_negative_player_balance(self):
        self.put(2,'2026-01-01T00:00:00Z');self.put(4,'2026-01-03T00:00:00Z')
        self.insert(event(40,'removed',15,account='Collector',occurred_at='2026-01-04T12:00:00.000000Z'),'A')
        self.build();self.value()
        players=self.series(view='players',item='Token')
        self.assertEqual(next(s['closing_balance'] for s in players['series'] if s['name']=='Collector'),-60)
        stash=self.series(view='stashes',item='Token')
        self.assertEqual(stash['total_series']['closing_balance'],0)
        self.assertTrue(all(p['balance']>=0 for s in stash['series'] for p in s['points']))

    def test_inventory_ignores_player_and_date_start_does_not_reset_stock(self):
        self.put(2,'2026-01-01T00:00:00Z');self.put(4,'2026-01-03T00:00:00Z');self.build();self.value()
        query={'view':'stashes','item':'Token','account':'Nobody','from':'2026-01-03T00:00:00Z','to':'2026-01-04T00:00:00Z'}
        chart=self.series(**query)
        self.assertEqual(chart['total_series']['closing_balance'],60)
        report=self.client.get('/api/leagues/A/valuations',query_string=query).json
        self.assertTrue(report['account_filter_ignored'])
        self.assertEqual(report['rows'][0]['quantity'],15)
        self.assertEqual(report['rows'][0]['opening_value'],30)
        self.assertEqual(report['rows'][0]['net'],60)
        self.assertEqual(report['rows'][0]['change'],30)
        self.assertEqual(self.series(view='players',item='Token',account='Nobody')['series'],[])

    def test_inventory_missing_price_does_not_discard_units_or_leave_a_negative_value(self):
        self.put(2,'2026-01-03T00:00:00Z');self.build();self.value()
        report=self.client.get('/api/leagues/A/valuations?view=stashes&item=Token&to=2026-01-02T12:00:00Z').json
        self.assertEqual(report['coverage'],'none');self.assertEqual(report['unpriced'][0]['units'],15)
        self.assertEqual(report['rows'][0]['quantity'],15)
        early=self.series(view='stashes',item='Token',at=1767312000000)
        self.assertEqual(early['pricing']['coverage'],'none')
        self.assertEqual(self.series(view='stashes',item='Token')['total_series']['closing_balance'],30)


class DailyHistoryTests(TestCase):
    def exchange_history(self,rates):
        return dict(payload={'item':{'id':'token'},'pairs':[{'id':'divine','history':[{'timestamp':at,'rate':price} for at,price in rates]}]},
                    url='https://poe.ninja/poe2/api/economy/exchange/current/details?league=A&type=Currency&id=token',headers={'Date':'Mon, 02 Nov 2026 23:00:00 GMT'},retrieved_at='2026-11-02T23:00:00Z')

    def make(self,response,feed='exchange',item=None,**kwargs):
        from backend.price_history import history_snapshot
        return history_snapshot('A',dict(feed=feed,category='Currency' if feed=='exchange' else 'PrecursorTablets'),item or dict(id='token',name='Token'),response,**kwargs)

    def test_exchange_dates_absolute_rates_zero_and_stable_identity(self):
        response=self.exchange_history([('2026-07-26T00:00:00Z','6.11'),('2026-07-27T00:00:00Z','5.96'),('2026-07-28T00:00:00Z',0)])
        result=self.make(response)
        self.assertEqual([q['price_atomic'] for q in result['quotes']],[str(611*ATOMIC//100),str(596*ATOMIC//100),'0'])
        self.assertEqual(len({q['quote_key'] for q in result['quotes']}),3)
        response['retrieved_at']='2026-11-03T12:00:00Z'
        self.assertEqual(result['id'],self.make(response)['id'])
        response['payload']['pairs'][0]['history'][0]['timestamp']='2026-07-26'
        with self.assertRaises(PriceError):self.make(response)

    def test_divine_is_exactly_one_without_inverting_other_pairs(self):
        response=self.exchange_history([('2026-01-01T00:00:00Z',800)])
        response['payload']['item']['id']='divine';response['payload']['pairs'][0]['id']='exalted'
        result=self.make(response,item=dict(id='divine',name='Divine Orb'))
        self.assertEqual(result['quotes'][0]['price_atomic'],str(ATOMIC))

    def test_stash_uses_league_end_header_or_cached_response_date_not_local_clock(self):
        response=dict(payload=[dict(daysAgo=2,value=3),dict(daysAgo=0,value=4)],headers={'Date':'Mon, 02 Nov 2026 23:00:00 GMT','X-League-EndAt':'2026-07-20T20:00:00Z'})
        item=dict(id=123,name='Tablet',variant='Rare')
        result=self.make(response,'stash',item)
        self.assertEqual([q['effective_at'][:10] for q in result['quotes']],['2026-07-18','2026-07-20'])
        self.assertIsNotNone(result['quotes'][0]['variant'])
        del response['headers']['X-League-EndAt']
        self.assertEqual(self.make(response,'stash',item)['quotes'][0]['effective_at'][:10],'2026-10-31')
        response['headers']={}
        with self.assertRaises(PriceError):self.make(response,'stash',item)

    def test_stash_conversion_requires_rate_on_same_historical_day(self):
        response=dict(payload=[dict(daysAgo=1,value=100),dict(daysAgo=0,value=100)],headers={'Date':'Fri, 02 Jan 2026 23:00:00 GMT'})
        from decimal import Decimal
        result=self.make(response,'stash',dict(id=1,name='Tablet'),primary='exalted',references={'exalted':{'2026-01-01T00:00:00.000000Z':Decimal('.02')}})
        self.assertEqual(len(result['quotes']),1)
        self.assertEqual(result['quotes'][0]['price_atomic'],str(2*ATOMIC))
        with self.assertRaises(PriceError):self.make(response,'stash',dict(id=1,name='Tablet'),primary='exalted')

    def test_history_requests_use_slug_and_304_preserves_relative_date_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'prices.sqlite';migrate(path);now=[1000]
            class Response:
                status=200;headers={'ETag':'history-v1','Date':'Mon, 02 Nov 2026 23:00:00 GMT'}
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,*args):return b'[]'
            calls=[]
            def opener(request,**kwargs):calls.append(request.full_url);return Response()
            client=NinjaClient(path,opener=opener,clock=lambda:now[0])
            item=dict(id='alch',detailsId='orb-of-alchemy')
            category=dict(feed='exchange',category='Currency')
            first=client.history('A',category,item)
            self.assertIn('id=orb-of-alchemy',calls[0])
            now[0]+=86400
            def unchanged(*args,**kwargs):raise HTTPError(DOCS,304,'unchanged',{'Date':'Tue, 03 Nov 2026 23:00:00 GMT'},None)
            client.opener=unchanged
            second=client.history('A',category,item)
            self.assertEqual(first['headers'],second['headers'])
