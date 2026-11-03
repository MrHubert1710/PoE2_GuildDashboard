"""Session-based guild history adapter ported from the user's existing fetcher.

The website endpoint is separate from the documented OAuth API. Every page and
entry is retained; unknown/unmonitored leagues stay pending until admin approval.
"""
from datetime import datetime,timezone
import hashlib,json,time,uuid
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from .archive_import import normalize,canonical
from .database import connect,utc_now
from .ggg_connection import GGGConnectionStore
from .quantities import parse_quantity

RESOURCE='ggg-guild-history-v1'
URL='https://www.pathofexile.com/api/guild/{guild_id}/stash/history'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def rate_delay(headers):
    delay=0
    value=headers.get('Retry-After','')
    if str(value).isdigit():delay=int(value)
    elif value:
        from email.utils import parsedate_to_datetime
        try:delay=max(0,parsedate_to_datetime(value).timestamp()-time.time())
        except (TypeError,ValueError,OverflowError):pass
    for rule in str(headers.get('X-Rate-Limit-Rules','')).split(','):
        rule=rule.strip()
        if not rule:continue
        def triples(value):
            result=[]
            for part in str(value).split(','):
                try:result.append(tuple(int(v) for v in part.split(':')))
                except ValueError:continue
            return [r for r in result if len(r)==3]
        limits=triples(headers.get('X-Rate-Limit-'+rule,''));states=triples(headers.get('X-Rate-Limit-'+rule+'-State',''))
        for i,(hits,period,restriction) in enumerate(states):
            delay=max(delay,restriction)
            if i<len(limits) and hits>=max(1,limits[i][0]-1):delay=max(delay,limits[i][1])
    return max(.5,delay)+.1


def first(row,keys):
    for key in keys:
        if key in row and row[key] not in (None,''):return row[key]
    return ''


