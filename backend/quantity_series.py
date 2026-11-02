"""Bounded UTC movement series. The wire format has no chart-library options."""
from datetime import datetime, timedelta, timezone
import math

from flask import current_app, jsonify, request
from .browsing import ReadError, date_argument, number_argument, one_argument, stash_arguments
from .database import connect, require_schema
from .quantities import effective_settings
from .quantity_api import league_row, metadata
from .text_search import TextFilters


FILTER_ARGUMENTS = {'account', 'account_regex', 'account_case', 'account_word', 'stash', 'item',
                    'item_regex', 'item_case', 'item_word', 'from', 'to'}


def read_series(league_id):
    if set(request.args) - FILTER_ARGUMENTS - {'revision', 'projection_id', 'series_item', 'max_points'}:
        raise ReadError('unknown_parameter')
    limit = number_argument('max_points', 240, 24, 600)
    start, end = date_argument('from'), date_argument('to', end=True)
    if start and end and start >= end:
        raise ReadError('invalid_date_range')
    filters = TextFilters()
    stashes, item = stash_arguments(), one_argument('series_item')
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
        base = dict(league_id=league_id, projection=meta, timezone=settings['timezone'],
                    unit='item_count', items=[], item=item or None, points=[], bounds=None,
                    bucket_seconds=None, max_points=limit, unresolved_events=0, totals=dict(added=0, removed=0, net=0, inferred=0))
        if not run:
            return jsonify(base)
        conditions, args = ["m.run_id=?", "q.effective_action!='excluded'"], [run['id']]
        for field, column in [('account', 't.account'), ('item', 'm.item_name')]:
            if filters.values[field]:
                predicate, values = filters.predicate(field, column)
                conditions.append(predicate); args.extend(values)
        canonical_stashes = sorted({settings['stash_aliases'].get(name, name) for name in stashes})
        if canonical_stashes:
            conditions.append('q.stash IN (' + ','.join('?' for _ in canonical_stashes) + ')')
            args.extend(canonical_stashes)
        if start:
            conditions.append('t.occurred_at>=?'); args.append(start)
        if end:
            conditions.append('t.occurred_at<?'); args.append(end)
        common = (' FROM quantity_movements m JOIN event_quantities q ON q.run_id=m.run_id AND q.transaction_id=m.transaction_id '
                  'JOIN transactions t ON t.id=m.transaction_id WHERE ' + ' AND '.join(conditions))
        catalog = [row[0] for row in c.execute('SELECT m.item_name' + common +
                    ' GROUP BY m.item_name ORDER BY SUM(ABS(m.quantity_delta)) DESC,m.item_name LIMIT 50', args)]
        if not item and catalog:
            item = catalog[0]
        base.update(items=catalog, item=item or None)
        if not item:
            return jsonify(base)
        event_conditions = [condition.replace('m.run_id', 'q.run_id').replace('m.item_name', 'q.item_name') for condition in conditions]
        unknown_sql = ('SELECT COUNT(*) FROM event_quantities q JOIN transactions t ON t.id=q.transaction_id WHERE '
                       + ' AND '.join(event_conditions) + " AND q.item_name=? AND (q.effective_action='unknown' OR q.resolution_reason='invalid_quantity')")
        base['unresolved_events'] = c.execute(unknown_sql, [*args, item]).fetchone()[0]
        common += ' AND m.item_name=?'
        args.append(item)
        span = c.execute('SELECT MIN(t.occurred_at),MAX(t.occurred_at)' + common, args).fetchone()
        if not span[0]:
            return jsonify(base)
        # Whole UTC days, including zero-activity buckets; explicit end is exclusive.
        first = datetime.fromisoformat((start or span[0]).replace('Z', '+00:00')).replace(hour=0, minute=0, second=0, microsecond=0)
        last = datetime.fromisoformat(end.replace('Z', '+00:00')) if end else datetime.fromisoformat(span[1].replace('Z', '+00:00')).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        lower, upper = int(first.timestamp()), int(last.timestamp())
        duration = upper - lower
        candidates = [60, 300, 900, 3600, 21600, 86400, 604800, 2592000]
        bucket = next((step for step in candidates if math.ceil(duration / step) <= limit), max(1, math.ceil(duration / limit)))
        count = math.ceil(duration / bucket)
        sql = ('SELECT CAST((CAST(strftime(\'%s\',substr(t.occurred_at,1,19)||\'Z\') AS INTEGER)-?)/? AS INTEGER) AS bucket,'
               'SUM(CASE WHEN m.quantity_delta>0 THEN m.quantity_delta ELSE 0 END) AS added,'
               'SUM(CASE WHEN m.quantity_delta<0 THEN -m.quantity_delta ELSE 0 END) AS removed,'
               "SUM(CASE WHEN m.confidence='inferred' THEN ABS(m.quantity_delta) ELSE 0 END) AS inferred" + common + ' GROUP BY bucket')
        grouped = {row['bucket']: dict(row) for row in c.execute(sql, [lower, bucket, *args])}
        points = []
        for index in range(count):
            values = grouped.get(index, dict(added=0, removed=0, inferred=0))
            point = dict(timestamp=(lower + index * bucket) * 1000,
                         end=min(upper, lower + (index + 1) * bucket) * 1000,
                         added=values['added'], removed=values['removed'],
                         net=values['added'] - values['removed'], inferred=values['inferred'])
            points.append(point)
        base.update(points=points, bucket_seconds=bucket, bounds=dict(start=lower * 1000, end=upper * 1000),
                    totals={key: sum(point[key] for point in points) for key in ('added', 'removed', 'net', 'inferred')})
        return jsonify(base)
