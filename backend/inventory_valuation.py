"""Inventory wealth, independent of contributors' cash-flow balances."""
from collections import defaultdict
from itertools import groupby
from .quantities import event_order
from .valuation import money


def project_inventory(ledger,index,mode,stop):
    from .worker import AdapterFailure
    ordered=sorted(ledger,key=lambda r:(*event_order(dict(id=r['transaction_id'],occurred_at=r['occurred_at'],external_id=r['external_id'])),r['sequence']))
    operations=defaultdict(list)
    for transaction,rows in groupby(ordered,key=lambda r:r['transaction_id']):
        rows=list(rows);operations[rows[0]['occurred_at']].append(rows)
    price_times=set()
    if mode=='historical':
        price_times.update(s['effective_at'] for s in index.snapshots if s['effective_at'])
        for groups in index.histories.values():
            for dates,_ in groups:price_times.update(dates)
    changes=set(operations)|price_times
    quantities=defaultdict(int);active=set();last={};points=[];sequence=0

    def record(keys,at):
        nonlocal sequence
        sequence+=1
        for key in sorted(keys):
            quantity=quantities[key]
            if quantity<0:raise AdapterFailure('inventory_reconstruction_invalid',retryable=False)
            result,reason=index.resolve(key[1],at,mode) if quantity else (None,'empty')
            source,quote=result if result else (None,None)
            value=quantity*int(quote['price_atomic']) if quote else 0 if not quantity else None
            reason=('estimated_undated' if source['effective_at'] is None and not quote.get('effective_at') else 'priced') if source else reason
            fingerprint=(quantity,value,reason)
            if last.get(key)==fingerprint:continue
            last[key]=fingerprint
            points.append((sequence,at,key[0],key[1],quantity,str(value) if value is not None else None,reason,source['id'] if source else None,quote['quote_key'] if quote else None))

    for at in sorted(changes):
        if stop.is_set():raise AdapterFailure('interrupted')
        # Price changes apply before transactions with the same timestamp.
        if at in price_times:record(active,at)
        for rows in operations.get(at,[]):
            affected=set()
            for row in rows:
                key=(row['stash'],row['item_name']);quantities[key]+=row['quantity_delta'];affected.add(key)
            # All technical entries and movements in one transaction are atomic.
            for key in affected:
                if quantities[key]:active.add(key)
                else:active.discard(key)
            record(affected,at)
    return points


def inventory_rows(c,run,filters,settings,stashes):
    where=['run_id=?'];args=[run['id']]
    if filters.values['item']:
        predicate,values=filters.predicate('item','item_name');where.append(predicate);args+=values
    names=sorted({settings['stash_aliases'].get(s,s) for s in stashes})
    if names:where.append('stash IN ('+','.join('?' for _ in names)+')');args+=names
    return [dict(row) for row in c.execute('SELECT * FROM inventory_value_points WHERE '+' AND '.join(where)+' ORDER BY occurred_at,sequence,stash,item_name',args)]


def current_positions(points,cutoff=None):
    result={}
    for row in points:
        if cutoff is not None and row['occurred_at']>=cutoff:break
        result[(row['stash'],row['item_name'])]=row
    return result


def coverage(positions):
    held=[row for row in positions.values() if row['quantity']>0]
    priced=[row for row in held if row['value_atomic'] is not None]
    missing=[row for row in held if row['value_atomic'] is None]
    return dict(coverage='none' if missing and not priced else 'partial' if missing else 'complete',
                priced_operations=len(priced),unpriced_operations=len(missing),estimated_operations=sum(row['reason']=='estimated_undated' for row in priced),
                snapshot_ids=sorted({row['snapshot_id'] for row in priced}),model='inventory')


def inventory_report(points,start,end,view,page,size,missing_page):
    opening=current_positions(points,start) if start else {};closing=current_positions(points,end)
    groups={};missing={}
    for row in closing.values():
        name=row['stash'] if view=='stashes' else 'summary'
        group=groups.setdefault(name,dict(name=name,opening_value=0,net=0,quantity=0,unpriced_units=0,change=0,reconstruction=False))
        group['quantity']+=row['quantity']
        if row['value_atomic'] is not None:group['net']+=int(row['value_atomic'])
        elif row['quantity']:
            group['unpriced_units']+=row['quantity'];key=(row['item_name'],row['reason'])
            item=missing.setdefault(key,dict(item_name=key[0],reason=key[1],operations=0,units=0))
            item['operations']+=1;item['units']+=row['quantity']
    for row in opening.values():
        name=row['stash'] if view=='stashes' else 'summary'
        group=groups.setdefault(name,dict(name=name,opening_value=0,net=0,quantity=0,unpriced_units=0,change=0,reconstruction=False))
        if row['value_atomic'] is not None:group['opening_value']+=int(row['value_atomic'])
    values=sorted(groups.values(),key=lambda row:row['name'])
    for row in values:
        row['change']=money(row['net']-row['opening_value']);row['net']=money(row['net']);row['opening_value']=money(row['opening_value'])
    missing=sorted(missing.values(),key=lambda row:(row['item_name'],row['reason']))
    pages=max(1,(len(values)+size-1)//size);page=min(page,pages)
    missing_pages=max(1,(len(missing)+49)//50);missing_page=min(missing_page,missing_pages)
    return dict(rows=values[(page-1)*size:page*size],total=len(values),page=page,pages=pages,unpriced=missing[(missing_page-1)*50:missing_page*50],
                unpriced_total=len(missing),unpriced_page=missing_page,unpriced_pages=missing_pages,**coverage(closing))


def inventory_movements(points):
    """Convert whole-position values into atomic value changes for shared chart sampling."""
    previous={};movements=[];identity=0
    for (at,sequence,stash),group in groupby(points,key=lambda row:(row['occurred_at'],row['sequence'],row['stash'])):
        delta=0
        for point in group:
            key=(stash,point['item_name']);value=int(point['value_atomic']) if point['value_atomic'] is not None else 0
            delta+=value-previous.get(key,0);previous[key]=value
        identity+=1
        movements.append(dict(id=identity,external_id=str(identity),sequence=0,atomic_group=sequence,occurred_at=at,stash=stash,account='',quantity_delta=delta,confidence='derived'))
    return movements


def atomic_totals(rows):
    groups={}
    for row in rows:
        key=row['atomic_group']
        if key not in groups:groups[key]=dict(row)
        else:groups[key]['quantity_delta']+=row['quantity_delta']
    return list(groups.values())
