import hashlib,json,sqlite3
from unittest import TestCase
from unittest.mock import patch
from backend.database import connect
from backend.league_deletion import deleted_names,redact_history
from backend.jobs import Queue
from backend.worker import Worker
from tests import test_phase7 as history_fixture
from tests.test_phase7 import raw
from tests import test_database as database_fixture
from tests.auth_helpers import create_app
from tests import test_prices as price_fixture


class DeletionTests(TestCase):
    setUp=history_fixture.HistoryTests.setUp
    insert=history_fixture.HistoryTests.insert
    fetch=history_fixture.HistoryTests.fetch
    put=price_fixture.ValuationTests.put
    value=price_fixture.ValuationTests.value
    def delete(self,league='A',**kwargs):
        row=next(r for r in self.client.get('/api/league-catalog').json['leagues'] if r['id']==league)
        return self.client.delete('/api/league-catalog/leagues/'+league,json={'name':row['name'],'version':row['version'],**kwargs})

    def test_delete_removes_derived_and_source_data_but_preserves_other_league(self):
        self.fetch([{'entries':[raw(80),raw(81,'B')],'truncated':False}])
        # Build derived records as well, including technical corrections.
        worker=Worker(self.queue)
        for _ in range(20):
            if not worker.run_once():break
        self.put(2,'2026-01-01T00:00:00Z');self.put(3,'2026-01-01T00:00:00Z',league='B');self.value()
        with connect(self.path) as c:
            before=[tuple(r) for r in c.execute("SELECT * FROM transactions WHERE league_id='B' ORDER BY id")]
            self.assertGreater(c.execute("SELECT count(*) FROM valuation_lines WHERE run_id IN (SELECT id FROM valuation_runs WHERE league_id='A')").fetchone()[0],0)
        result=self.delete();self.assertEqual(result.status_code,200,result.json)
        with connect(self.path) as c:
            self.assertIsNone(c.execute("SELECT 1 FROM leagues WHERE id='A'").fetchone())
            self.assertEqual(before,[tuple(r) for r in c.execute("SELECT * FROM transactions WHERE league_id='B' ORDER BY id")])
            self.assertEqual(c.execute("SELECT count(*) FROM guild_history_events WHERE league_name='A'").fetchone()[0],0)
            self.assertIn('A',deleted_names(c))
            self.assertEqual(c.execute("SELECT count(*) FROM price_snapshots WHERE league_id='A'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM price_snapshots WHERE league_id='B'").fetchone()[0],1)
            for page in c.execute('SELECT * FROM guild_history_pages'):
                self.assertEqual(hashlib.sha256(page['payload_json'].encode()).hexdigest(),page['sha256'])
                self.assertEqual([r['League'] for r in json.loads(page['payload_json'])['entries']],['B'])
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(self.client.get('/api/leagues/A/transactions').status_code,404)

    def test_deleted_history_is_not_restored_by_global_fetch(self):
        self.fetch([{'entries':[raw(90),raw(91,'B')],'truncated':False}])
        self.assertEqual(self.delete().status_code,200)
        # Use B to trigger the shared guild request after A has been deleted.
        class Client:
            def __init__(self,*args):pass
            def fetch(self,*args):
                payload={'entries':[raw(90),raw(92,'B')],'truncated':False}
                return json.dumps(payload),payload
        self.queue.enqueue('B','history','manual')
        with patch('backend.ggg_history.GuildHistoryClient',Client):
            worker=Worker(self.queue)
            for _ in range(20):
                if not worker.run_once():break
        with connect(self.path) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM guild_history_events WHERE league_name='A'").fetchone()[0],0)
            for page in c.execute('SELECT payload_json FROM guild_history_pages'):
                self.assertNotIn('"League":"A"',page[0]);self.assertNotIn('"League": "A"',page[0])
        result=self.client.post('/api/league-catalog/leagues',json={'name':'A'})
        self.assertEqual(result.status_code,201,result.json)
        # Fixture IDs A/B differ from production deterministic IDs, so verify
        # removal by identity (name/game/realm), not only ID, below.
        with connect(self.path) as c:self.assertNotIn('A',deleted_names(c))

    def test_running_jobs_and_stale_confirmation_block_deletion(self):
        self.assertEqual(self.delete(version=999).status_code,409)
        job=self.queue.enqueue('B','history','manual');self.queue.claim('worker')
        self.assertEqual(self.delete().status_code,409)
        with connect(self.path) as c:self.assertIsNotNone(c.execute("SELECT 1 FROM leagues WHERE id='A'").fetchone())

    def test_delete_requires_admin_and_csrf(self):
        anonymous=self.client.application.test_client_class(self.client.application)
        self.assertEqual(anonymous.delete('/api/league-catalog/leagues/A',json={'name':'A','version':0}).status_code,401)
        self.client.csrf=None
        self.assertEqual(self.delete().status_code,403)

    def test_failure_rolls_back_deletion_and_last_league_can_be_removed(self):
        with connect(self.path) as c:before=[tuple(r) for r in c.execute('SELECT * FROM transactions ORDER BY id')]
        def fail(c,league):
            c.execute('DELETE FROM transactions WHERE league_id=?',(league['id'],))
            raise sqlite3.OperationalError('simulated failure')
        with patch('backend.catalog_api.purge_league',side_effect=fail):
            self.assertEqual(self.delete().status_code,503)
        with connect(self.path) as c:
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM transactions ORDER BY id')])
            self.assertNotIn('A',deleted_names(c))
        self.assertEqual(self.delete().status_code,200)
        self.assertEqual(self.delete('B').status_code,200)
        self.assertEqual(self.delete('C').status_code,200)
        self.assertEqual(self.client.get('/api/leagues').json['leagues'],[])



class RebuildDeletionTests(TestCase):
    setUp=database_fixture.DatabaseTests.setUp
    row=database_fixture.DatabaseTests.row
    write_history=database_fixture.DatabaseTests.write_history
    save_manifest=database_fixture.DatabaseTests.save_manifest
    def test_rebuild_does_not_restore_deleted_archive_league(self):
        from backend.archive_import import import_bundle
        from backend.database_lifecycle import rebuild
        import_bundle(self.database,self.data)
        client=create_app({'TESTING':True,'DATABASE_FILE':self.database}).test_client()
        league=next(r for r in client.get('/api/league-catalog').json['leagues'] if r['name']=='Alpha')
        result=client.delete('/api/league-catalog/leagues/'+league['id'],json={'name':'Alpha','version':0})
        self.assertEqual(result.status_code,200,result.json)
        rebuild(self.database,self.data)
        with connect(self.database) as c:
            self.assertEqual([r[0] for r in c.execute('SELECT name FROM leagues')],['Beta'])
            self.assertEqual(c.execute('SELECT count(*) FROM transactions').fetchone()[0],1)
            self.assertIn('Alpha',deleted_names(c));self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
