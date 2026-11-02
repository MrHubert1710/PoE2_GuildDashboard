"""Cumulative movement balances with viewport-aware, extrema-preserving sampling."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import math
import re

from flask import current_app, jsonify, request
from .browsing import request_timezone, ReadError, date_argument, number_argument, one_argument, stash_arguments
from .database import connect, require_schema
from .quantities import effective_settings
from .quantity_api import league_row, metadata
from .text_search import TextFilters

FILTER_ARGUMENTS = {'timezone', 'account', 'account_regex', 'account_case', 'account_word', 'stash', 'item',
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


def navigator_context(rows, view, limit):
    """Full filtered history; calendar dates only select the detail window."""
    bounds = dict(start=rows[0]['timestamp']-1, end=rows[-1]['timestamp']+1)
    groups = defaultdict(list)
    for row in rows:
        name=row['account'] if view=='players' else row['stash'] if view=='stashes' else 'summary'
        groups[name].append(row)
    ranked=sorted(groups,key=lambda name:(name!='__poa_reconstruction__',-sum(abs(row['quantity_delta']) for row in groups[name]),name))[:100]
    point_limit=min(limit,max(24,6000//max(1,len(ranked))))
    series=[]
    for name in ranked:
        balance=0;points=[dict(timestamp=bounds['start'],balance=0)]
        for row in groups[name]:
            balance+=row['quantity_delta'];points.append(dict(timestamp=row['timestamp'],balance=balance))
        points.append(dict(timestamp=bounds['end'],balance=balance))
        overview,_=sample_extrema(points,point_limit)
        series.append(dict(id=hashlib.sha256((view+'\0'+name).encode()).hexdigest()[:16],name=name,reconstruction=name=='__poa_reconstruction__',
                           opening_balance=0,closing_balance=balance,event_count=len(points)-2,
                           point_count=len(points),points=overview,overview=overview))
    return dict(bounds=bounds,series=series)


def combined_series(rows, window, limit, overview=None):
    """Sum ordered source movements before sampling, including simultaneous events."""
    low,high=window['start'],window['end']
    opening=sum(row['quantity_delta'] for row in rows if row['timestamp']<low)
    balance=opening;points=[dict(timestamp=low,balance=balance)]
    for row in rows:
        if low<=row['timestamp']<high:
            balance+=row['quantity_delta'];points.append(dict(timestamp=row['timestamp'],balance=balance))
    points.append(dict(timestamp=high,balance=balance))
    selected,step=sample_extrema(points,limit)
    return dict(id='combined',name='Combined balance',aggregate=True,opening_balance=opening,closing_balance=balance,
                event_count=len(points)-2,point_count=len(points),points=selected,
                overview=overview if overview is not None else selected),step


def event_order(row):
    external=row['external_id'];numeric=external.isascii() and external.isdigit()
    return row['occurred_at'],0 if numeric else 1,int(external) if numeric else external,row['id'],row['sequence']


def read_series(league_id):
    if set(request.args) - FILTER_ARGUMENTS - {'revision', 'projection_id', 'series_item', 'max_points', 'view', 'window_start', 'window_end', 'all_items', 'at'}:
        raise ReadError('unknown_parameter')
    limit = number_argument('max_points', 240, 24, 600)
    view = one_argument('view','summary')
    if view not in {'summary','players','stashes'}:
        raise ReadError('invalid_view')
    lower, upper = viewport_argument('window_start'), viewport_argument('window_end')
    if (lower is None) != (upper is None) or (lower is not None and lower >= upper):
        raise ReadError('invalid_viewport')
    at=viewport_argument('at')
    all_items=one_argument('all_items','0')
    if all_items not in {'0','1'}:raise ReadError('invalid_all_items')
    all_items=all_items=='1'
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
        settings=dict(effective_settings(league,c),timezone=request_timezone(effective_settings(league,c)['timezone']))
        start,end=date_argument('from',zone=settings['timezone']),date_argument('to',end=True,zone=settings['timezone'])
        if start and end and start>=end: raise ReadError('invalid_date_range')
        base=dict(league_id=league_id,projection=meta,timezone=settings['timezone'],view=view,unit='item_count',
                  items=[],item=item or None,series=[],bounds=None,window=None,total_series=None,navigator=dict(bounds=None,series=[],total_series=None),resolution_ms=None,max_points=limit,
                  sampled=False,unresolved_events=0,series_truncated=False,totals=dict(added=0,removed=0,net=0,inferred=0))
        if not run:return jsonify(base)
        conditions,args=["m.run_id=?","q.effective_action!='excluded'"],[run['id']]
        for field,column in [('account','COALESCE(m.account,t.account)'),('item','m.item_name')]:
            if filters.values[field]:
                predicate,values=filters.predicate(field,column);conditions.append(predicate);args.extend(values)
        names=sorted({settings['stash_aliases'].get(name,name) for name in stashes})
        if names:
            conditions.append('q.stash IN ('+','.join('?' for _ in names)+')');args.extend(names)
        # Read preceding movements too: a date/viewport filter must not reset the balance.
        common=(' FROM quantity_ledger m JOIN event_quantities q ON q.run_id=m.run_id AND q.transaction_id=m.transaction_id '
                'JOIN transactions t ON t.id=m.transaction_id WHERE '+' AND '.join(conditions))
        catalog=[row[0] for row in c.execute('SELECT m.item_name'+common+' GROUP BY m.item_name ORDER BY SUM(ABS(m.quantity_delta)) DESC,m.item_name LIMIT 50',args)]
        item=None if all_items else item or (catalog[0] if catalog else None);base.update(items=catalog,item=item,all_items=all_items)
        item_sql,item_args=('',[]) if all_items else (' AND m.item_name=?',[item])
        if at is not None:
            try:cutoff=(datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(milliseconds=at+1)).isoformat(timespec='microseconds').replace('+00:00','Z')
            except (OverflowError,ValueError):raise ReadError('invalid_viewport')
            column='COALESCE(m.account,t.account)' if view=='players' else 'q.stash' if view=='stashes' else "'summary'"
            cursor_rows=c.execute('SELECT '+column+' AS name,SUM(CASE WHEN t.occurred_at<? THEN m.quantity_delta ELSE 0 END) AS balance'+common+item_sql+' GROUP BY '+column+" ORDER BY (name='__poa_reconstruction__') DESC,SUM(ABS(m.quantity_delta)) DESC,name",[cutoff,*args,*item_args]).fetchall()
            total=sum(row['balance'] for row in cursor_rows)
            balances=[dict(id=hashlib.sha256((view+'\0'+row['name']).encode()).hexdigest()[:16],name=row['name'],reconstruction=row['name']=='__poa_reconstruction__',balance=row['balance']) for row in cursor_rows[:100]]
            if view!='summary':balances.append(dict(id='combined',name='Combined balance',balance=total))
            return jsonify(league_id=league_id,projection=meta,timezone=settings['timezone'],timestamp=at,balances=balances)
        if not item and not all_items:return jsonify(base)
        event_conditions=[value.replace('COALESCE(m.account,t.account)','t.account').replace('m.run_id','q.run_id').replace('m.item_name','q.item_name') for value in conditions]
        extra,extra_args='',[]
        if start:extra+=' AND t.occurred_at>=?';extra_args.append(start)
        if end:extra+=' AND t.occurred_at<?';extra_args.append(end)
        unknown_sql=('SELECT COUNT(*) FROM event_quantities q JOIN transactions t ON t.id=q.transaction_id WHERE '+' AND '.join(event_conditions)+
                     (" AND q.item_name=?" if not all_items else "")+" AND (q.effective_action='unknown' OR q.resolution_reason='invalid_quantity')"+extra)
        base['unresolved_events']=c.execute(unknown_sql,[*args,*([] if all_items else [item]),*extra_args]).fetchone()[0]
        rows=[dict(row) for row in c.execute('SELECT t.id,t.external_id,t.occurred_at,COALESCE(m.account,t.account) AS account,q.stash,m.sequence,m.quantity_delta,m.confidence'+common+item_sql,[*args,*item_args])]
        if not rows:return jsonify(base)
        rows.sort(key=event_order)
        for row in rows:row['timestamp']=stamp(row['occurred_at'])
        ledger_rows=rows
        if view != 'players':
            # Technical entries and player movements form one atomic event per stash.
            # Do not draw a fictitious stock spike between a correction and removal.
            atomic = {}
            for row in rows:
                if row['id'] not in atomic:
                    atomic[row['id']] = dict(row)
                else:
                    atomic[row['id']]['quantity_delta'] += row['quantity_delta']
                    if row['confidence'] == 'inferred': atomic[row['id']]['confidence'] = 'inferred'
            rows = list(atomic.values())
        for row in rows:row['timestamp']=stamp(row['occurred_at'])
        base['navigator']=navigator_context(rows,view,limit)
        first=stamp(start) if start else rows[0]['timestamp']-1
        last=stamp(end) if end else rows[-1]['timestamp']+1
        if last<=first:last=first+1
        domain=dict(start=first,end=last)
        low=lower if lower is not None else first
        high=upper if upper is not None else last
        if low>=high:low,high=first,last
        grouped=defaultdict(list)
        for row in rows:
            group=row['account'] if view=='players' else row['stash'] if view=='stashes' else 'summary'
            grouped[group].append(row)
        for row in ledger_rows:
            if low<=row['timestamp']<high:
                amount=row['quantity_delta'];base['totals']['added' if amount>0 else 'removed']+=abs(amount)
                base['totals']['net']+=amount
                if row['confidence']=='inferred':base['totals']['inferred']+=abs(amount)
        ranked=sorted(grouped,key=lambda group:(group!='__poa_reconstruction__',-sum(abs(row['quantity_delta']) for row in grouped[group]),group))
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
            output.append(dict(id=hashlib.sha256((view+'\0'+name).encode()).hexdigest()[:16],name=name,reconstruction=name=='__poa_reconstruction__',opening_balance=opening,
                               closing_balance=balance,event_count=len(points)-2,point_count=len(points),points=selected,overview=overview))
        base['navigator']['total_series']=None
        if view!='summary':
            total_context,_=combined_series(rows,base['navigator']['bounds'],limit)
            base['navigator']['total_series']=total_context
            base['total_series'],step=combined_series(rows,dict(start=low,end=high),limit,total_context['overview'])
            if step:sampled=True;resolution=max(resolution or 0,step)
        base.update(series=output,bounds=domain,window=dict(start=low,end=high),sampled=sampled,
                    resolution_ms=resolution,max_points=point_limit)
        return jsonify(base)
