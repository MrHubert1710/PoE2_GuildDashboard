"""Immutable league-scoped price observations. Undated legacy data stays undated."""
from collections import defaultdict
from bisect import bisect_right
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import unicodedata
from .archive_import import canonical
from .database import connect, utc_now
from .ninja import PriceError, NinjaClient

ATOMIC=10**12
CURRENCY='Divine Orb'


def name_key(value):
    if not isinstance(value,str):raise PriceError('price_payload_invalid')
    return ' '.join(unicodedata.normalize('NFKC',value).replace('’',"'").split()).casefold()


def amount(value):
    try:result=Decimal(str(value))
    except (InvalidOperation,ValueError):raise PriceError('price_payload_invalid')
    if not result.is_finite() or result<0 or result>Decimal(10**9):raise PriceError('price_payload_invalid')
    return result


def normalize(payload,feed):
    if not isinstance(payload,dict) or not isinstance(payload.get('lines'),list):raise PriceError('price_payload_invalid')
    core=payload.get('core') or {}
    if not isinstance(core,dict):raise PriceError('price_payload_invalid')
    primary=core.get('primary')
    if primary=='divine':factor=Decimal(1)
    elif primary and isinstance(core.get('rates'),dict) and 'divine' in core['rates']:factor=amount(core['rates']['divine'])
    else:raise PriceError('price_currency_unknown')
    if factor<=0:raise PriceError('price_currency_unknown')
    metadata={row['id']:row for row in payload.get('items',[]) if isinstance(row,dict) and 'id' in row}
    quotes=[];seen=set()
    for row in payload['lines']:
        if not isinstance(row,dict):raise PriceError('price_payload_invalid')
        if feed=='exchange':
            meta=metadata.get(row.get('id'),{})
            title=meta.get('name')
            key=str(row.get('id',''));variant=None
        elif feed=='stash':
            title=row.get('name');key=str(row.get('itemId') or row.get('id') or '')
            variant=canonical({key:row[key] for key in ('variant','corrupted','gemLevel','gemQuality','links') if row.get(key) not in (None,False,'')})
            if variant=='{}':variant=None
            key+=':'+str(row.get('id',''))+':'+(variant or '')
        else:raise PriceError('price_payload_invalid')
        if not title or not key or key in seen:raise PriceError('price_payload_invalid')
        seen.add(key)
        price=amount(row.get('primaryValue'))*factor
        if price>Decimal(10**9):raise PriceError('price_payload_invalid')
        quotes.append(dict(quote_key=key,name=title,name_key=name_key(title),price_atomic=str(int((price*ATOMIC).quantize(Decimal(1),rounding=ROUND_HALF_EVEN))),variant=variant))
    # The primary currency is often omitted from lines; its value is exactly 1 primary.
    if feed=='exchange' and any(row.get('category')=='Currency' for row in metadata.values()):
        for meta in core.get('items',[]):
            if not isinstance(meta,dict) or not meta.get('name') or meta.get('id') in seen:continue
            key=meta['id']
            if key==primary:rate=Decimal(1)
            elif key in core.get('rates',{}):
                units=amount(core['rates'][key])
                if not units:continue
                rate=Decimal(1)/units
            else:continue
            if rate*factor>Decimal(10**9):raise PriceError('price_payload_invalid')
            quotes.append(dict(quote_key=key,name=meta['name'],name_key=name_key(meta['name']),price_atomic=str(int((rate*factor*ATOMIC).quantize(Decimal(1)))),variant=None));seen.add(key)
    return quotes


def snapshot(league_id,feed,category,payload,*,effective_at=None,provenance='observed',observed_at=None):
    if effective_at is not None:
        date=datetime.fromisoformat(effective_at.replace('Z','+00:00'))
        if date.tzinfo is None:raise PriceError('price_time_unknown')
        effective_at=date.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    raw=canonical(payload);digest=hashlib.sha256(raw.encode()).hexdigest()
    identity=hashlib.sha256(canonical([league_id,feed,category,digest,provenance]).encode()).hexdigest()
    return dict(id=identity,league_id=league_id,feed=feed,category=category,observed_at=observed_at or utc_now(),effective_at=effective_at,
                provenance=provenance,sha256=digest,payload_json=raw,currency=CURRENCY,quotes=normalize(payload,feed))


