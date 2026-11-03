"""Retain fetched source facts and admin-added leagues during an offline rebuild."""
from .database import DatabaseError


def preserve(old,fresh):
    if not old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='league_catalog_entries'").fetchone():return
    from .league_deletion import KEY,deleted_leagues,purge_league
    from .archive_import import canonical
    deleted=deleted_leagues(old)
    for entry in deleted:
        league=fresh.execute('SELECT * FROM leagues WHERE id=?',(entry['id'],)).fetchone()
        if league:purge_league(fresh,league)
    if deleted:fresh.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(KEY,canonical(deleted)))
    def insert(table,row,replace=False):
        values=dict(row);columns=','.join(values)
        fresh.execute(('INSERT OR REPLACE' if replace else 'INSERT OR IGNORE')+' INTO '+table+'('+columns+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values()))
    source_map={}
    for row in old.execute('SELECT * FROM sources ORDER BY id'):
        source=fresh.execute('SELECT id FROM sources WHERE source_key=?',(row['source_key'],)).fetchone()
        if not source:
            if fresh.execute('SELECT 1 FROM sources WHERE id=?',(row['id'],)).fetchone():raise DatabaseError('Rebuild would change a guild source identity; restore a full database backup instead')
            insert('sources',row);source_id=row['id']
        else:
            source_id=source[0]
            if source_id!=row['id']:raise DatabaseError('Rebuild would change a guild source identity; restore a full database backup instead')
            fresh.execute('UPDATE sources SET owner_reference=? WHERE id=?',(row['owner_reference'],source_id))
        source_map[row['id']]=source_id
    has_history=bool(old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='guild_history_pages'").fetchone())
    api_leagues={r[0] for r in old.execute("SELECT DISTINCT league_id FROM transactions WHERE normalization_version='ggg-history-v1'")} if has_history else set()
    policy_leagues={r[0] for r in old.execute('SELECT league_id FROM league_policies')}
    for row in old.execute('SELECT * FROM leagues'):
        exists=fresh.execute('SELECT 1 FROM leagues WHERE id=?',(row['id'],)).fetchone()
        if not exists:
            if row['settings_provenance']=='admin_catalog' or row['id'] in api_leagues:insert('leagues',row)
            elif row['id'] in policy_leagues:raise DatabaseError('Rebuild would discard configured league data; retain its archive or restore a full backup')
        else:
            columns=[key for key in ('monitored','observed_lifecycle','observed_source','observed_at','variant_json') if key in row.keys()]
            fresh.execute('UPDATE leagues SET '+','.join(key+'=?' for key in columns)+' WHERE id=?',(*[row[key] for key in columns],row['id']))
            override=old.execute('SELECT lifecycle_override FROM league_policies WHERE league_id=?',(row['id'],)).fetchone()
            state=override[0] if override and override[0] is not None else row['observed_lifecycle']
            fresh.execute('UPDATE leagues SET lifecycle=?,archived=? WHERE id=?',(state,row['archived'],row['id']))
    known={r[0] for r in fresh.execute('SELECT id FROM leagues')}
    for row in old.execute('SELECT * FROM league_external_ids'):
        if row['league_id'] in known:insert('league_external_ids',row)
    for table in ('catalog_observations','league_catalog_entries','league_catalog_sources','league_catalog_http_cache','league_policies','guild_quantity_defaults'):
        for row in old.execute('SELECT * FROM '+table):insert(table,row,replace=True)
    from .league_catalog import apply_observed_status
    for league_id in known:apply_observed_status(fresh,league_id)
    if not has_history:return
    imports={row[0] for row in old.execute('SELECT DISTINCT import_id FROM guild_history_pages')}
    for run in imports:insert('import_runs',old.execute('SELECT * FROM import_runs WHERE id=?',(run,)).fetchone())
    for row in old.execute("SELECT * FROM transactions WHERE normalization_version='ggg-history-v1' ORDER BY id"):
        existing=fresh.execute('SELECT * FROM transactions WHERE source_id=? AND league_id=? AND external_id=?',(row['source_id'],row['league_id'],row['external_id'])).fetchone()
        if existing:
            if existing['normalized_sha256']!=row['normalized_sha256']:raise DatabaseError('Rebuild conflicts with fetched guild history')
        else:
            values=dict(row);values.pop('id');insert('transactions',values)
    for row in old.execute("SELECT * FROM revisions WHERE import_id IN (SELECT DISTINCT import_id FROM guild_history_pages)"):insert('revisions',row)
    for row in old.execute('SELECT * FROM guild_history_pages'):insert('guild_history_pages',row)
    for row in old.execute('SELECT * FROM guild_history_events'):
        values=dict(row)
        if row['transaction_id'] is not None:
            transaction=old.execute('SELECT source_id,league_id,external_id FROM transactions WHERE id=?',(row['transaction_id'],)).fetchone()
            new=fresh.execute('SELECT id FROM transactions WHERE source_id=? AND league_id=? AND external_id=?',tuple(transaction)).fetchone()
            if not new:raise DatabaseError('Rebuild would lose a fetched guild entry')
            values['transaction_id']=new[0]
        insert('guild_history_events',values)
    for row in old.execute('SELECT * FROM source_cursors'):insert('source_cursors',row,replace=True)
