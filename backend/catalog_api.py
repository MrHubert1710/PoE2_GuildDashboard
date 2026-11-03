"""Administrator-only discovery, explicit league creation and source connection."""
import json,sqlite3,uuid
from flask import Blueprint,current_app,jsonify,request
from .database import connect,require_schema,utc_now,DatabaseError
from .browsing import ReadError,read_error,database_error
from .archive_import import canonical
from .league_catalog import text,matched_league,apply_observed_status,ggg_configuration
from .ggg_connection import GGGConnectionStore,ConnectionError
from .refresh_api import queue
from .jobs import JobRejected
from .league_deletion import purge_league,remember_deletion,allow_readdition

catalog=Blueprint('catalog',__name__)
catalog.register_error_handler(ReadError,read_error)
catalog.register_error_handler(DatabaseError,database_error)
catalog.register_error_handler(sqlite3.Error,database_error)


def connection_store():return GGGConnectionStore(current_app.config['GGG_CONNECTION_FILE'])


def policy(c,league):
    row=c.execute('SELECT * FROM league_policies WHERE league_id=?',(league['id'],)).fetchone()
    return dict(monitored=bool(league['monitored']),archived=bool(league['archived']),lifecycle_override=row['lifecycle_override'] if row else None,version=row['version'] if row else 0)


@catalog.get('/api/league-catalog')
def status():
    q=queue()
    with connect(current_app.config['DATABASE_FILE'],readonly=True) as c:
        require_schema(c);c.execute('BEGIN');rows=[]
        for raw in c.execute('SELECT * FROM league_catalog_entries ORDER BY name,provider,external_id'):
            row=dict(raw);league=matched_league(c,row['provider'],row)
            row.pop('payload_json');row['variant']=json.loads(row.pop('variant_json'));row['present']=bool(row['present']);row['league_id']=league['id'] if league else None
            rows.append(row)
        local=[]
        for league in c.execute('SELECT * FROM leagues ORDER BY name,id'):
            local.append(dict(id=league['id'],name=league['name'],lifecycle=league['lifecycle'],observed_lifecycle=league['observed_lifecycle'],observed_source=league['observed_source'],observed_at=league['observed_at'],**policy(c,league)))
        sources=[dict(r) for r in c.execute('SELECT * FROM league_catalog_sources ORDER BY provider')]
        job=c.execute('SELECT id,state,error_code,finished_at,result_json FROM jobs WHERE scope_key=? ORDER BY rowid DESC LIMIT 1',(q.scope(None,'league_catalog'),)).fetchone()
        return jsonify(entries=rows,leagues=local,sources=sources,available=q.catalog_available,ggg_configured=bool(ggg_configuration()),job=dict(job) if job else None)


@catalog.post('/api/league-catalog/refresh')
def refresh():
    if not request.is_json or request.get_json(silent=True)!={}:raise ReadError('invalid_catalog_request')
    result=queue().enqueue(None,'league_catalog','manual')
    return jsonify(result),202 if result['outcome'] in ('queued','coalesced') else 200


@catalog.post('/api/league-catalog/leagues')
def add_league():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or set(payload) not in ({'provider','external_id'},{'name'}):raise ReadError('invalid_catalog_request')
    with connect(current_app.config['DATABASE_FILE']) as c:
        require_schema(c);c.execute('BEGIN IMMEDIATE');entry=None
        if 'provider' in payload:
            if payload['provider'] not in ('ggg','poe.ninja') or not isinstance(payload['external_id'],str):raise ReadError('invalid_catalog_request')
            entry=c.execute('SELECT * FROM league_catalog_entries WHERE provider=? AND external_id=? AND game=\'poe2\' AND realm=\'pc\'',(payload['provider'],payload['external_id'])).fetchone()
            if not entry:raise ReadError('catalog_entry_not_found',404)
            name=entry['name']
        else:
            try:name=text(payload['name'])
            except ValueError:raise ReadError('invalid_catalog_request') from None
        league_id=str(uuid.uuid5(uuid.NAMESPACE_URL,canonical(['poe2','pc',name])))
        existing=(matched_league(c,entry['provider'],entry) if entry else None) or c.execute("SELECT * FROM leagues WHERE game='poe2' AND realm='pc' AND name=?",(name,)).fetchone()
        if existing:league_id=existing['id']
        else:
            observed=entry['lifecycle'] if entry and entry['provider']=='ggg' else 'unknown'
            c.execute("INSERT INTO leagues(id,game,realm,name,lifecycle,observed_lifecycle,archived,monitored,settings_provenance,variant_json) VALUES(?,'poe2','pc',?,?,?,0,1,'admin_catalog',?)",(league_id,name,observed,observed,entry['variant_json'] if entry else '{}'))
        for candidate in c.execute("SELECT * FROM league_catalog_entries WHERE game='poe2' AND realm='pc' AND name=?",(name,)).fetchall():
            c.execute('INSERT OR IGNORE INTO league_external_ids VALUES(?,?,?)',(league_id,candidate['provider'],candidate['external_id']))
            if candidate['provider']=='ggg' and candidate['lifecycle']!='unknown':c.execute("UPDATE leagues SET observed_lifecycle=?,observed_source='ggg',observed_at=? WHERE id=?",(candidate['lifecycle'],candidate['last_seen'],league_id))
        apply_observed_status(c,league_id)
        if allow_readdition(c,league_id):
            # Explicit re-addition needs a full history pass, not only the overlap.
            from .ggg_history import RESOURCE
            c.execute('DELETE FROM source_cursors WHERE resource=?',(RESOURCE,))
        c.commit()
    # Pending guild entries may already contain this league's history.
    result=queue().enqueue(league_id,'history','manual')
    return jsonify(league_id=league_id,added=not bool(existing),history=result),200 if existing else 201


