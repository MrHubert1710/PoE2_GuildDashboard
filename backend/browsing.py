"""Phase 2 read-only APIs and isolated access to registered historical HTML."""
from datetime import date, datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
import sqlite3

from flask import Blueprint, Response, current_app, jsonify, request, g

from .database import connect, require_schema, DatabaseError


browser = Blueprint('browser', __name__)
SORTS = {'date': 't.occurred_at', 'account': 'casefold(t.account)',
         'stash': 'casefold(t.stash)', 'item': 'casefold(t.item)', 'action': 't.action'}


class ReadError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status


@browser.errorhandler(ReadError)
def read_error(error):
    return jsonify(error=error.code), error.status


@browser.errorhandler(sqlite3.Error)
@browser.errorhandler(DatabaseError)
def database_error(_error):
    if getattr(g, 'regex_error', None):
        return jsonify(error=g.regex_error), 400
    return jsonify(error='database_unavailable'), 503


@browser.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def revision(connection, league_id):
    instance = connection.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()
    if not instance:
        raise DatabaseError('Missing database identity')
    revisions = [row[0] for row in connection.execute(
        "SELECT id FROM revisions WHERE league_id=? AND kind='raw_import' ORDER BY id", (league_id,))]
    return instance[0] + ':' + hashlib.sha256('\n'.join(revisions).encode()).hexdigest()[:24]


def league_or_error(connection, league_id):
    league = connection.execute('SELECT id,name,game,realm,lifecycle,archived,history_complete '
                                'FROM leagues WHERE id=?', (league_id,)).fetchone()
    if not league:
        raise ReadError('league_not_found', 404)
    return league


def reports(connection, league_id):
    return [dict(row) for row in connection.execute(
        "SELECT id,archive_key AS name,sha256,bytes FROM archive_files "
        "WHERE league_id=? AND kind='report' ORDER BY archive_key,id DESC", (league_id,))]


@browser.get('/api/leagues')
def leagues():
    with connect(current_app.config['DATABASE_FILE'], readonly=True) as connection:
        require_schema(connection)
        connection.execute('BEGIN')
        result = []
        for row in connection.execute('SELECT l.id,l.name,l.game,l.realm,l.lifecycle,l.archived,l.history_complete,l.settings_json,'
                                      'COUNT(t.id) AS transactions,MIN(t.occurred_at) AS oldest_at,'
                                      'MAX(t.occurred_at) AS newest_at FROM leagues l '
                                      'LEFT JOIN transactions t ON t.league_id=l.id GROUP BY l.id ORDER BY l.name,l.id'):
            league = dict(row)
            league['archived'] = bool(league['archived'])
            league['history_complete'] = None if row['history_complete'] is None else bool(row['history_complete'])
            from .quantities import effective_settings, projection_hash, visible_stashes, settings_hash
            configured = effective_settings(row, connection)
            league['timezone'] = configured['timezone']
            league['hour_format'] = configured['hour_format']
            league['display_settings_hash'] = settings_hash(configured)
            league['quantity_settings_hash'] = projection_hash(row, connection)
            league.pop('settings_json', None)
            league['revision'] = revision(connection, row['id'])
            league['reports'] = reports(connection, row['id'])
            league['stashes'] = visible_stashes(connection, row['id'], configured)
            if configured['target_stashes'] is not None:
                names = league['stashes']
                placeholders = ','.join('?' for _ in names)
                coverage = connection.execute(
                    f'SELECT COUNT(*) AS transactions,MIN(occurred_at) AS oldest_at,MAX(occurred_at) AS newest_at '
                    f'FROM transactions WHERE league_id=? AND stash IN ({placeholders})', [row['id'], *names]).fetchone()
                league.update(dict(coverage))
            result.append(league)
        return jsonify(leagues=result)


def one_argument(name, default=''):
    values = request.args.getlist(name)
    if len(values) > 1:
        raise ReadError('duplicate_parameter')
    value = values[0] if values else default
    if len(value) > 200:
        raise ReadError('parameter_too_long')
    return value


def stash_arguments():
    values = request.args.getlist('stash')
    if len(values) > 100:
        raise ReadError('too_many_stashes')
    if any(len(value) > 200 for value in values):
        raise ReadError('parameter_too_long')
    return sorted({value.strip() for value in values if value.strip()})


def number_argument(name, default, minimum, maximum):
    value = one_argument(name, str(default))
    if not re.fullmatch(r'[0-9]+', value):
        raise ReadError('invalid_pagination')
    result = int(value)
    if not minimum <= result <= maximum:
        raise ReadError('invalid_pagination')
    return result


def date_argument(name, *, end=False, zone='UTC'):
    value = one_argument(name)
    if not value:
        return None
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Date format')
        day = date.fromisoformat(value)
        if end:
            day += timedelta(days=1)
        from .timezones import timezone_info
        return datetime(day.year, day.month, day.day, tzinfo=timezone_info(zone)).astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        raise ReadError('invalid_date') from None


