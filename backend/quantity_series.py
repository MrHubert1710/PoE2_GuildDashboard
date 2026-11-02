"""Cumulative movement balances with viewport-aware, extrema-preserving sampling."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import math
import re

from flask import current_app, jsonify, request
from .browsing import ReadError, date_argument, number_argument, one_argument, stash_arguments
from .database import connect, require_schema
from .quantities import effective_settings
from .quantity_api import league_row, metadata
from .text_search import TextFilters

FILTER_ARGUMENTS = {'account', 'account_regex', 'account_case', 'account_word', 'stash', 'item',
                    'item_regex', 'item_case', 'item_word', 'from', 'to'}


def stamp(value):
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)


def viewport_argument(name):
    value = one_argument(name)
    if not value:
        return None
    if not re.fullmatch(r'-?\d{1,15}', value) or abs(int(value)) > 8640000000000000:
        raise ReadError('invalid_viewport')
    return int(value)


def sample_extrema(points, limit):
    """Keep first/min/max/last in each time bin, in original event order."""
    if len(points) <= limit:
        return points, None
    bins = max(1, (limit - 2) // 4)
    width = max(1, points[-1]['timestamp'] - points[0]['timestamp'])
    groups = defaultdict(list)
    for index in range(1, len(points) - 1):
        bucket = min(bins - 1, (points[index]['timestamp'] - points[0]['timestamp']) * bins // width)
        groups[bucket].append(index)
    keep = {0, len(points) - 1}
    for indices in groups.values():
        keep.update((indices[0], min(indices,key=lambda i: points[i]['balance']),
                     max(indices,key=lambda i: points[i]['balance']), indices[-1]))
    return [points[index] for index in sorted(keep)], math.ceil(width / bins)


def read_series(league_id):
    if set(request.args) - FILTER_ARGUMENTS - {'revision', 'projection_id', 'series_item', 'max_points', 'view', 'window_start', 'window_end'}:
        raise ReadError('unknown_parameter')
    limit = number_argument('max_points', 240, 24, 600)
    view = one_argument('view','summary')
    if view not in {'summary','players','stashes'}:
        raise ReadError('invalid_view')
    lower, upper = viewport_argument('window_start'), viewport_argument('window_end')
    if (lower is None) != (upper is None) or (lower is not None and lower >= upper):
        raise ReadError('invalid_viewport')
    filters = TextFilters()
    stashes, item = stash_arguments(), one_argument('series_item')
    with connect(current_app.config['DATABASE_FILE'], readonly=True) as c:
        require_schema(c); c.execute('BEGIN')
        c.create_function('casefold',1,lambda value: value.casefold(),deterministic=True)
        filters.bind(c)
        league=league_row(c,league_id); meta,run=metadata(c,league)
        expected,pinned=one_argument('revision'),one_argument('projection_id')
        if expected and expected!=meta['input_revision']: raise ReadError('revision_changed',409)
        if pinned and pinned!=meta['id']: raise ReadError('projection_changed',409)
        settings=effective_settings(league,c)
        start,end=date_argument('from',zone=settings['timezone']),date_argument('to',end=True,zone=settings['timezone'])
        if start and end and start>=end: raise ReadError('invalid_date_range')
        base=dict(league_id=league_id,projection=meta,timezone=settings['timezone'],view=view,unit='item_count',
                  items=[],item=item or None,series=[],bounds=None,window=None,resolution_ms=None,max_points=limit,
                  sampled=False,unresolved_events=0,series_truncated=False,totals=dict(added=0,removed=0,net=0,inferred=0))
        if not run:return jsonify(base)
        conditions,args=["m.run_id=?","q.effective_action!='excluded'"],[run['id']]
        for field,column in [('account','t.account'),('item','m.item_name')]:
            if filters.values[field]:
                predicate,values=filters.predicate(field,column);conditions.append(predicate);args.extend(values)
        names=sorted({settings['stash_aliases'].get(name,name) for name in stashes})
        if names:
            conditions.append('q.stash IN ('+','.join('?' for _ in names)+')');args.extend(names)
        # Read preceding movements too: a date/viewport filter must not reset the balance.
        if end:conditions.append('t.occurred_at<?');args.append(end)
        common=(' FROM quantity_movements m JOIN event_quantities q ON q.run_id=m.run_id AND q.transaction_id=m.transaction_id '
                'JOIN transactions t ON t.id=m.transaction_id WHERE '+' AND '.join(conditions))
        catalog=[row[0] for row in c.execute('SELECT m.item_name'+common+' GROUP BY m.item_name ORDER BY SUM(ABS(m.quantity_delta)) DESC,m.item_name LIMIT 50',args)]
        item=item or (catalog[0] if catalog else None);base.update(items=catalog,item=item)
        if not item:return jsonify(base)
        event_conditions=[value.replace('m.run_id','q.run_id').replace('m.item_name','q.item_name') for value in conditions]
        extra,extra_args=('',[]) if not start else (' AND t.occurred_at>=?',[start])
        unknown_sql=('SELECT COUNT(*) FROM event_quantities q JOIN transactions t ON t.id=q.transaction_id WHERE '+' AND '.join(event_conditions)+
                     " AND q.item_name=? AND (q.effective_action='unknown' OR q.resolution_reason='invalid_quantity')"+extra)
        base['unresolved_events']=c.execute(unknown_sql,[*args,item,*extra_args]).fetchone()[0]
        rows=[dict(row) for row in c.execute('SELECT t.id,t.external_id,t.occurred_at,t.account,q.stash,m.sequence,m.quantity_delta,m.confidence'+common+' AND m.item_name=?',[*args,item])]
        if not rows:return jsonify(base)
        def order(row):
            external=row['external_id']; numeric=external.isascii() and external.isdigit()
            return row['occurred_at'],0 if numeric else 1,int(external) if numeric else external,row['id'],row['sequence']
        rows.sort(key=order)
        for row in rows:row['timestamp']=stamp(row['occurred_at'])
        first=stamp(start) if start else rows[0]['timestamp']-1
        last=stamp(end) if end else rows[-1]['timestamp']+1
        if last<=first:last=first+1
        domain=dict(start=first,end=last)
        low=max(first,lower) if lower is not None else first
        high=min(last,upper) if upper is not None else last
        if low>=high:low,high=first,last
        grouped=defaultdict(list)
        for row in rows:
            group=row['account'] if view=='players' else row['stash'] if view=='stashes' else 'summary'
            grouped[group].append(row)
            if first<=row['timestamp']<last:
                amount=row['quantity_delta'];base['totals']['added' if amount>0 else 'removed']+=abs(amount)
                base['totals']['net']+=amount
                if row['confidence']=='inferred':base['totals']['inferred']+=abs(amount)
        ranked=sorted(grouped,key=lambda group:(-sum(abs(row['quantity_delta']) for row in grouped[group]),group))
        base['series_truncated']=len(ranked)>100
        ranked=ranked[:100]
        point_limit=min(limit,max(24,6000//max(1,len(ranked))))
        output=[];resolution=None;sampled=False
        for name in ranked:
            opening=sum(row['quantity_delta'] for row in grouped[name] if row['timestamp']<low)
            balance=opening;points=[dict(timestamp=low,balance=balance)]
            for row in grouped[name]:
                if low<=row['timestamp']<high:
                    balance+=row['quantity_delta'];points.append(dict(timestamp=row['timestamp'],balance=balance))
            points.append(dict(timestamp=high,balance=balance))
            # Navigator always covers the full domain, independently of the detail window.
            full_balance=sum(row['quantity_delta'] for row in grouped[name] if row['timestamp']<first)
            full_points=[dict(timestamp=first,balance=full_balance)]
            for row in grouped[name]:
                if first<=row['timestamp']<last:
                    full_balance+=row['quantity_delta']
                    full_points.append(dict(timestamp=row['timestamp'],balance=full_balance))
            full_points.append(dict(timestamp=last,balance=full_balance))
            overview,_=sample_extrema(full_points,point_limit)
            selected,step=sample_extrema(points,point_limit)
            if step:sampled=True;resolution=max(resolution or 0,step)
            output.append(dict(id=hashlib.sha256((view+'\0'+name).encode()).hexdigest()[:16],name=name,opening_balance=opening,
                               closing_balance=balance,event_count=len(points)-2,point_count=len(points),points=selected,overview=overview))
        base.update(series=output,bounds=domain,window=dict(start=low,end=high),sampled=sampled,
                    resolution_ms=resolution,max_points=point_limit)
        return jsonify(base)
