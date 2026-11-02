"""Read quantity projections and edit explicit per-league settings."""
import json
import sqlite3
from flask import Blueprint, current_app, jsonify, request
from .browsing import ReadError, read_error, database_error, one_argument, number_argument, date_argument, revision, stash_arguments
from .database import connect, require_schema, DatabaseError, utc_now
from .quantities import current_run, effective_settings, settings_hash, validate_settings, ALGORITHM, guild_defaults, projection_hash
from .refresh_api import queue
from .text_search import TextFilters

quantities = Blueprint('quantities', __name__)
quantities.register_error_handler(ReadError, read_error)
quantities.register_error_handler(sqlite3.Error, database_error)
quantities.register_error_handler(DatabaseError, database_error)


@quantities.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def league_row(c, league_id):
    league = c.execute('SELECT * FROM leagues WHERE id=?', (league_id,)).fetchone()
    if not league:
        raise ReadError('league_not_found', 404)
    return league


def metadata(c, league):
    expected = revision(c, league['id'])
    run = current_run(c, league, expected)
    previous = c.execute('SELECT created_at FROM quantity_runs WHERE league_id=? ORDER BY created_at DESC LIMIT 1', (league['id'],)).fetchone()
    return {'state': 'ready' if run else 'stale' if previous else 'missing',
            'id': run['id'] if run else None, 'input_revision': expected,
            'algorithm_version': ALGORITHM, 'settings_hash': projection_hash(league, c),
            'initial_state': 'empty' if league['history_complete'] else 'unknown',
            'generated_at': run['created_at'] if run else None,
            'previous_generated_at': previous['created_at'] if previous else None}, run


@quantities.route('/api/leagues/<league_id>/quantity-settings', methods=['GET', 'PUT'])
def settings(league_id):
    if request.method == 'PUT':
        if request.headers.get('Origin') and request.headers['Origin'].rstrip('/') != request.host_url.rstrip('/'):
            raise ReadError('origin_rejected', 403)
        if not request.is_json:
            raise ReadError('json_required', 415)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {'expected_hash', 'settings', 'scope', 'expected_guild_hash'} or not {'expected_hash', 'settings'} <= set(payload) or not isinstance(payload['expected_hash'], str):
            raise ReadError('invalid_settings')
        try:
            updated = validate_settings(payload['settings'])
        except ValueError as error:
            raise ReadError(str(error)) from None
        scope = payload.get('scope', 'league')
        if not isinstance(scope, str) or scope not in {'league', 'guild', 'inherit'}:
            raise ReadError('invalid_settings')
        with queue().transaction() as c:
            league = league_row(c, league_id)
            if payload['expected_hash'] != settings_hash(effective_settings(league, c)):
                raise ReadError('settings_changed', 409)
            original = json.loads(league['settings_json'])
            if scope == 'guild':
                source, defaults = guild_defaults(c, league_id)
                if source is None:
                    raise ReadError('ambiguous_guild', 409)
                if payload.get('expected_guild_hash') != settings_hash(defaults):
                    raise ReadError('settings_changed', 409)
                c.execute('INSERT INTO guild_quantity_defaults VALUES (?,?,?) ON CONFLICT(source_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at',
                          (source, json.dumps(updated, ensure_ascii=False, sort_keys=True), utc_now()))
                original.pop('quantity_settings', None)
            elif scope == 'inherit':
                original.pop('quantity_settings', None)
            else:
                original['quantity_settings'] = updated
            c.execute('UPDATE leagues SET settings_json=? WHERE id=?', (json.dumps(original, ensure_ascii=False, sort_keys=True), league_id))
            updated = effective_settings(league_row(c, league_id), c)
        return jsonify(settings=updated, settings_hash=settings_hash(updated))
    with connect(current_app.config['DATABASE_FILE'], readonly=True) as c:
        require_schema(c)
        c.execute('BEGIN')
        league = league_row(c, league_id)
        configured = effective_settings(league, c)
        stashes = [r[0] for r in c.execute('SELECT DISTINCT stash FROM transactions WHERE league_id=? ORDER BY stash', (league_id,))]
        source, defaults = guild_defaults(c, league_id)
        return jsonify(guild_available=source is not None, guild_settings=defaults, guild_hash=settings_hash(defaults), settings=configured, settings_hash=settings_hash(configured), stashes=stashes,
                       provenance='user' if 'quantity_settings' in json.loads(league['settings_json']) else 'guild_defaults',
                       legacy_settings=json.loads(league['settings_json']))


