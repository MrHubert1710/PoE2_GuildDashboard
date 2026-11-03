"""Explicit league deletion, including derived data and fetched source records.

Source archive files/backups are immutable recovery inputs. A small deletion
record prevents a rebuild or a global history fetch from restoring the league.
"""
import hashlib
import json
from urllib.parse import urlsplit,parse_qs
from .archive_import import canonical
from .database import utc_now

KEY='deleted_leagues'


def deleted_leagues(c):
    row=c.execute('SELECT value FROM metadata WHERE key=?',(KEY,)).fetchone()
    return json.loads(row[0]) if row else []


def deleted_names(c):
    return {row['name'] for row in deleted_leagues(c) if row['game']=='poe2' and row['realm']=='pc'}


def redact_history(body,names):
    """Remove deleted leagues from shared pages without losing other leagues."""
    changed=False
    def visit(value):
        nonlocal changed
        if isinstance(value,list):
            result=[]
            for entry in value:
                league=entry.get('League',entry.get('league')) if isinstance(entry,dict) else None
                if isinstance(league,str) and league.strip() in names:changed=True;continue
                result.append(visit(entry))
            return result
        if isinstance(value,dict):return {key:visit(item) for key,item in value.items()}
        return value
    payload=visit(json.loads(body))
    if changed:
        if isinstance(payload,dict):payload['_poa_redacted']=True
        return canonical(payload)
    return body


def purge_league(c,league):
    """Caller holds BEGIN IMMEDIATE; child-first deletes preserve foreign keys."""
    # SQLite checks surviving children for each parent row. Build reverse FK
    # indexes on first use to avoid quadratic scans of other leagues' records.
    for table,columns in (
        ('valuation_lines','transaction_id'),('valuation_lines','snapshot_id,quote_key'),
        ('inventory_value_points','snapshot_id,quote_key'),('event_quantities','transaction_id'),
        ('quantity_state','transaction_id'),('guild_history_events','transaction_id'),
        ('guild_history_events','page_id'),
    ):
        c.execute('CREATE INDEX IF NOT EXISTS deletion_'+table+'_'+columns.replace(',','_')+' ON '+table+'('+columns+')')
    league_id,name=league['id'],league['name']
    c.execute('DELETE FROM valuation_lines WHERE run_id IN (SELECT id FROM valuation_runs WHERE league_id=?)',(league_id,))
    c.execute('DELETE FROM inventory_value_points WHERE run_id IN (SELECT id FROM valuation_runs WHERE league_id=?)',(league_id,))
    c.execute('DELETE FROM valuation_runs WHERE league_id=?',(league_id,))
    for table in ('quantity_reconciliations','quantity_movements'):
        c.execute('DELETE FROM '+table+' WHERE run_id IN (SELECT id FROM quantity_runs WHERE league_id=?)',(league_id,))
    for table in ('quantity_state','event_quantities','quantity_runs'):
        c.execute('DELETE FROM '+table+' WHERE league_id=?',(league_id,))
    # Include pending source records as well as those linked to transactions.
    c.execute('DELETE FROM guild_history_events WHERE league_name=? OR transaction_id IN (SELECT id FROM transactions WHERE league_id=?)',(name,league_id))
    for page in c.execute('SELECT id,payload_json FROM guild_history_pages').fetchall():
        body=redact_history(page['payload_json'],{name})
        if body==page['payload_json']:continue
        if not c.execute('SELECT 1 FROM guild_history_events WHERE page_id=?',(page['id'],)).fetchone():
            c.execute('DELETE FROM guild_history_pages WHERE id=?',(page['id'],))
        else:
            c.execute('UPDATE guild_history_pages SET payload_json=?,sha256=? WHERE id=?',(body,hashlib.sha256(body.encode()).hexdigest(),page['id']))
    identities={name,*(row[0] for row in c.execute("SELECT external_id FROM league_external_ids WHERE league_id=? AND provider='poe.ninja'",(league_id,)))}
    for row in c.execute('SELECT url FROM price_http_cache').fetchall():
        if set(parse_qs(urlsplit(row['url']).query).get('league',[])) & identities:
            c.execute('DELETE FROM price_http_cache WHERE url=?',(row['url'],))
    c.execute('DELETE FROM price_quotes WHERE snapshot_id IN (SELECT id FROM price_snapshots WHERE league_id=?)',(league_id,))
    for table in ('price_snapshots','price_aliases','transactions','revisions','archive_files','league_external_ids','league_policies'):
        c.execute('DELETE FROM '+table+' WHERE league_id=?',(league_id,))
    # Global guild scopes/cursors are shared; only remove league-specific scopes.
    scopes=[row[0] for row in c.execute("SELECT DISTINCT scope_key FROM jobs WHERE league_id=? AND kind!='history'",(league_id,))]
    c.execute('DELETE FROM automatic_attempts WHERE job_id IN (SELECT id FROM jobs WHERE league_id=?)',(league_id,))
    c.execute('DELETE FROM jobs WHERE league_id=?',(league_id,))
    for scope in scopes:
        c.execute('DELETE FROM automatic_attempts WHERE scope_key=?',(scope,))
        c.execute('DELETE FROM refresh_scopes WHERE scope_key=?',(scope,))
    c.execute('DELETE FROM leagues WHERE id=?',(league_id,))


def remember_deletion(c,league):
    rows=[r for r in deleted_leagues(c) if r['id']!=league['id']]
    rows.append({key:league[key] for key in ('id','game','realm','name')}|{'deleted_at':utc_now()})
    c.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(KEY,canonical(rows)))


def allow_readdition(c,league_id):
    league=c.execute('SELECT * FROM leagues WHERE id=?',(league_id,)).fetchone()
    rows=deleted_leagues(c)
    remaining=[r for r in rows if r['id']!=league_id and (r['game'],r['realm'],r['name'])!=(league['game'],league['realm'],league['name'])]
    if len(rows)==len(remaining):return False
    c.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(KEY,canonical(remaining)))
    return True
