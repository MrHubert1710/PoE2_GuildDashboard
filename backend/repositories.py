"""Read-only database diagnostics for phase 1. No transaction browsing yet."""
from .database import connect, require_schema, DatabaseError, SCHEMA_VERSION


def database_status(path):
    with connect(path, readonly=True) as connection:
        require_schema(connection)
        connection.execute('BEGIN')
        metadata = connection.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()
        if metadata is None:
            raise DatabaseError('Database identity is missing')
        instance = metadata[0]
        leagues = []
        for row in connection.execute('SELECT l.id,l.name,l.lifecycle,l.archived,l.monitored,l.history_complete,'
                                      'COUNT(t.id) AS transactions,MIN(t.occurred_at) AS oldest_at,'
                                      'MAX(t.occurred_at) AS newest_at FROM leagues l '
                                      'LEFT JOIN transactions t ON t.league_id=l.id GROUP BY l.id ORDER BY l.name'):
            league = dict(row)
            league['archived'] = bool(league['archived'])
            league['monitored'] = bool(league['monitored'])
            league['history_complete'] = (None if league['history_complete'] is None
                                           else bool(league['history_complete']))
            league['files'] = dict(connection.execute('SELECT kind,COUNT(*) FROM archive_files '
                                                     'WHERE league_id=? GROUP BY kind', (row['id'],)).fetchall())
            history = connection.execute("SELECT sha256 FROM archive_files WHERE league_id=? AND kind='history' ORDER BY id DESC LIMIT 1",
                                         (row['id'],)).fetchone()
            league['history_sha256'] = history[0] if history else None
            leagues.append(league)
        last_run = connection.execute('SELECT id,status,started_at,finished_at,inserted_count,duplicate_count,'
                                      'invalid_count,conflict_count FROM import_runs ORDER BY rowid DESC LIMIT 1').fetchone()
        last_completed = connection.execute("SELECT id FROM import_runs WHERE status='completed' ORDER BY rowid DESC LIMIT 1").fetchone()
        check = connection.execute('SELECT checked_at,transaction_count,last_completed_import_id,result '
                                   'FROM database_checks ORDER BY id DESC LIMIT 1').fetchone()
        check = dict(check) if check else None
        if check:
            check['current'] = check['last_completed_import_id'] == (last_completed[0] if last_completed else None)
            del check['last_completed_import_id']
        result = {'state': 'ready', 'schema_version': SCHEMA_VERSION, 'instance_id': instance,
                  'journal_mode': connection.execute('PRAGMA journal_mode').fetchone()[0],
                  'leagues': leagues, 'transactions': sum(league['transactions'] for league in leagues),
                  'last_import': dict(last_run) if last_run else None, 'integrity': check}
        connection.commit()
        return result