def normalize_event(raw):
    if not isinstance(raw,dict):raise ValueError('history_invalid_response')
    account=first(raw,['Account','account','accountName','account_name','user','player'])
    if isinstance(account,dict):account=first(account,['name','accountName','account_name','id'])
    item=first(raw,['Item','item','itemName','item_name','name'])
    if isinstance(item,dict):item=first(item,['name','itemName','typeLine','baseType','displayName'])
    date=first(raw,['Date','date','time','timestamp','createdAt','created_at'])
    if isinstance(date,(int,float)) or isinstance(date,str) and date.isdigit():
        value=float(date);value=value/1000 if value>=10**12 else value
        date=datetime.fromtimestamp(value,timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    row=dict(Date=str(date),Id=str(first(raw,['Id','id','transactionId','transaction_id','historyId','history_id'])),
             League=str(first(raw,['League','league'])),Account=str(account),Action=str(first(raw,['Action','action','event','type'])).lower(),
             Stash=str(first(raw,['Stash','stash','stashName','stash_name','tab','tabName'])),Item=str(item),
             X=str(first(raw,['X','x','left','column'])),Y=str(first(raw,['Y','y','top','row'])))
    if any(len(v)>2000 for v in row.values()) or len(row['Id'])>200 or len(row['League'])>200:raise ValueError('history_invalid_response')
    return row,normalize(row,row['League'].strip())


def entries(payload):
    if isinstance(payload,list):return payload
    if not isinstance(payload,dict) or payload.get('error'):raise ValueError('history_invalid_response')
    for key in ('entries','history','transactions','events','data','result'):
        if key in payload and isinstance(payload[key],(list,dict)):return entries(payload[key])
    raise ValueError('history_invalid_response')


class GuildHistoryClient:
    def __init__(self,store,opener=None):self.store=store;self.opener=opener or build_opener(NoRedirect()).open
    def fetch(self,configuration,from_time,end,from_id,stop):
        from .worker import AdapterFailure
        while True:
            current=self.store.get()
            if current['revision']!=configuration['revision'] or not current['enabled']:raise AdapterFailure('data_changed',retryable=False)
            delay=current['next_request']-time.time()
            if delay<=0:break
            if stop.wait(min(delay,60)):raise AdapterFailure('interrupted')
        params={'from':str(from_time),'end':str(end)}
        if from_id:params['fromid']=from_id
        request=Request(URL.format(guild_id=configuration['guild_id'])+'?'+urlencode(params),headers={'User-Agent':'PathOfAccounting/1.0 (+https://dyyyl.ovh/poe2guild/)','Accept':'application/json','Cookie':'POESESSID='+configuration['session_id']})
        try:
            with self.opener(request,timeout=30) as response:
                self.store.cooldown(time.time()+rate_delay(response.headers))
                raw=response.read(16*1024*1024+1)
                if len(raw)>16*1024*1024:raise AdapterFailure('history_invalid_response',retryable=False)
                body=raw.decode('utf-8');payload=json.loads(body)
                return body,payload
        except HTTPError as failure:
            delay=rate_delay(failure.headers or {})
            self.store.cooldown(time.time()+max(delay,60 if failure.code==429 else 0))
            code='history_auth_failed' if failure.code in (301,302,303,307,308,401,403) else 'provider_limited' if failure.code==429 else 'history_source_failed'
            self.store.mark(configuration['revision'],'rejected' if code=='history_auth_failed' else 'error',code)
            raise AdapterFailure(code,retryable=failure.code==429 or failure.code>=500,retry_after=delay) from None
        except (URLError,OSError,UnicodeError,ValueError):
            self.store.mark(configuration['revision'],'error','history_invalid_response')
            raise AdapterFailure('history_invalid_response',retryable=False) from None


def same_event(old,norm):
    fields={'occurred_at':'Date','account':'Account','action':'Action','stash':'Stash','x':'X','y':'Y'}
    if any(old[k]!=norm[v] for k,v in fields.items()):return False
    try:return parse_quantity(old['item'])==parse_quantity(norm['Item'])
    except ValueError:return old['item']==norm['Item']


class GuildHistoryAdapter:
    def stage(self,queue,job,stop):
        from .worker import AdapterFailure
        store=GGGConnectionStore(queue.connection_file);configuration=store.get()
        if not configuration['enabled'] or not configuration['session_id']:raise AdapterFailure('source_unavailable',retryable=False)
        job['connection_revision']=configuration['revision']
        source=configuration['source_id'];upper=int(time.time())
        with connect(queue.path,readonly=True) as c:
            row=c.execute('SELECT cursor FROM source_cursors WHERE source_id=? AND resource=?',(source,RESOURCE)).fetchone()
            expected=row[0] if row else None
        previous=json.loads(expected)['upper'] if expected else 0
        end=max(0,previous-6*3600);start=upper;from_id='';seen=set();pages=[];fetched=[]
        client=GuildHistoryClient(store)
        store.mark(configuration['revision'],'fetching',pages=0)
        for page_number in range(1,201):
            if stop.is_set():raise AdapterFailure('interrupted')
            body,payload=client.fetch(configuration,start,end,from_id,stop)
            try:
                records=entries(payload)
                if len(records)>100000:raise ValueError()
                truncated=payload.get('truncated',False) if isinstance(payload,dict) else False
                if type(truncated) is not bool:raise ValueError()
                normalized=[(raw,*normalize_event(raw)) for raw in records]
                if truncated and not records:raise ValueError()
            except (ValueError,TypeError,KeyError,OverflowError):
                store.mark(configuration['revision'],'error','history_invalid_response')
                raise AdapterFailure('history_invalid_response',retryable=False) from None
            page_id=str(uuid.uuid4());pages.append((page_id,page_number,str(start),str(end),from_id,utc_now(),body,hashlib.sha256(body.encode()).hexdigest()))
            fetched.extend((raw,csv,norm,page_id) for raw,csv,norm in normalized)
            store.mark(configuration['revision'],'fetching',pages=page_number)
            if not truncated:break
            last=normalized[-1][2];next_start=str(int(datetime.fromisoformat(last['Date'].replace('Z','+00:00')).timestamp()));next_id=last['Id']
            cursor=(next_start,next_id)
            if cursor in seen or cursor==(str(start),from_id):raise AdapterFailure('history_cursor_repeated',retryable=False)
            seen.add(cursor);start,from_id=next_start,next_id
        else:raise AdapterFailure('history_page_limit',retryable=False)
        def publish(c):
            if store.get()['revision']!=configuration['revision']:raise AdapterFailure('data_changed',retryable=False)
            cursor=c.execute('SELECT cursor FROM source_cursors WHERE source_id=? AND resource=?',(source,RESOURCE)).fetchone()
            if (cursor[0] if cursor else None)!=expected:raise AdapterFailure('data_changed')
            run=str(uuid.uuid4());stamp=utc_now();changed=set();duplicates=0
            c.execute("INSERT INTO import_runs(id,source_id,started_at,finished_at,status,manifest_sha256) VALUES(?,?,?,?,'completed',?)",(run,source,stamp,stamp,hashlib.sha256(canonical([p[7] for p in pages]).encode()).hexdigest()))
            c.executemany('INSERT INTO guild_history_pages VALUES(?,?,?,?,?,?,?,?,?,?)',[(p[0],source,run,*p[1:]) for p in pages])
            for raw,csv,norm,page_id in fetched:
                previous_event=c.execute('SELECT normalized_json FROM guild_history_events WHERE source_id=? AND league_name=? AND external_id=?',(source,norm['League'],norm['Id'])).fetchone()
                if previous_event:
                    previous_norm=normalize(json.loads(previous_event['normalized_json']),norm['League'])
                    prior={field:previous_norm[key] for field,key in {'occurred_at':'Date','account':'Account','action':'Action','stash':'Stash','item':'Item','x':'X','y':'Y'}.items()}
                    if not same_event(prior,norm):raise AdapterFailure('history_conflict',retryable=False)
                c.execute('INSERT OR IGNORE INTO guild_history_events VALUES(?,?,?,?,?,?,NULL,?)',(source,norm['League'],norm['Id'],norm['Date'],canonical(raw),canonical(csv),page_id))
            for event in c.execute('SELECT * FROM guild_history_events WHERE source_id=? AND transaction_id IS NULL ORDER BY occurred_at,external_id',(source,)).fetchall():
                league=c.execute("SELECT * FROM leagues WHERE game='poe2' AND realm='pc' AND name=? AND monitored=1",(event['league_name'],)).fetchone()
                if not league:continue
                csv=json.loads(event['normalized_json']);norm=normalize(csv,league['name'])
                old=c.execute('SELECT * FROM transactions WHERE source_id=? AND league_id=? AND external_id=?',(source,league['id'],norm['Id'])).fetchone()
                if old:
                    if not same_event(old,norm):raise AdapterFailure('history_conflict',retryable=False)
                    transaction=old['id'];duplicates+=1
                else:
                    values=(source,league['id'],norm['Id'],norm['Date'],norm['Account'],norm['Action'],norm['Stash'],norm['Item'],norm['X'],norm['Y'],canonical(csv),hashlib.sha256(canonical(norm).encode()).hexdigest(),'ggg-history-v1',run)
                    transaction=c.execute('INSERT INTO transactions(source_id,league_id,external_id,occurred_at,account,action,stash,item,x,y,raw_json,normalized_sha256,normalization_version,import_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',values).lastrowid
                    changed.add(league['id'])
                c.execute('UPDATE guild_history_events SET transaction_id=? WHERE source_id=? AND league_name=? AND external_id=?',(transaction,source,event['league_name'],event['external_id']))
            for league_id in changed:c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,NULL)',(str(uuid.uuid4()),league_id,run,stamp,'raw_import','ggg-history-v1'))
            c.execute('INSERT OR REPLACE INTO source_cursors VALUES(?,?,?,?)',(source,RESOURCE,canonical({'upper':upper,'schema':1}),stamp))
            inserted=c.execute('SELECT count(*) FROM transactions WHERE import_id=?',(run,)).fetchone()[0]
            pending=c.execute('SELECT count(*) FROM guild_history_events WHERE source_id=? AND transaction_id IS NULL',(source,)).fetchone()[0]
            c.execute('UPDATE import_runs SET inserted_count=?,duplicate_count=? WHERE id=?',(inserted,duplicates,run))
            store.mark(configuration['revision'],'connected',pages=len(pages))
            return dict(inserted=inserted,duplicates=duplicates,pending=pending,pages=len(pages),changed_leagues=sorted(changed))
        return publish