def save_snapshot(c,data):
    columns=[key for key in data if key!='quotes']
    inserted=c.execute(f"INSERT OR IGNORE INTO price_snapshots({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",[data[key] for key in columns]).rowcount
    if inserted:
        for quote in data['quotes']:
            c.execute('INSERT INTO price_quotes VALUES(?,?,?,?,?,?,?)',(data['id'],quote['quote_key'],quote['name'],quote['name_key'],quote['price_atomic'],quote['variant'],quote.get('effective_at')))
    return bool(inserted)


def legacy_snapshots(c,league_id,data_root):
    root=Path(data_root).resolve();result=[]
    for row in c.execute("SELECT relative_path,sha256 FROM archive_files WHERE league_id=? AND kind='price_cache' ORDER BY relative_path",(league_id,)):
        path=(root/row['relative_path']).resolve()
        if not path.is_relative_to(root):raise PriceError('price_archive_invalid')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise PriceError('price_archive_invalid')
        payload=json.loads(raw)
        categories={item.get('category') for item in payload.get('items',[]) if isinstance(item,dict) and item.get('category')}
        category=next(iter(categories)) if len(categories)==1 else path.stem
        result.append(snapshot(league_id,'exchange',category,payload,provenance='legacy_undated'))
    return result


def import_legacy(database,data_root):
    with connect(database) as c:
        staged=[entry for league in c.execute('SELECT id FROM leagues') for entry in legacy_snapshots(c,league['id'],data_root)]
        c.execute('BEGIN IMMEDIATE')
        try:
            inserted=sum(save_snapshot(c,data) for data in staged);c.commit()
        except BaseException:c.rollback();raise
    return inserted


def price_revision(c,league_id):
    snapshots=[tuple(row) for row in c.execute('SELECT id,effective_at FROM price_snapshots WHERE league_id=? ORDER BY id',(league_id,))]
    aliases=[tuple(row) for row in c.execute('SELECT source_key,target_key FROM price_aliases WHERE league_id=? ORDER BY source_key',(league_id,))]
    return hashlib.sha256(canonical([snapshots,aliases]).encode()).hexdigest()


class PriceIndex:
    def __init__(self,c,league_id):
        self.snapshots=[dict(r) for r in c.execute('SELECT id,feed,category,effective_at,observed_at,provenance FROM price_snapshots WHERE league_id=? ORDER BY effective_at,observed_at,id',(league_id,))]
        by_id={s['id']:s for s in self.snapshots}
        histories=defaultdict(list)
        self.quotes=defaultdict(lambda:defaultdict(list))
        for r in c.execute('SELECT q.* FROM price_quotes q JOIN price_snapshots s ON s.id=q.snapshot_id WHERE s.league_id=?',(league_id,)):
            quote=dict(r);source=by_id[r['snapshot_id']]
            if source['provenance']=='history_daily':
                histories[(r['name_key'],source['feed'],source['category'],r['quote_key'].rsplit('@',1)[0])].append((source,quote))
            else:self.quotes[r['snapshot_id']][r['name_key']].append(quote)
        self.histories=defaultdict(list)
        for (name,feed,category,item),samples in histories.items():
            samples.sort(key=lambda pair:(pair[1]['effective_at'],pair[0]['observed_at'],pair[0]['id']))
            self.histories[name].append(([pair[1]['effective_at'] for pair in samples],samples))
        self.aliases=dict(c.execute('SELECT source_key,target_key FROM price_aliases WHERE league_id=?',(league_id,)))
        self.categories=defaultdict(list)
        self.cache={}
        for row in self.snapshots:
            if row['provenance']!='history_daily':self.categories[(row['feed'],row['category'])].append(row)
    def resolve(self,item,at,mode):
        key=name_key(item);key=self.aliases.get(key,key);cache_key=(key,at if mode=='historical' else None,mode)
        if cache_key in self.cache:return self.cache[cache_key]
        result=self._resolve(key,at,mode);self.cache[cache_key]=result;return result
    def _resolve(self,key,at,mode):
        grouped=defaultdict(list)
        for snapshots in self.categories.values():
            dated=[s for s in snapshots if s['effective_at'] is not None and (mode=='latest' or s['effective_at']<=at)]
            if dated:chosen=max(dated,key=lambda s:(s['effective_at'],s['id']))
            elif mode=='latest':chosen=max(snapshots,key=lambda s:(s['observed_at'],s['id']))
            else:continue
            for quote in self.quotes[chosen['id']].get(key,[]):grouped[(chosen['feed'],chosen['category'])].append((chosen,quote))
        historical=defaultdict(list)
        for dates,samples in self.histories.get(key,[]):
            index=len(samples)-1 if mode=='latest' else bisect_right(dates,at)-1
            if index>=0:
                source,quote=samples[index];historical[(source['feed'],source['category'])].append((source,quote))
        for category,points in historical.items():
            current=grouped.get(category,[])
            # A newer observed overview supersedes daily data for latest pricing.
            if not current or max(p[1]['effective_at'] for p in points)>=max(p[0]['effective_at'] or '' for p in current):grouped[category]=points
        candidates=[candidate for group in grouped.values() for candidate in group]
        # Legacy category keys may differ from today's catalog (currency/Currency).
        # Undated estimates must not make a known dated quote ambiguous.
        dated=[candidate for candidate in candidates if candidate[1].get('effective_at') or candidate[0]['effective_at']]
        if dated:candidates=dated
        if not candidates:return None,'historical_price_missing' if mode=='historical' else 'price_missing'
        if len(candidates)>1 or candidates[0][1]['variant']:return None,'price_ambiguous'
        return candidates[0],None


