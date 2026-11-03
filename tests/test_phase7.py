import json,sqlite3,tempfile,threading,time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from backend.database import connect,migrate,utc_now
from backend.jobs import Queue,LeaseLost
from backend.worker import Worker,AdapterFailure
from backend.ggg_connection import GGGConnectionStore
from backend.ggg_history import GuildHistoryClient,RESOURCE,rate_delay
from backend.league_catalog import parse_catalog,publish_catalog,LeagueCatalogAdapter,GGGLeaguesClient
from tests.auth_helpers import create_app
from tests import test_quantities as quantities_fixture

TOKEN='canary-session-not-a-real-cookie-12345'


def raw(index=50,league='A',**kwargs):
    result=dict(Date='2026-01-03T12:00:00Z',Id=str(index),League=league,Account='Donor',Action='added',Stash='Main',Item='2× Token',X='1',Y='0');result.update(kwargs);return result


class HistoryTests(TestCase):
    insert=quantities_fixture.QuantityApiTests.insert
    def setUp(self):
        quantities_fixture.QuantityApiTests.setUp(self)
        self.store=GGGConnectionStore(self.path.parent/'provider.sqlite')
        self.store.save('123',TOKEN,1,True)
        with connect(self.path) as c:c.execute("UPDATE sources SET owner_reference='123' WHERE id=1")
        self.queue=Queue(self.path,cooldown=0,connection_file=self.store.path)
        self.client=create_app({'TESTING':True,'DATABASE_FILE':self.path,'GGG_CONNECTION_FILE':self.store.path}).test_client()
    def fetch(self,pages):
        iterator=iter(pages)
        class Client:
            def __init__(self,*args):pass
            def fetch(self,*args):
                result=next(iterator)
                if isinstance(result,Exception):raise result
                return json.dumps(result),result
        job=self.queue.enqueue('A','history','manual')['job_id']
        with patch('backend.ggg_history.GuildHistoryClient',Client):
            worker=Worker(self.queue)
            for _ in range(10):
                if not worker.run_once():break
                with connect(self.path) as c:state=c.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0]
                if state in ('completed','failed'):break
    def test_global_import_deduplicates_archives_and_keeps_unknown_leagues_pending(self):
        old=dict(Date='2026-01-01T00:01:00Z',Id='1',League='A',Account='Alice',Action='modified',Stash='Main',Item='20× Token',X='0',Y='0')
        self.fetch([{'entries':[raw(50,'B'),raw(51,'Not added'),old],'truncated':False}])
        with connect(self.path) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM transactions WHERE league_id='B' AND external_id='50'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM leagues WHERE name='Not added'").fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM guild_history_pages').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM guild_history_events WHERE transaction_id IS NULL').fetchone()[0],1)
            self.assertIsNotNone(c.execute('SELECT cursor FROM source_cursors WHERE source_id=1 AND resource=?',(RESOURCE,)).fetchone())
        self.assertTrue(self.queue.status('A')['history']['available']) # Local archive does not mean ended.
        self.assertEqual(self.queue.scope('A','history'),self.queue.scope('B','history'))
    def test_successful_pagination_preserves_raw_pages_and_detects_later_event_conflicts(self):
        first={'entries':[dict(raw(80),extra_metadata={'proof':123})],'truncated':True}
        second={'entries':[raw(81,'B',Date='2026-01-02T13:00:00Z')],'truncated':False}
        self.fetch([first,second])
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM guild_history_pages').fetchone()[0],2)
            self.assertEqual(json.loads(c.execute('SELECT raw_json FROM guild_history_events WHERE external_id=?',('80',)).fetchone()[0])['extra_metadata'],{'proof':123})
            cursor=c.execute('SELECT cursor FROM source_cursors').fetchone()[0]
        self.fetch([{'entries':[raw(80,Item='999× Token')],'truncated':False}])
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT cursor FROM source_cursors').fetchone()[0],cursor)
            self.assertEqual(c.execute("SELECT item FROM transactions WHERE league_id='A' AND external_id='80'").fetchone()[0],'2× Token')
        self.assertEqual(self.store.public()['error_code'],'history_conflict')

    def test_pagination_failure_never_advances_cursor_or_imports_partial_data(self):
        self.fetch([{'entries':[raw()],'truncated':True},AdapterFailure('history_source_failed',retryable=False)])
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM guild_history_pages').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM source_cursors').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM transactions WHERE external_id='50'").fetchone()[0],0)
    def test_repeated_cursor_invalid_shape_and_unknown_league_field_are_rejected(self):
        for payload in [{'foo':[]},{'entries':[dict(id='missing-everything')],'truncated':False}]:
            self.fetch([payload])
            with connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM source_cursors').fetchone()[0],0)
    def test_session_is_write_only_and_bound_to_one_guild(self):
        response=self.client.get('/api/ggg-connection');self.assertEqual(response.status_code,200)
        self.assertNotIn(TOKEN,response.text)
        state=response.json['connection']
        payload=dict(guild_id='123',session_id='',enabled=True,clear_session=False,revision=state['revision'],source_id=1)
        saved=self.client.put('/api/ggg-connection',json=payload);self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(self.store.get()['session_id'],TOKEN);self.assertNotIn(TOKEN,saved.text)
        self.assertEqual(self.client.put('/api/ggg-connection',json=payload).status_code,409)
        payload.update(guild_id='999',revision=saved.json['connection']['revision'])
        self.assertEqual(self.client.put('/api/ggg-connection',json=payload).status_code,409)
    def test_configuration_change_fences_an_inflight_import(self):
        from backend.ggg_history import GuildHistoryAdapter
        self.queue.enqueue('A','history','manual');job=self.queue.claim('test')
        class Client:
            def __init__(self,*args):pass
            def fetch(self,*args):return '{}',{'entries':[raw()],'truncated':False}
        with patch('backend.ggg_history.GuildHistoryClient',Client):publish=GuildHistoryAdapter().stage(self.queue,job,threading.Event())
        self.store.save('123','different-test-session-123456',1,True)
        with self.assertRaises(AdapterFailure):self.queue.complete(job,publish)
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM source_cursors').fetchone()[0],0)
    def test_request_uses_cookie_only_on_fixed_endpoint_and_auth_failure_stops_autofetch(self):
        captured=[]
        def opener(request,**kwargs):
            captured.append(request)
            raise HTTPError(request.full_url,401,'Denied',{},None)
        client=GuildHistoryClient(self.store,opener=opener)
        with self.assertRaises(AdapterFailure):client.fetch(self.store.get(),123,0,'',threading.Event())
        self.assertEqual(captured[0].get_header('Cookie'),'POESESSID='+TOKEN)
        self.assertTrue(captured[0].full_url.startswith('https://www.pathofexile.com/api/guild/123/stash/history?'))
        self.assertEqual(self.queue.status('A')['history']['reason'],'history_auth_failed')
        self.assertNotIn(TOKEN,json.dumps(self.store.public()))
    def test_rate_limit_headers_and_retry_after_are_respected(self):
        self.assertGreaterEqual(rate_delay({'Retry-After':'120'}),120)
        self.assertGreaterEqual(rate_delay({'X-Rate-Limit-Rules':'Account','X-Rate-Limit-Account':'5:60:120','X-Rate-Limit-Account-State':'4:60:0'}),60)
        with connect(self.path) as c:c.execute("UPDATE leagues SET lifecycle='ended' WHERE id='A'")
        self.assertEqual(self.queue.status('A')['history']['reason'],'not_monitored')
    def test_unknown_pending_history_is_imported_after_admin_adds_the_league(self):
        self.fetch([{'entries':[raw(70,'Next League')],'truncated':False}])
        response=self.client.post('/api/league-catalog/leagues',json={'name':'Next League'})
        self.assertEqual(response.status_code,201,response.json);league=response.json['league_id']
        # Finish scheduled quantity work first, then the queued global history job.
        with patch('backend.ggg_history.GuildHistoryClient') as cls:
            cls.return_value.fetch.return_value=('[]',[])
            worker=Worker(self.queue)
            for _ in range(10):
                if not worker.run_once():break
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM transactions WHERE league_id=? AND external_id=?',(league,'70')).fetchone()[0],1)

    def test_shared_history_preserves_archived_raw_but_imports_only_monitored_leagues(self):
        self.assertEqual(self.client.put('/api/league-catalog/leagues/A',json={'lifecycle_override':'ended','version':0}).status_code,200)
        payload={'entries':[raw(101),raw(102,'B')],'truncated':False}
        def run(league,payload):
            self.queue.enqueue(league,'history','manual')
            with patch('backend.ggg_history.GuildHistoryClient') as client:
                client.return_value.fetch.return_value=(json.dumps(payload),payload)
                worker=Worker(self.queue)
                for _ in range(10):
                    if not worker.run_once():break
        run('B',payload)
        with connect(self.path) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM transactions WHERE league_id='A' AND external_id='101'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM transactions WHERE league_id='B' AND external_id='102'").fetchone()[0],1)
            self.assertIsNone(c.execute("SELECT transaction_id FROM guild_history_events WHERE league_name='A' AND external_id='101'").fetchone()[0])
        self.assertEqual(self.client.put('/api/league-catalog/leagues/A',json={'lifecycle_override':'active','version':1}).status_code,200)
        run('A',{'entries':[],'truncated':False})
        with connect(self.path) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM transactions WHERE league_id='A' AND external_id='101'").fetchone()[0],1)


class CatalogTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'db.sqlite';migrate(self.path)
        self.client=create_app({'TESTING':True,'DATABASE_FILE':self.path,'CATALOG_FETCH_AVAILABLE':True}).test_client()
    def publish(self,provider,payload):
        with connect(self.path) as c:
            c.execute('BEGIN IMMEDIATE');publish_catalog(c,provider,parse_catalog(provider,payload),payload);c.commit()
    def test_discovery_does_not_create_local_leagues_and_only_admin_can_add(self):
        self.publish('poe.ninja',[dict(id='New League',name='New League'),dict(id='HC New League',name='HC New League')])
        self.assertEqual(self.client.get('/api/leagues').json['leagues'],[])
        anonymous=self.client.application.test_client_class(self.client.application)
        self.assertEqual(anonymous.get('/api/league-catalog').status_code,401)
        self.assertEqual(anonymous.post('/api/league-catalog/leagues',json={'name':'Illegal'}).status_code,401)
        result=self.client.post('/api/league-catalog/leagues',json={'provider':'poe.ninja','external_id':'New League'})
        self.assertEqual(result.status_code,201,result.json)
        leagues=self.client.get('/api/leagues').json['leagues'];self.assertEqual(len(leagues),1);self.assertEqual(leagues[0]['lifecycle'],'active')
        self.assertTrue(leagues[0]['monitored'])
        self.assertEqual(self.client.post('/api/league-catalog/leagues',json={'provider':'poe.ninja','external_id':'New League'}).status_code,200)
    def test_connection_and_catalog_mutations_require_admin_and_csrf(self):
        anonymous=self.client.application.test_client_class(self.client.application)
        self.assertEqual(anonymous.get('/api/ggg-connection').status_code,401)
        self.assertEqual(anonymous.put('/api/ggg-connection',json={}).status_code,401)
        csrf=self.client.csrf;self.client.csrf=None
        self.assertEqual(self.client.post('/api/league-catalog/leagues',json={'name':'Wrong'}).status_code,403)
        self.assertEqual(self.client.put('/api/ggg-connection',json={}).status_code,403)
        self.client.csrf=csrf

    def test_newer_catalog_status_and_admin_override_take_precedence(self):
        league=self.client.post('/api/league-catalog/leagues',json={'name':'Old but active'}).json['league_id']
        self.publish('ggg',[dict(id='Old but active',name='Old but active',_list='main',startAt='2026-01-01T00:00:00Z')])
        self.assertEqual(self.client.get('/api/leagues').json['leagues'][0]['lifecycle'],'active')
        self.publish('poe.ninja',[dict(id='Other',name='Other')])
        self.assertEqual(self.client.get('/api/leagues').json['leagues'][0]['lifecycle'],'ended')
        policy=dict(lifecycle_override='active',version=0)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+league,json=policy).status_code,200)
        self.publish('ggg',[dict(id='Old but active',endAt='2026-01-01T00:00:00Z')])
        current=self.client.get('/api/leagues').json['leagues'][0];self.assertEqual(current['lifecycle'],'active');self.assertEqual(current['observed_lifecycle'],'ended')
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+league,json=policy).status_code,409)
        policy.update(version=1,lifecycle_override=None)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+league,json=policy).status_code,200)
        self.assertEqual(self.client.get('/api/leagues').json['leagues'][0]['lifecycle'],'ended')
    def test_empty_or_malformed_catalog_preserves_previous_evidence(self):
        self.publish('poe.ninja',[dict(id='Keep',name='Keep')])
        for payload in [[],{},[dict(id='Bad',name='')],[dict(id='Same'),dict(id='Same')]]:
            with self.assertRaises(ValueError):parse_catalog('poe.ninja',payload)
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT name FROM league_catalog_entries').fetchone()[0],'Keep')

    def test_ninja_assigns_status_to_existing_and_new_leagues_and_keeps_admin_override(self):
        existing=self.client.post('/api/league-catalog/leagues',json={'name':'Hardcore'}).json['league_id']
        self.publish('poe.ninja',[dict(id='Hardcore',name='Hardcore'),dict(id='New',name='New')])
        def state(league_id):return next(r for r in self.client.get('/api/leagues').json['leagues'] if r['id']==league_id)
        self.assertEqual(state(existing)['lifecycle'],'active')
        self.assertEqual(state(existing)['lifecycle_source'],'poe.ninja')
        added=self.client.post('/api/league-catalog/leagues',json={'provider':'poe.ninja','external_id':'New'}).json['league_id']
        self.assertEqual(state(added)['lifecycle'],'active')
        self.publish('poe.ninja',[dict(id='New',name='New')])
        self.assertEqual(state(existing)['lifecycle'],'ended')
        policy=dict(lifecycle_override='active',version=0)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+existing,json=policy).status_code,200)
        self.publish('poe.ninja',[dict(id='New',name='New')])
        self.assertEqual(state(existing)['lifecycle'],'active')
        self.assertEqual(state(existing)['lifecycle_source'],'manual')
        self.assertEqual(state(existing)['observed_lifecycle'],'ended')
        policy.update(lifecycle_override=None,version=1)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+existing,json=policy).status_code,200)
        self.assertEqual(state(existing)['lifecycle'],'ended')
        self.publish('poe.ninja',[dict(id='Hardcore',name='Hardcore')])
        self.assertEqual(state(existing)['lifecycle'],'active')
        self.assertEqual(state(added)['lifecycle'],'ended')

    def test_catalog_failure_does_not_archive_active_league(self):
        league=self.client.post('/api/league-catalog/leagues',json={'name':'Hardcore'}).json['league_id']
        self.publish('poe.ninja',[dict(id='Hardcore',name='Hardcore')])
        queue=Queue(self.path,catalog_available=True,cooldown=0)
        queue.enqueue(None,'league_catalog','manual');job=queue.claim('worker')
        for response in ['[]','not JSON']:
            with patch('backend.league_catalog.NinjaClient') as ninja,patch('backend.league_catalog.ggg_configuration',return_value=None):
                ninja.return_value.fetch.return_value=response
                publication=LeagueCatalogAdapter().stage(queue,job,threading.Event())
            with connect(self.path) as c:
                c.execute('BEGIN IMMEDIATE');publication(c);c.commit()
            state=next(r for r in self.client.get('/api/leagues').json['leagues'] if r['id']==league)
            self.assertEqual(state['lifecycle'],'active')
            self.assertEqual(state['lifecycle_source'],'poe.ninja')

    def test_archiving_disables_monitoring_and_fences_queued_and_running_fetches(self):
        league=self.client.post('/api/league-catalog/leagues',json={'name':'Hardcore'}).json['league_id']
        self.publish('poe.ninja',[dict(id='Hardcore',name='Hardcore')])
        queue=Queue(self.path,cooldown=0)
        queued=queue.enqueue(league,'prices','manual')['job_id']
        policy=dict(lifecycle_override='ended',version=0)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+league,json=policy).status_code,200)
        self.assertFalse(self.client.get('/api/leagues').json['leagues'][0]['monitored'])
        self.assertEqual(queue.enqueue(league,'history','manual')['reason'],'not_monitored')
        self.assertIsNone(queue.claim('worker'))
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT error_code FROM jobs WHERE id=?',(queued,)).fetchone()[0],'not_monitored')
        policy.update(lifecycle_override='active',version=1)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+league,json=policy).status_code,200)
        self.assertTrue(self.client.get('/api/leagues').json['leagues'][0]['monitored'])
        queued=queue.enqueue(league,'prices','manual')['job_id'];lease=queue.claim('worker')
        policy.update(lifecycle_override='ended',version=2)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+league,json=policy).status_code,200)
        queue.complete(lease,lambda c:self.fail('Archived price publication ran'))
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT error_code FROM jobs WHERE id=?',(queued,)).fetchone()[0],'not_monitored')
            self.assertEqual(c.execute('SELECT monitored FROM leagues WHERE id=?',(league,)).fetchone()[0],0)
        policy.update(lifecycle_override=None,version=3)
        self.assertEqual(self.client.put('/api/league-catalog/leagues/'+league,json=policy).status_code,200)
        self.assertTrue(self.client.get('/api/leagues').json['leagues'][0]['monitored'])
    def test_catalog_global_job_deduplication_and_fenced_publication(self):
        queue=Queue(self.path,catalog_available=True,cooldown=0)
        first=queue.enqueue(None,'league_catalog','manual');second=queue.enqueue(None,'league_catalog','automatic')
        self.assertEqual(first['job_id'],second['job_id']);job=queue.claim('worker')
        with patch('backend.league_catalog.NinjaClient') as ninja,patch('backend.league_catalog.ggg_configuration',return_value=None):
            ninja.return_value.fetch.return_value='[{"id":"Candidate","name":"Candidate"}]'
            publish=LeagueCatalogAdapter().stage(queue,job,threading.Event())
        queue.complete(job,publish)
        self.assertEqual(queue.enqueue(None,'league_catalog','manual')['outcome'],'fresh')
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM leagues').fetchone()[0],0)
    def test_ggg_catalog_uses_authenticated_pagination_and_known_league_details(self):
        calls=[]
        class Client(GGGLeaguesClient):
            def fetch(self,path):
                calls.append(path)
                if '/Old?' in path:return {'league':{'id':'Old','endAt':'2026-01-01T00:00:00Z'}}
                if 'type=event' in path:return {'leagues':[]}
                return {'leagues':[{'id':'Current','category':{'current':True},'rules':[{'id':'Hardcore'}]}]}
        payload=Client(self.path,('not-real','agent')).leagues(['Old'],threading.Event());rows=parse_catalog('ggg',payload)
        self.assertTrue(all('realm=poe2' in url for url in calls))
        self.assertEqual({r['name']:r['lifecycle'] for r in rows},{'Current':'active','Old':'ended'})
        self.assertTrue(json.loads(next(r['variant_json'] for r in rows if r['name']=='Current'))['hardcore'])
