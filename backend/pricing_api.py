"""Price provenance, availability and paginated signed operation valuations."""
import sqlite3
from flask import Blueprint,current_app,jsonify,request
from .database import connect,require_schema,DatabaseError
from .browsing import ReadError,read_error,database_error,one_argument,number_argument,date_argument,stash_arguments,request_timezone
from .quantity_api import league_row,metadata
from .quantities import effective_settings
from .text_search import TextFilters
from .valuation import current_valuation,money
from .prices import CURRENCY

pricing=Blueprint('pricing',__name__)
pricing.register_error_handler(ReadError,read_error)
pricing.register_error_handler(sqlite3.Error,database_error)
pricing.register_error_handler(DatabaseError,database_error)


@pricing.get('/api/leagues/<league_id>/prices')
def status(league_id):
    with connect(current_app.config['DATABASE_FILE'],readonly=True) as c:
        require_schema(c);c.execute('BEGIN');league=league_row(c,league_id)
        snapshots=[dict(row) for row in c.execute('SELECT s.id,s.feed,s.category,s.observed_at,s.effective_at,s.provenance,s.currency,MIN(q.effective_at) AS history_from,MAX(q.effective_at) AS history_to,COUNT(q.effective_at) AS history_samples FROM price_snapshots s LEFT JOIN price_quotes q ON q.snapshot_id=s.id WHERE s.league_id=? GROUP BY s.id ORDER BY s.observed_at DESC,s.id',(league_id,))]
        categories=[dict(row) for row in c.execute('SELECT feed,category,label,active FROM price_categories ORDER BY feed,category')]
        historical,revision=current_valuation(c,league,'historical');latest,_=current_valuation(c,league,'latest')
        return jsonify(currency=CURRENCY,price_revision=revision,snapshots=snapshots,categories=categories,
                       valuations={'historical':bool(historical),'latest':bool(latest)},undated=any(s['provenance']=='legacy_undated' for s in snapshots))


@pricing.get('/api/leagues/<league_id>/valuations')
def report(league_id):
    allowed={'mode','view','account','account_regex','account_case','account_word','stash','item','item_regex','item_case','item_word','from','to','timezone','page','page_size','unpriced_page','revision'}
    if set(request.args)-allowed:raise ReadError('unknown_parameter')
    mode=one_argument('mode','historical');view=one_argument('view','summary')
    if mode not in {'historical','latest'} or view not in {'summary','players','stashes'}:raise ReadError('invalid_view')
    page=number_argument('page',1,1,1000000);size=number_argument('page_size',25,1,100)
    missing_page=number_argument('unpriced_page',1,1,1000000)
    filters=TextFilters()
    with connect(current_app.config['DATABASE_FILE'],readonly=True) as c:
        require_schema(c);c.execute('BEGIN');filters.bind(c);c.create_function('casefold',1,lambda v:v.casefold())
        league=league_row(c,league_id);meta,qrun=metadata(c,league);run,revision=current_valuation(c,league,mode)
        if one_argument('revision') and one_argument('revision')!=meta['input_revision']:raise ReadError('revision_changed',409)
        if not run:return jsonify(state='missing',rows=[],unpriced=[],unpriced_total=0,total=0,page=1,pages=1,mode=mode,currency=CURRENCY,price_revision=revision)
        where=['v.run_id=?'];args=[run['id']]
        for field,column in [('account','COALESCE(m.account,t.account)'),('item','m.item_name')]:
            if filters.values[field]:
                predicate,values=filters.predicate(field,column);where.append(predicate);args.extend(values)
        settings=effective_settings(league,c);stashes=sorted({settings['stash_aliases'].get(s,s) for s in stash_arguments()})
        if stashes:where.append('q.stash IN ('+','.join('?' for _ in stashes)+')');args+=stashes
        start,end=date_argument('from',zone=request_timezone(settings['timezone'])),date_argument('to',end=True,zone=request_timezone(settings['timezone']))
        if start and end and start>=end:raise ReadError('invalid_date_range')
        if start:where.append('t.occurred_at>=?');args.append(start)
        if end:where.append('t.occurred_at<?');args.append(end)
        common=' FROM valuation_lines v JOIN quantity_ledger m ON m.run_id=? AND m.transaction_id=v.transaction_id AND m.sequence=v.sequence JOIN event_quantities q ON q.run_id=m.run_id AND q.transaction_id=m.transaction_id JOIN transactions t ON t.id=m.transaction_id WHERE '+' AND '.join(where)
        rows=[dict(row) for row in c.execute('SELECT m.*,t.account AS actor,q.stash,v.value_atomic,v.reason,v.snapshot_id'+common,[run['quantity_run_id'],*args])]
        groups={};missing={};snapshots=set();estimated=0;priced=0
        for row in rows:
            if row['value_atomic'] is None:
                key=(row['item_name'],row['reason']);value=missing.setdefault(key,dict(item_name=key[0],reason=key[1],operations=0,units=0))
                value['operations']+=1;value['units']+=abs(row['quantity_delta']);continue
            priced+=1;estimated+=row['reason']=='estimated_undated';snapshots.add(row['snapshot_id'])
            name=(row['account'] or row['actor']) if view=='players' else row['stash'] if view=='stashes' else 'summary'
            value=groups.setdefault(name,dict(name=name,added=0,removed=0,net=0,operations=0,reconstruction=name=='__poa_reconstruction__'))
            amount=int(row['value_atomic']);value['net']+=amount;value['added' if amount>=0 else 'removed']+=abs(amount);value['operations']+=1
        values=sorted(groups.values(),key=lambda v:v['name'])
        for row in values:
            for key in ('added','removed','net'):row[key]=money(row[key])
        missing=sorted(missing.values(),key=lambda v:(v['item_name'],v['reason']));missing_pages=max(1,(len(missing)+49)//50);missing_page=min(missing_page,missing_pages);pages=max(1,(len(values)+size-1)//size);page=min(page,pages)
        return jsonify(state='ready',rows=values[(page-1)*size:page*size],unpriced=missing[(missing_page-1)*50:missing_page*50],unpriced_total=len(missing),unpriced_page=missing_page,unpriced_pages=missing_pages,total=len(values),page=page,pages=pages,
                       mode=mode,currency=CURRENCY,price_revision=revision,valuation_id=run['id'],snapshot_ids=sorted(snapshots),estimated_operations=estimated,
                       priced_operations=priced,unpriced_operations=sum(v['operations'] for v in missing),coverage='none' if not priced else 'partial' if missing else 'complete',
                       algorithm_version=run['algorithm_version'])