class PricesAdapter:
    def stage(self,queue,job,stop):
        from .worker import AdapterFailure, ROOT
        client=NinjaClient(queue.path)
        try:
            categories=client.catalog();league=client.league_id(job['league_name']) if 'league_name' in job else None
            if league is None:
                with connect(queue.path,readonly=True) as c:league=client.league_id(queue.league(c,job['league_id'])['name'])
        except PriceError as error:raise AdapterFailure(error.code,retryable=False) from None
        with connect(queue.path,readonly=True) as c:
            names={name_key(row[0]) for row in c.execute('SELECT DISTINCT item_name FROM quantity_ledger WHERE run_id IN (SELECT id FROM quantity_runs WHERE league_id=?)',(job['league_id'],))}
            names.update(row[0] for row in c.execute('SELECT target_key FROM price_aliases WHERE league_id=?',(job['league_id'],)))
        staged=[];errors=[];history_count=0;sample_count=0;references={}
        from .price_history import history_snapshot
        for category in sorted(categories,key=lambda cat:(cat['feed']!='exchange',cat['category']!='Currency')):
            if stop.is_set():raise AdapterFailure('interrupted')
            try:
                payload=client.prices(league,category)
                staged.append(snapshot(job['league_id'],category['feed'],category['category'],payload,effective_at=utc_now()))
            except (PriceError,ValueError,TypeError,KeyError) as error:errors.append(dict(category=category['category'],error=getattr(error,'code','price_payload_invalid')))
            else:
                items=payload.get('items',[]) if category['feed']=='exchange' else payload['lines']
                core_items=payload.get('core',{}).get('items',[]) if category['feed']=='exchange' and category['category']=='Currency' else []
                items=[*items,*core_items]
                core_ids={item['id'] for item in core_items}
                targets={str(item['id']):item for item in items if isinstance(item,dict) and 'id' in item and (item['id'] in core_ids or name_key(item.get('name','')) in names)}
                for item in targets.values():
                    if stop.is_set():raise AdapterFailure('interrupted')
                    try:
                        response=client.history(league,category,item)
                        data=history_snapshot(job['league_id'],category,item,response,primary=payload.get('core',{}).get('primary',''),references=references)
                        if item['id'] in core_ids:references[item['id']]={q['effective_at']:Decimal(q['price_atomic'])/ATOMIC for q in data['quotes']}
                        staged.append(data);history_count+=1;sample_count+=len(data['quotes'])
                    except (PriceError,ValueError,TypeError,KeyError,AttributeError) as error:
                        errors.append(dict(category=category['category'],item=item['name'],error=getattr(error,'code','price_history_invalid')))
                    # One request at a time, with a small pause; shared HTTP cache avoids repeats.
                    if stop.wait(.1):raise AdapterFailure('interrupted')
        if not staged:raise AdapterFailure('price_source_unavailable',retryable=False)
        identity=hashlib.sha256(canonical(categories).encode()).hexdigest()
        def publish(c):
            c.execute('INSERT OR IGNORE INTO price_catalogs VALUES(?,?,?)',(identity,utc_now(),canonical(categories)))
            c.execute('UPDATE price_categories SET active=0')
            for cat in categories:c.execute('INSERT OR REPLACE INTO price_categories VALUES(?,?,?,?,?)',(cat['feed'],cat['category'],cat['label'],1,identity))
            inserted=sum(save_snapshot(c,data) for data in staged)
            return dict(snapshots=inserted,categories=len(categories),history_items=history_count,history_samples=sample_count,history_format=1,errors=errors)
        return publish