@quantities.get('/api/leagues/<league_id>/quantities')
def report(league_id):
    allowed = {'view', 'account', 'stash', 'item', 'from', 'to', 'page', 'page_size', 'revision', 'projection_id', 'account_regex', 'item_regex', 'account_case', 'account_word', 'item_case', 'item_word'}
    if set(request.args) - allowed:
        raise ReadError('unknown_parameter')
    view = one_argument('view', 'summary')
    if view not in {'summary', 'players', 'stashes', 'state'}:
        raise ReadError('invalid_view')
    page, size = number_argument('page', 1, 1, 1000000), number_argument('page_size', 25, 1, 100)
    if size not in {25, 50, 100}:
        raise ReadError('invalid_pagination')
    start, end = date_argument('from'), date_argument('to', end=True)
    if start and end and start >= end:
        raise ReadError('invalid_date_range')
    filters = TextFilters()
    account, item = filters.values['account'], filters.values['item']
    stashes = stash_arguments()
    if view == 'state' and (start or end or account):
        raise ReadError('state_filter_not_supported')
    with connect(current_app.config['DATABASE_FILE'], readonly=True) as c:
        require_schema(c)
        c.execute('BEGIN')
        c.create_function('casefold', 1, lambda value: value.casefold(), deterministic=True)
        filters.bind(c)
        league = league_row(c, league_id)
        meta, run = metadata(c, league)
        expected, pinned = one_argument('revision'), one_argument('projection_id')
        if expected and expected != meta['input_revision']:
            raise ReadError('revision_changed', 409)
        if pinned and pinned != meta['id']:
            raise ReadError('projection_changed', 409)
        settings = effective_settings(league, c)
        if not run:
            return jsonify(league_id=league_id, projection=meta, settings=settings, rows=[], total=0, pages=1, page=1, stats=None)
        conditions, values = ['q.run_id=?'], [run['id']]
        if account:
            predicate, arguments = filters.predicate('account', 't.account')
            conditions.append(predicate); values.extend(arguments)
        canonical_stashes = sorted({settings['stash_aliases'].get(stash, stash) for stash in stashes})
        if canonical_stashes:
            conditions.append('q.stash IN (' + ','.join('?' for _ in canonical_stashes) + ')'); values.extend(canonical_stashes)
        if start:
            conditions.append('t.occurred_at>=?'); values.append(start)
        if end:
            conditions.append('t.occurred_at<?'); values.append(end)
        common = ' AND '.join(conditions)
        event_item = ''
        event_values = list(values)
        if item:
            event_predicate, event_arguments = filters.predicate('item', 'q.item_name')
            movement_predicate, movement_arguments = filters.predicate('item', 'mm.item_name')
            event_item = f' AND ({event_predicate} OR EXISTS(SELECT 1 FROM quantity_movements mm WHERE mm.run_id=q.run_id AND mm.transaction_id=q.transaction_id AND {movement_predicate}))'
            event_values += event_arguments + movement_arguments
        stats = dict(c.execute('SELECT COUNT(*) AS events,COALESCE(SUM(q.effective_action=\'unknown\'),0) AS unknown,'
                               'COALESCE(SUM(q.confidence=\'inferred\'),0) AS inferred,COALESCE(SUM(q.effective_action=\'excluded\'),0) AS excluded,'
                               "COALESCE(SUM(q.resolution_reason IN ('state_conflict','invalid_quantity','ambiguous_order')),0) AS warnings "
                               'FROM event_quantities q JOIN transactions t ON t.id=q.transaction_id WHERE ' + common + event_item, event_values).fetchone())
        if view == 'state':
            where, args = ['s.run_id=?', '(s.quantity>0 OR s.quantity IS NULL)'], [run['id']]
            if canonical_stashes:
                where.append('s.stash IN (' + ','.join('?' for _ in canonical_stashes) + ')'); args.extend(canonical_stashes)
            if item:
                predicate, arguments = filters.predicate('item', 's.item_name')
                where.append(predicate); args.extend(arguments)
            sql = ('SELECT s.source_id,s.stash,s.x,s.y,s.item_name,s.quantity,t.occurred_at,t.account '
                   'FROM quantity_state s JOIN transactions t ON t.id=s.transaction_id WHERE ' + ' AND '.join(where))
            order = 'stash,source_id,y,x'
        else:
            groups = {'summary': 'm.item_name', 'players': 't.account,m.item_name', 'stashes': 'q.stash,m.item_name'}[view]
            selected = 'm.item_name' + (',t.account' if view == 'players' else ',q.stash' if view == 'stashes' else '')
            where, args = common, list(values)
            if item:
                predicate, arguments = filters.predicate('item', 'm.item_name')
                where += ' AND ' + predicate; args.extend(arguments)
            sql = (f'SELECT {selected},SUM(CASE WHEN m.quantity_delta>0 THEN m.quantity_delta ELSE 0 END) AS added,'
                   'SUM(CASE WHEN m.quantity_delta<0 THEN -m.quantity_delta ELSE 0 END) AS removed,SUM(m.quantity_delta) AS net,'
                   "SUM(CASE WHEN m.confidence='inferred' THEN ABS(m.quantity_delta) ELSE 0 END) AS inferred_quantity,"
                   'COUNT(*) AS movements FROM quantity_movements m JOIN event_quantities q ON q.run_id=m.run_id AND q.transaction_id=m.transaction_id '
                   'JOIN transactions t ON t.id=q.transaction_id WHERE ' + where + ' GROUP BY ' + groups)
            order = 'casefold(account),item_name' if view == 'players' else 'stash,item_name' if view == 'stashes' else 'item_name'
        total = c.execute('SELECT COUNT(*) FROM (' + sql + ')', args).fetchone()[0]
        pages = max(1, (total + size - 1) // size)
        page = min(page, pages)
        rows = [dict(row) for row in c.execute('SELECT * FROM (' + sql + ') ORDER BY ' + order + ' LIMIT ? OFFSET ?', args + [size, (page-1)*size])]
        return jsonify(league_id=league_id, projection=meta, settings=settings, rows=rows, total=total, pages=pages, page=page, stats=stats,
                       history_complete=bool(league['history_complete']))