@browser.get('/api/leagues/<league_id>/transactions')
def transactions(league_id):
    allowed = {'page', 'page_size', 'sort', 'direction', 'account', 'stash', 'item', 'from', 'to', 'revision', 'account_regex', 'item_regex', 'account_case', 'account_word', 'item_case', 'item_word'}
    if set(request.args) - allowed:
        raise ReadError('unknown_parameter')
    page = number_argument('page', 1, 1, 1000000)
    page_size = number_argument('page_size', 50, 1, 100)
    if page_size not in {25, 50, 100}:
        raise ReadError('invalid_pagination')
    sort, direction = one_argument('sort', 'date'), one_argument('direction', 'desc')
    if sort not in SORTS or direction not in {'asc', 'desc'}:
        raise ReadError('invalid_sort')
    start, end = date_argument('from'), date_argument('to', end=True)
    if start and end and start >= end:
        raise ReadError('invalid_date_range')
    from .text_search import TextFilters
    filters = TextFilters()
    conditions, values = ['t.league_id=?'], [league_id]
    stashes = stash_arguments()
    if stashes:
        conditions.append('t.stash IN (' + ','.join('?' for _ in stashes) + ')')
        values.extend(stashes)
    for field in ('account', 'item'):
        if filters.values[field]:
            predicate, arguments = filters.predicate(field, 't.' + field)
            conditions.append(predicate)
            values.extend(arguments)
    expected_revision = one_argument('revision')
    with connect(current_app.config['DATABASE_FILE'], readonly=True) as connection:
        require_schema(connection)
        connection.execute('BEGIN')
        connection.create_function('casefold', 1, lambda value: value.casefold(), deterministic=True)
        filters.bind(connection)
        league_or_error(connection, league_id)
        from .quantities import effective_settings, visible_stashes
        league = connection.execute('SELECT * FROM leagues WHERE id=?', (league_id,)).fetchone()
        configured = effective_settings(league, connection)
        start, end = date_argument('from', zone=configured['timezone']), date_argument('to', end=True, zone=configured['timezone'])
        if start:
            conditions.append('t.occurred_at>=?'); values.append(start)
        if end:
            conditions.append('t.occurred_at<?'); values.append(end)
        if configured['target_stashes'] is not None:
            names = visible_stashes(connection, league_id, configured)
            conditions.append('t.stash IN (' + ','.join('?' for _ in names) + ')')
            values.extend(names)
        current_revision = revision(connection, league_id)
        if expected_revision and current_revision != expected_revision:
            raise ReadError('revision_changed', 409)
        where = ' AND '.join(conditions)
        total = connection.execute('SELECT COUNT(*) FROM transactions t WHERE ' + where, values).fetchone()[0]
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        order = SORTS[sort] + ' ' + direction + ',t.id ' + direction
        rows = connection.execute(
            'SELECT t.id,t.external_id,t.occurred_at,t.account,t.action,t.stash,t.item,t.x,t.y '
            'FROM transactions t WHERE ' + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
            values + [page_size, (page - 1) * page_size]).fetchall()
        from .quantity_api import metadata
        from .quantities import current_run
        league = connection.execute('SELECT * FROM leagues WHERE id=?', (league_id,)).fetchone()
        meta, run = metadata(connection, league)
        result_rows = [dict(row) for row in rows]
        if run and rows:
            ids = [row['id'] for row in rows]
            placeholders = ','.join('?' for _ in ids)
            annotations = {r['transaction_id']: dict(r) for r in connection.execute(
                f'SELECT * FROM event_quantities WHERE run_id=? AND transaction_id IN ({placeholders})', [run['id'], *ids])}
            movements = {}
            for movement in connection.execute(f'SELECT transaction_id,item_name,quantity_delta,confidence FROM quantity_movements WHERE run_id=? AND transaction_id IN ({placeholders}) ORDER BY transaction_id,sequence', [run['id'], *ids]):
                movements.setdefault(movement['transaction_id'], []).append(dict(movement))
            for row in result_rows:
                annotation = annotations.get(row['id'])
                if annotation:
                    annotation.pop('run_id', None)
                    annotation.pop('transaction_id', None)
                    annotation['movements'] = movements.get(row['id'], [])
                row['quantity'] = annotation
        return jsonify(league_id=league_id, revision=current_revision, projection=meta, page=page, page_size=page_size,
                       total=total, pages=pages, sort=sort, direction=direction,
                       rows=result_rows)


@browser.get('/archives/<int:archive_id>')
def archive(archive_id):
    with connect(current_app.config['DATABASE_FILE'], readonly=True) as connection:
        require_schema(connection)
        entry = connection.execute("SELECT relative_path,sha256 FROM archive_files WHERE id=? AND kind='report'",
                                   (archive_id,)).fetchone()
    if not entry:
        raise ReadError('archive_not_found', 404)
    root = Path(current_app.config['DATA_DIRECTORY']).resolve()
    path = (root / entry['relative_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ReadError('archive_unavailable', 404)
    try:
        content = path.read_bytes()
    except OSError:
        raise ReadError('archive_unavailable', 404) from None
    if hashlib.sha256(content).hexdigest() != entry['sha256']:
        raise ReadError('archive_checksum_mismatch', 409)
    response = Response(content, mimetype='text/html')
    response.headers['Content-Security-Policy'] = (
        "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response
