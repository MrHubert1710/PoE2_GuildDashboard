import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import sqlite3
import unittest
from unittest.mock import patch

from backend.app import create_app
from backend.archive_import import canonical, normalize
from backend.database import connect, migrate
from backend.jobs import Queue, LeaseLost
from backend.quantities import DEFAULTS, replay, parse_quantity, validate_settings, QuantityAdapter
from backend.worker import Worker, AdapterFailure


def event(index, action, quantity, item='Token', **changes):
    value = dict(id=index, external_id=str(index), source_id=1, occurred_at=f'2026-01-01T00:{index:02}:00.000000Z',
                 account='Alice', action=action, item=f'{quantity}× {item}', stash='Main', x=0, y=0)
    value.update(changes)
    return value


class ReplayTests(unittest.TestCase):
    def test_signed_changes_zero_baseline_unchanged_and_empty_anchor(self):
        data = replay([event(1,'modified',20), event(2,'modified',15), event(3,'added',2), event(4,'removed',3),
                       event(5,'modified',14), event(6,'modified',0), event(7,'added',5)], DEFAULTS)
        self.assertEqual([r['quantity_delta'] for r in data['events']], [20,-5,2,-3,0,-14,5])
        self.assertEqual([r['effective_action'] for r in data['events']], ['added','removed','added','removed','unchanged','removed','added'])
        self.assertEqual(data['states'][0]['quantity'],5)

    def test_first_added_and_following_modified_use_zero_baseline(self):
        data = replay([event(1,'added',10), event(2,'modified',12), event(3,'modified',9)], DEFAULTS)
        self.assertEqual([r['quantity_delta'] for r in data['events']], [10,2,-3])
        self.assertEqual(data['events'][0]['quantity_after'],10)

    def test_item_replacement_has_two_inferred_movements_and_no_combined_delta(self):
        data = replay([event(1,'modified',10,'A'), event(2,'modified',5,'B')], DEFAULTS)
        self.assertEqual([(m['item_name'],m['quantity_delta'],m['confidence']) for m in data['movements']], [('A',10,'derived'),('A',-10,'inferred'),('B',5,'inferred')])
        self.assertEqual(data['events'][1]['effective_action'],'mixed')
        self.assertIsNone(data['events'][1]['quantity_delta'])

    def test_source_stash_and_coordinates_are_separate(self):
        rows = [event(1,'modified',10),event(2,'modified',5,source_id=2),event(3,'modified',6,stash='Other'),event(4,'modified',7,x=1)]
        self.assertEqual([r['quantity_delta'] for r in replay(rows,DEFAULTS)['events']], [10,5,6,7])

    def test_numeric_id_tiebreak_and_ambiguous_ids_do_not_guess(self):
        rows = [event(10,'modified',8),event(2,'modified',10,occurred_at='2026-01-01T00:10:00.000000Z')]
        self.assertEqual([r['quantity_delta'] for r in replay(rows,DEFAULTS)['events']], [10,-2])
        rows[0]['external_id']='opaque';rows[1]['external_id']='another'
        data = replay(rows,DEFAULTS)
        self.assertTrue(all(r['resolution_reason']=='ambiguous_order' for r in data['events']))
        self.assertIsNone(data['states'][0]['quantity'])

    def test_underflow_invalid_quantity_and_reanchoring(self):
        rows = [event(1,'modified',3),event(2,'removed',5),event(3,'modified',4),event(4,'modified',3)]
        data = replay(rows,DEFAULTS)
        self.assertEqual(data['events'][1]['resolution_reason'],'state_conflict')
        self.assertIsNone(data['events'][1]['quantity_after'])
        self.assertEqual([r['quantity_delta'] for r in data['events']], [3,-5,None,-1])
        rows[1]['item']='-5x Token'
        self.assertEqual(replay(rows,DEFAULTS)['events'][1]['resolution_reason'],'invalid_quantity')

    def test_quantity_parser_handles_legacy_notations_and_rejects_unsafe_numbers(self):
        for text in ['67x Orb','67× Orb','67Ă— Orb','67X Orb']:
            self.assertEqual(parse_quantity(text),(67,'Orb'))
        self.assertEqual(parse_quantity('7 League Boots'),(1,'7 League Boots'))
        self.assertEqual(parse_quantity('0× Orb'),(0,'Orb'))
        for text in ['', '12x','-3x Orb','1.5x Orb','1000000001× Orb']:
            with self.assertRaises(ValueError):parse_quantity(text)

    def test_selection_and_alias_merge_only_when_explicit(self):
        rows=[event(1,'modified',10,stash='Typo'),event(2,'modified',7,stash='Main')]
        settings=dict(DEFAULTS,stash_aliases={'Typo':'Main'},target_stashes=['Main','Future stash'])
        self.assertEqual(replay(rows,settings)['events'][1]['quantity_delta'],-3)
        self.assertEqual(replay(rows,DEFAULTS)['events'][1]['quantity_delta'],7)
        self.assertEqual(replay(rows,dict(DEFAULTS,target_stashes=[]))['states'],[])

    def test_every_league_starts_empty(self):
        data=replay([event(1,'added',10),event(2,'modified',7)],DEFAULTS)
        self.assertEqual([r['quantity_delta'] for r in data['events']],[10,-3])
        self.assertEqual(data['events'][0]['quantity_before'],0)

    def test_empty_history_and_zero_movements_stay_zero(self):
        self.assertEqual(replay([],DEFAULTS),dict(events=[],movements=[],states=[]))
        for action in ('added','removed','modified'):
            data=replay([event(1,action,0)],DEFAULTS)
            row=data['events'][0]
            self.assertEqual((row['quantity_before'],row['quantity_after'],row['quantity_delta']),(0,0,0))
            self.assertEqual(row['effective_action'],'unchanged')
            self.assertEqual(data['movements'],[])

    def test_settings_validation(self):
        self.assertEqual(validate_settings(dict(DEFAULTS,timezone='Europe/Warsaw'))['timezone'],'Europe/Warsaw')
        for value in [[],dict(DEFAULTS,timezone='Mars/Here'),dict(DEFAULTS,stash_aliases={'A':'B','B':'A'}),dict(DEFAULTS,target_stashes='Main'),dict(DEFAULTS,stash_aliases={'A':'B','B':'C'})]:
            with self.assertRaises(ValueError):validate_settings(value)

    def test_legacy_agreement_on_known_baseline_and_explicit_boundary_difference(self):
        # Extract only the three arithmetic functions. Never import/execute legacy config or IO.
        legacy = Path(__file__).resolve().parents[2]/'poe2-guild/poe2logger/processing.py'
        if not legacy.exists():self.skipTest('Independent legacy checkout unavailable')
        tree=ast.parse(legacy.read_text())
        names={'add_operation_entry','calculate_operation_summaries','calculate_final_stash_state'}
        namespace={'player_summary':defaultdict(lambda:defaultdict(lambda:dict(added=0,removed=0))),
                   'stash_summary':defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:dict(added=0,removed=0)))),
                   'coordinate_state':{},'final_stash_state':{}}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(legacy),'exec'),namespace)
        rows=[event(1,'modified',0),event(2,'added',10),event(3,'modified',15),event(4,'removed',3),event(5,'modified',7),event(6,'modified',2,'Other')]
        namespace['log_events']=[dict(r,quantity=parse_quantity(r['item'])[0],item_name=parse_quantity(r['item'])[1],parsed_date=r['occurred_at'],parsed_id=int(r['external_id']),date=r['occurred_at']) for r in rows]
        namespace['calculate_operation_summaries']();namespace['calculate_final_stash_state']()
        data=replay(rows,DEFAULTS)
        totals=defaultdict(lambda:dict(added=0,removed=0))
        for m in data['movements']:totals[m['item_name']]['added' if m['quantity_delta']>0 else 'removed']+=abs(m['quantity_delta'])
        self.assertEqual(dict(totals),dict(namespace['player_summary']['Alice']))
        self.assertEqual(data['states'][0]['quantity'],namespace['final_stash_state'][('Main',0,0)]['quantity'])
        self.assertEqual(replay([event(1,'modified',20)],DEFAULTS)['events'][0]['quantity_delta'],20)


class QuantityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'quantities.sqlite';migrate(self.path)
        with connect(self.path) as c:
            for source in [1,2]:
                c.execute('INSERT INTO sources VALUES (?,?,?,NULL,?)',(source,f'guild-{source}','local','2026-01-01'))
                c.execute("INSERT INTO import_runs(id,source_id,started_at,status,manifest_sha256) VALUES (?,?,?,'completed','hash')",(f'import-{source}',source,'2026-01-01'))
            for league,source in [('A',1),('B',1),('C',2)]:
                c.execute("INSERT INTO leagues(id,game,realm,name) VALUES (?,'poe2','pc',?)",(league,league))
                c.execute("INSERT INTO revisions VALUES (?,?,?,'2026-01-01','raw_import','test',NULL)",(f'raw-{league}',league,f'import-{source}'))
        rows=[event(1,'modified',20),event(2,'modified',15,account='Buyer',occurred_at='2026-01-02T00:00:00.000000Z'),
              event(3,'modified',0,x=1),event(4,'added',5,'Other',x=1)]
        for row in rows:self.insert(row,'A')
        self.insert(event(10,'modified',100),'B');self.insert(event(11,'modified',90),'B')
        self.insert(event(20,'modified',12,source_id=2),'C')
        self.client=create_app({'TESTING':True,'DATABASE_FILE':self.path}).test_client()
        self.queue=Queue(self.path,cooldown=0)

    def insert(self,row,league):
        raw=dict(Date=row['occurred_at'],Id=row['external_id'],League=league,Account=row['account'],Action=row['action'],Stash=row['stash'],Item=row['item'],X=str(row['x']),Y=str(row['y']))
        norm=normalize(raw,league)
        with connect(self.path) as c:
            c.execute('INSERT INTO transactions(source_id,league_id,external_id,occurred_at,account,action,stash,item,x,y,raw_json,normalized_sha256,normalization_version,import_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (row['source_id'],league,row['external_id'],row['occurred_at'],row['account'],row['action'],row['stash'],row['item'],row['x'],row['y'],canonical(raw),hashlib.sha256(canonical(norm).encode()).hexdigest(),'v1',f"import-{row['source_id']}"))

    def build(self,league='A'):
        self.queue.enqueue(league,'quantities','automatic');Worker(self.queue).run_once()
        return self.client.get(f'/api/leagues/{league}/quantities').json

    def config(self,league='A'):return self.client.get(f'/api/leagues/{league}/quantity-settings').json
    def save(self,settings,league='A',scope='league',**extra):
        current=self.config(league)
        return self.client.put(f'/api/leagues/{league}/quantity-settings',json=dict(expected_hash=current['settings_hash'],expected_guild_hash=current['guild_hash'],settings=settings,scope=scope,**extra))

    def test_projection_preserves_source_and_annotates_every_transaction(self):
        with connect(self.path) as c:before=[tuple(r) for r in c.execute('SELECT * FROM transactions')]
        result=self.build();self.assertEqual(result['projection']['state'],'ready')
        events=self.client.get('/api/leagues/A/transactions?direction=asc').json['rows']
        row=next(e for e in events if e['external_id']=='2')
        self.assertEqual(events[0]['action'],'modified');self.assertEqual(row['quantity']['quantity_delta'],-5)
        self.assertEqual(row['quantity']['effective_action'],'removed')
        self.assertEqual(events[0]['quantity']['quantity_delta'],20)
        with connect(self.path) as c:self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM transactions')])
        self.assertEqual(self.queue.enqueue('A','quantities','automatic')['outcome'],'fresh')

    def test_filter_replays_prior_days_and_accounts_before_applying_filters(self):
        self.build()
        result=self.client.get('/api/leagues/A/quantities?account=Buyer&from=2026-01-02&to=2026-01-02').json
        self.assertEqual(result['stats']['events'],1)
        self.assertEqual(result['rows'][0]['removed'],5)
        self.assertEqual(result['rows'][0]['net'],-5)

    def test_group_views_final_state_and_literal_filters(self):
        self.build()
        for view,column in [('players','account'),('stashes','stash')]:
            result=self.client.get('/api/leagues/A/quantities?view='+view)
            self.assertEqual(result.status_code,200);self.assertIn(column,result.json['rows'][0])
        state=self.client.get('/api/leagues/A/quantities?view=state').json
        self.assertEqual(sorted(r['quantity'] for r in state['rows']),[5,15])
        self.assertEqual(self.client.get('/api/leagues/A/quantities?item=%25_').json['total'],0)
        self.assertEqual(self.client.get('/api/leagues/A/quantities?page=999').json['page'],1)
        self.assertEqual(self.client.get('/api/leagues/A/quantities?view=state&account=Alice').status_code,400)

    def test_guild_defaults_inherit_names_but_never_inventory_between_leagues_or_guilds(self):
        self.save(dict(DEFAULTS,stash_aliases={'Main':'Shared'},target_stashes=['Shared','Future']),scope='guild')
        self.assertEqual(self.config('B')['settings']['stash_aliases'],{'Main':'Shared'})
        self.assertEqual(self.config('C')['settings'],DEFAULTS)
        self.build('A');b=self.build('B')
        self.assertEqual(b['rows'][0]['removed'],10)
        rows=self.client.get('/api/leagues/B/transactions?direction=asc').json['rows']
        self.assertEqual(rows[0]['quantity']['quantity_delta'],100)
        self.assertEqual(self.client.get('/api/leagues/B/quantities?view=state').json['rows'][0]['quantity'],90)

    def test_per_league_override_and_restore_inheritance(self):
        self.save(dict(DEFAULTS,timezone='Europe/Warsaw'),'B')
        self.save(dict(DEFAULTS,timezone='Europe/London'),scope='guild')
        self.assertEqual(self.config('A')['settings']['timezone'],'Europe/London')
        self.assertEqual(self.config('B')['settings']['timezone'],'Europe/Warsaw')
        self.save(DEFAULTS,'B',scope='inherit')
        self.assertEqual(self.config('B')['settings']['timezone'],'Europe/London')

    def test_settings_change_invalidates_projection_preserves_old_run_and_rejects_lost_update(self):
        old=self.build()['projection']['id'];configuration=self.config()
        self.assertEqual(self.save(dict(DEFAULTS,target_stashes=[])).status_code,200)
        current=self.client.get('/api/leagues/A/quantities').json
        self.assertEqual(current['projection']['state'],'stale');self.assertEqual(current['rows'],[])
        self.assertEqual(self.client.get('/api/leagues/A/transactions').json['rows'],[])
        response=self.client.put('/api/leagues/A/quantity-settings',json={'expected_hash':configuration['settings_hash'],'settings':DEFAULTS})
        self.assertEqual(response.status_code,409)
        result=self.build();self.assertEqual(result['stats']['events'],0)
        self.assertEqual(result['stats']['excluded'],0)
        with connect(self.path) as c:self.assertIsNotNone(c.execute('SELECT * FROM quantity_runs WHERE id=?',(old,)).fetchone())

    def test_hidden_stashes_are_removed_from_all_views_before_rebuild_and_can_be_restored(self):
        self.insert(event(30,'added',2,stash='Special',x=5),'A')
        self.build()
        self.save(dict(DEFAULTS,target_stashes=['Special'],stash_aliases={'Main':'Renamed'}))
        # Visibility follows saved settings immediately, even while the projection is stale.
        league=next(row for row in self.client.get('/api/leagues').json['leagues'] if row['id']=='A')
        self.assertEqual(league['stashes'],['Special'])
        self.assertEqual(league['transactions'],1)
        self.assertEqual(self.client.get('/api/leagues/A/transactions').json['total'],1)
        self.assertEqual(self.client.get('/api/leagues/A/transactions?stash=Main').json['total'],0)
        self.assertEqual(set(self.config()['stashes']),{'Main','Special'})
        self.assertEqual(self.client.get('/api/leagues/A/quantities').json['projection']['state'],'stale')
        self.build()
        for view in ('summary','players','stashes','state'):
            report=self.client.get('/api/leagues/A/quantities?view='+view).json
            self.assertEqual(report['stats']['events'],1)
            self.assertEqual(report['stats']['excluded'],0)
            self.assertTrue(all(row.get('stash','Special')=='Special' for row in report['rows']))
        with connect(self.path) as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM transactions WHERE league_id='A'").fetchone()[0],5)
        self.save(DEFAULTS)
        self.assertEqual(self.client.get('/api/leagues/A/transactions').json['total'],5)
        self.build()
        self.assertEqual(self.client.get('/api/leagues/A/quantities').json['stats']['events'],5)

    def test_alias_selection_hides_raw_names_and_guild_defaults_apply_per_league(self):
        self.save(dict(DEFAULTS,stash_aliases={'Main':'Shared'},target_stashes=['Shared']),scope='guild')
        a=next(row for row in self.client.get('/api/leagues').json['leagues'] if row['id']=='A')
        self.assertEqual(a['stashes'],['Main'])
        self.assertEqual(a['transactions'],4)
        self.save(dict(DEFAULTS,target_stashes=[]),scope='guild')
        leagues={row['id']:row for row in self.client.get('/api/leagues').json['leagues']}
        self.assertEqual(leagues['A']['transactions'],0)
        self.assertEqual(leagues['B']['transactions'],0)
        self.assertEqual(leagues['C']['transactions'],1)
        self.assertEqual(self.client.get('/api/leagues/B/transactions').json['rows'],[])

    def test_input_change_and_settings_change_fence_staged_publication(self):
        self.queue.enqueue('A','quantities','automatic');lease=self.queue.claim('worker')
        callback=QuantityAdapter().stage(self.queue,lease,threading.Event())
        self.save(dict(DEFAULTS,timezone='Europe/Warsaw'))
        with self.assertRaises(AdapterFailure):self.queue.complete(lease,callback)
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM quantity_runs').fetchone()[0],0)

    def test_http_validation_and_no_generation_from_get(self):
        for query in ['view=bad','page=0','page_size=1','unknown=x','from=2026-02-31','page=1&page=2']:
            self.assertEqual(self.client.get('/api/leagues/A/quantities?'+query).status_code,400)
        self.assertEqual(self.client.get('/api/leagues/missing/quantities').status_code,404)
        self.assertEqual(self.client.get('/api/leagues/A/quantities').json['projection']['state'],'missing')
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
        for payload in [[],{},dict(settings=DEFAULTS,expected_hash='',scope=[]),dict(settings=dict(DEFAULTS,timezone='bad'),expected_hash='')]:
            self.assertEqual(self.client.put('/api/leagues/A/quantity-settings',json=payload).status_code,400)

    def test_stale_expected_input_or_projection_is_not_silently_replaced(self):
        self.build()
        self.assertEqual(self.client.get('/api/leagues/A/quantities?revision=old').status_code,409)
        self.assertEqual(self.client.get('/api/leagues/A/quantities?projection_id=old').status_code,409)

    def test_quantity_jobs_do_not_spend_history_fetch_budget(self):
        self.build()
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM automatic_attempts').fetchone()[0],0)

    def test_zero_baseline_does_not_depend_on_history_coverage(self):
        first=self.build()['projection']['id']
        for coverage in (None, 0, 1):
            with connect(self.path) as c:c.execute("UPDATE leagues SET history_complete=? WHERE id='A'",(coverage,))
            result=self.client.get('/api/leagues/A/quantities').json
            self.assertEqual(result['projection']['state'],'ready')
            self.assertEqual(result['projection']['id'],first)
            self.assertEqual(result['projection']['initial_state'],'empty')

    def test_no_transactions_has_zero_totals_and_empty_state(self):
        with connect(self.path) as c:c.execute("DELETE FROM transactions WHERE league_id='C'")
        result=self.build('C')
        self.assertEqual(result['rows'],[])
        self.assertTrue(all(value == 0 for value in result['stats'].values()))
        self.assertEqual(self.client.get('/api/leagues/C/quantities?view=state').json['rows'],[])

    def test_old_algorithm_projection_is_stale_and_preserved(self):
        with patch('backend.quantities.ALGORITHM', 'quantities-v1'):
            first=self.build()['projection']['id']
        self.assertEqual(self.client.get('/api/leagues/A/quantities').json['projection']['state'],'stale')
        self.assertEqual(self.build()['projection']['algorithm_version'],'quantities-v2')
        with connect(self.path) as c:self.assertEqual(c.execute('SELECT algorithm_version FROM quantity_runs WHERE id=?',(first,)).fetchone()[0],'quantities-v1')

    def test_database_rejects_cross_league_projection_links(self):
        run=self.build()['projection']['id']
        with connect(self.path) as c:
            transaction=c.execute("SELECT id FROM transactions WHERE league_id='B' LIMIT 1").fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO event_quantities(league_id,run_id,transaction_id,item_name,stash,effective_action,confidence,resolution_reason) VALUES ('A',?,?,'Token','Main','unknown','unknown','unknown_before')",(run,transaction))

    def test_multiselect_stash_filter_is_shared_by_summary_and_reconstructed_state(self):
        self.insert(event(99,'added',2,'Comma',stash='Tab, %_',x=2,occurred_at='2026-01-02T12:00:00.000000Z'),'A')
        self.build()
        for view in ('summary','players','stashes','state'):
            selected = self.client.get('/api/leagues/A/quantities',query_string=[('view',view),('stash','Main'),('stash','Tab, %_')])
            self.assertEqual(selected.status_code,200)
            if view != 'state':self.assertEqual(selected.json['stats']['events'],5)
        single = self.client.get('/api/leagues/A/quantities',query_string=[('stash','Tab, %_')]).json
        repeated = self.client.get('/api/leagues/A/quantities',query_string=[('stash','Tab, %_'),('stash','Tab, %_')]).json
        self.assertEqual(single['stats']['events'],1)
        self.assertEqual(single['rows'],repeated['rows'])
        self.assertEqual(self.client.get('/api/leagues/A/quantities',query_string=[('stash','Main')]*101).status_code,400)

    def test_aliases_in_multiselect_do_not_double_count_movements(self):
        self.save(dict(DEFAULTS,stash_aliases={'Main':'Shared'}))
        self.build()
        one=self.client.get('/api/leagues/A/quantities?stash=Main').json
        both=self.client.get('/api/leagues/A/quantities?stash=Main&stash=Shared').json
        self.assertEqual(one['rows'],both['rows'])
        self.assertEqual(one['stats'],both['stats'])

    def test_regex_filters_apply_to_groups_stats_and_final_state(self):
        self.build()
        url='/api/leagues/A/quantities'
        literal=self.client.get(url,query_string={'account':'^buyer$'})
        self.assertEqual(literal.json['stats']['events'],0)
        filtered=self.client.get(url,query_string={'account':'^buyer$','account_regex':'1','item':'^(Token|Other)$','item_regex':'1'})
        self.assertEqual(filtered.status_code,200)
        self.assertEqual(filtered.json['stats']['events'],1)
        self.assertEqual(filtered.json['rows'][0]['net'],-5)
        for view in ('summary','players','stashes','state'):
            result=self.client.get(url,query_string={'view':view,'item':'^Other$','item_regex':'1'})
            self.assertEqual(result.status_code,200)
            self.assertTrue(all(row['item_name']=='Other' for row in result.json['rows']))
        invalid=self.client.get(url,query_string={'item':'[','item_regex':'1'})
        self.assertEqual((invalid.status_code,invalid.json['error']),(400,'invalid_item_regex'))

    def test_regex_timeout_in_quantity_api_returns_actionable_error(self):
        from unittest.mock import patch
        from flask import g
        self.build()
        def timeout(_self,_value):
            g.regex_error='regex_timeout'
            raise TimeoutError()
        with patch('backend.text_search.RegexMatcher.matches',timeout):
            result=self.client.get('/api/leagues/A/quantities?item=.*&item_regex=1')
        self.assertEqual((result.status_code,result.json['error']),(400,'regex_timeout'))

    def test_case_and_word_modes_apply_to_quantity_names_and_accounts(self):
        self.build()
        url='/api/leagues/A/quantities'
        result=self.client.get(url,query_string={'account':'buyer','account_case':'1'})
        self.assertEqual(result.json['stats']['events'],0)
        result=self.client.get(url,query_string={'account':'Buyer','account_word':'1','item':'Token','item_case':'1'})
        self.assertEqual(result.json['stats']['events'],1)
        for view in ('summary','players','stashes','state'):
            result=self.client.get(url,query_string={'view':view,'item':'Oth','item_word':'1'})
            self.assertEqual(result.json['rows'],[])
            result=self.client.get(url,query_string={'view':view,'item':'other','item_word':'1'})
            self.assertEqual(result.json['rows'][0]['item_name'],'Other')