@catalog.put('/api/league-catalog/leagues/<league_id>')
def update_policy(league_id):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or set(payload)!={'monitored','archived','lifecycle_override','version'} or type(payload['monitored']) is not bool or type(payload['archived']) is not bool or type(payload['version']) is not int or payload['lifecycle_override'] not in (None,'active','ended','unknown'):raise ReadError('invalid_catalog_request')
    with connect(current_app.config['DATABASE_FILE']) as c:
        require_schema(c);c.execute('BEGIN IMMEDIATE');league=c.execute('SELECT * FROM leagues WHERE id=?',(league_id,)).fetchone()
        if not league:raise ReadError('league_not_found',404)
        if policy(c,league)['version']!=payload['version']:raise ReadError('catalog_policy_changed',409)
        c.execute('UPDATE leagues SET monitored=?,archived=? WHERE id=?',(int(payload['monitored']),int(payload['archived']),league_id))
        c.execute('INSERT OR REPLACE INTO league_policies VALUES(?,?,?,?)',(league_id,payload['lifecycle_override'],payload['version']+1,utc_now()))
        apply_observed_status(c,league_id);c.commit()
    return jsonify(saved=True)


@catalog.delete('/api/league-catalog/leagues/<league_id>')
def delete_league(league_id):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or set(payload)!={'name','version'} or type(payload['version']) is not int:
        raise ReadError('invalid_catalog_request')
    with connect(current_app.config['DATABASE_FILE']) as c:
        require_schema(c);c.execute('BEGIN IMMEDIATE')
        league=c.execute('SELECT * FROM leagues WHERE id=?',(league_id,)).fetchone()
        if not league:raise ReadError('league_not_found',404)
        if payload['name']!=league['name'] or payload['version']!=policy(c,league)['version']:
            raise ReadError('catalog_policy_changed',409)
        # A staged history publication could otherwise restore deleted source facts.
        if c.execute("SELECT 1 FROM jobs WHERE state='running' AND (league_id=? OR kind='history')",(league_id,)).fetchone():
            raise ReadError('league_busy',409)
        remember_deletion(c,league);purge_league(c,league);c.commit()
    return jsonify(deleted=True,league_id=league_id)


@catalog.get('/api/ggg-connection')
def get_connection():
    with connect(current_app.config['DATABASE_FILE'],readonly=True) as c:
        require_schema(c)
        sources=[dict(row) for row in c.execute('SELECT id,source_key,owner_reference FROM sources ORDER BY id')]
        pending=c.execute('SELECT league_name,count(*) AS events FROM guild_history_events WHERE transaction_id IS NULL GROUP BY league_name ORDER BY league_name').fetchall()
    return jsonify(connection=connection_store().public(),sources=sources,pending=[dict(r) for r in pending])


@catalog.put('/api/ggg-connection')
def put_connection():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or set(payload)!={'guild_id','session_id','enabled','clear_session','revision','source_id'}:raise ReadError('invalid_connection')
    store=connection_store()
    with connect(current_app.config['DATABASE_FILE']) as c:
        require_schema(c);c.execute('BEGIN IMMEDIATE');old=store.get()
        if payload['revision']!=old['revision']:raise ReadError('connection_changed',409)
        guild=payload['guild_id']
        # Validate before any source binding or secret write.
        import re
        if not isinstance(guild,str) or not re.fullmatch('[1-9][0-9]{0,19}',guild):raise ReadError('invalid_guild_id')
        source_id=payload['source_id'] if payload['source_id'] is not None else old['source_id']
        if source_id is not None:
            if type(source_id) is not int:raise ReadError('invalid_connection')
            source=c.execute('SELECT * FROM sources WHERE id=?',(source_id,)).fetchone()
            if not source:raise ReadError('invalid_connection')
            if source['owner_reference'] not in (None,'',guild):raise ReadError('guild_binding_conflict',409)
        else:
            candidates=c.execute('SELECT * FROM sources').fetchall()
            if len(candidates)==1 and candidates[0]['owner_reference'] in (None,'',guild):source_id=candidates[0]['id']
            elif candidates:raise ReadError('guild_archive_required')
            else:source_id=c.execute('INSERT INTO sources(source_key,provider,owner_reference,created_at) VALUES(?,?,?,?)',('ggg-guild-'+guild,'ggg-session',guild,utc_now())).lastrowid
        try:public=store.save(guild,payload['session_id'],source_id,payload['enabled'],payload['clear_session'])
        except ConnectionError as error:raise ReadError(str(error)) from None
        c.execute('UPDATE sources SET owner_reference=? WHERE id=?',(guild,source_id));c.commit()
    return jsonify(connection=public)
