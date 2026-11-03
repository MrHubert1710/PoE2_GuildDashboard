"""Provider evidence is separate from admin-approved local leagues and monitoring."""
from datetime import datetime,timezone
import json,os,re,time,uuid
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,quote
from .archive_import import canonical
from .database import connect,utc_now
from .ninja import NinjaClient,PriceError,ROOT as NINJA_ROOT

GGG_ROOT='https://api.pathofexile.com'


def ggg_configuration():
    token=os.getenv('POA_GGG_LEAGUES_TOKEN','')
    client=os.getenv('POA_GGG_CLIENT_ID','');contact=os.getenv('POA_GGG_CONTACT','')
    valid=bool(token and len(token)<=4096 and all(33<=ord(c)<127 for c in token) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',client) and contact and len(contact)<=200 and all(32<=ord(c)<127 for c in contact) and '\r' not in token and '\n' not in token)
    return (token,f'OAuth {client}/1.0 (contact: {contact}) PathOfAccounting') if valid else None


def text(value):
    if not isinstance(value,str) or not value.strip() or len(value)>200 or value!=value.strip() or any(ord(c)<32 for c in value):raise PriceError('catalog_invalid')
    return value


def lifecycle(raw,now):
    def date(key):
        value=raw.get(key)
        if value is None:return None
        try:
            result=datetime.fromisoformat(value.replace('Z','+00:00'))
            if result.tzinfo is None:raise ValueError()
            return result.astimezone(timezone.utc)
        except (ValueError,TypeError,AttributeError):raise PriceError('catalog_invalid') from None
    start,end=date('startAt'),date('endAt')
    if start and end and end<start:raise PriceError('catalog_invalid')
    if end and end<=now:return 'ended'
    if start and start>now:return 'unknown'
    if (raw.get('category') or {}).get('current') is True or raw.get('_list') in ('main','event'):return 'active'
    return 'unknown'


def parse_catalog(provider,payload,now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(payload,list) or not payload or len(payload)>2000:raise PriceError('catalog_invalid')
    rows=[];seen=set()
    for raw in payload:
        if not isinstance(raw,dict):raise PriceError('catalog_invalid')
        identity=text(raw.get('id'));name=text(raw.get('name') if provider=='poe.ninja' else raw.get('name') or identity)
        if identity in seen:raise PriceError('catalog_invalid')
        seen.add(identity)
        if provider=='ggg':
            if raw.get('realm') not in (None,'pc','poe2'):raise PriceError('catalog_invalid')
            rules=raw.get('rules') or []
            if not isinstance(rules,list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rules):raise PriceError('catalog_invalid')
            if raw.get('category') is not None and not isinstance(raw['category'],dict):raise PriceError('catalog_invalid')
            ids={r['id'] for r in rules}
            variant=dict(hardcore='Hardcore' in ids,ssf='NoParties' in ids,rules=sorted(ids),category=(raw.get('category') or {}).get('id'))
            state=lifecycle(raw,now)
        elif provider=='poe.ninja':
            # Documented as active economy leagues. Absence is handled only
            # after publishing a complete, validated catalog snapshot.
            variant=dict(hardcore=name.startswith('HC ') or name=='Hardcore',ssf=None);state='active'
        else:raise PriceError('catalog_invalid')
        rows.append(dict(external_id=identity,name=name,game='poe2',realm='pc',variant_json=canonical(variant),lifecycle=state,payload_json=canonical(raw)))
    return rows


class GGGLeaguesClient:
    def __init__(self,database,configuration,opener=None,clock=time.time):
        from urllib.request import build_opener
        from .ggg_history import NoRedirect
        self.database=database;self.configuration=configuration;self.opener=opener or build_opener(NoRedirect()).open;self.clock=clock
    def fetch(self,path):
        url=GGG_ROOT+path;now=self.clock()
        with connect(self.database,readonly=True) as c:cached=c.execute('SELECT * FROM league_catalog_http_cache WHERE url=?',(url,)).fetchone()
        if cached and cached['expires_at']>now:
            if cached['error_code']:raise PriceError(cached['error_code'])
            return json.loads(cached['body'])
        token,agent=self.configuration;headers={'Authorization':'Bearer '+token,'User-Agent':agent,'Accept':'application/json'}
        if cached and cached['etag']:headers['If-None-Match']=cached['etag']
        body=None;etag=None;error=None;delay=3600
        try:
            with self.opener(Request(url,headers=headers),timeout=20) as response:
                raw=response.read(4*1024*1024+1)
                if len(raw)>4*1024*1024:raise PriceError('catalog_invalid')
                body=raw.decode('utf-8');json.loads(body);etag=response.headers.get('ETag')
                age=re.search(r'(?:s-maxage|max-age)=(\d+)',response.headers.get('Cache-Control',''))
                if age:delay=max(delay,int(age[1]))
        except HTTPError as failure:
            if failure.code==304 and cached and cached['body']:body=cached['body'];etag=cached['etag']
            else:
                error='ggg_catalog_unauthorized' if failure.code in (401,403) else 'ggg_catalog_limited' if failure.code==429 else 'ggg_catalog_unavailable'
                retry=(failure.headers or {}).get('Retry-After','')
                if retry.isdigit():delay=max(delay,int(retry))
                elif retry:
                    from email.utils import parsedate_to_datetime
                    try:delay=max(delay,int(parsedate_to_datetime(retry).timestamp()-now))
                    except (TypeError,ValueError,OverflowError):pass
        except (URLError,OSError,ValueError,UnicodeError,PriceError):error='ggg_catalog_unavailable'
        with connect(self.database) as c:c.execute('INSERT OR REPLACE INTO league_catalog_http_cache VALUES(?,?,?,?,?,?)',(url,body or (cached['body'] if cached else None),etag or (cached['etag'] if cached else None),now+delay,utc_now(),error))
        if error:raise PriceError(error)
        return json.loads(body)
    def leagues(self,known,stop):
        result={}
        for kind in ('main','event'):
            for offset in range(0,1000,50):
                if stop.is_set():raise PriceError('interrupted')
                response=self.fetch('/league?'+urlencode(dict(realm='poe2',type=kind,limit=50,offset=offset)))
                page=response.get('leagues') if isinstance(response,dict) else None
                if not isinstance(page,list) or len(page)>50:raise PriceError('catalog_invalid')
                for raw in page:
                    if not isinstance(raw,dict) or not isinstance(raw.get('id'),str) or raw['id'] in result:raise PriceError('catalog_invalid')
                    result[raw['id']]={**raw,'_list':kind}
                if len(page)<50:break
            else:raise PriceError('catalog_incomplete')
        names={row.get('name') or row['id'] for row in result.values()}
        for name in known:
            if name in names:continue
            response=self.fetch('/league/'+quote(name,safe='')+'?realm=poe2')
            raw=response.get('league') if isinstance(response,dict) else None
            if raw is not None:
                if not isinstance(raw,dict) or not isinstance(raw.get('id'),str):raise PriceError('catalog_invalid')
                result[raw['id']]=raw
        return list(result.values())


def matched_league(c,provider,row):
    mapped=c.execute('SELECT l.* FROM leagues l JOIN league_external_ids e ON e.league_id=l.id WHERE e.provider=? AND e.external_id=? AND l.game=? AND l.realm=?',(provider,row['external_id'],row['game'],row['realm'])).fetchall()
    if len(mapped)>1:raise PriceError('catalog_mapping_ambiguous')
    if mapped:return mapped[0]
    return c.execute('SELECT * FROM leagues WHERE game=? AND realm=? AND name=?',(row['game'],row['realm'],row['name'])).fetchone()


def automatic_status(c,league):
    """Derive status and provenance from the last successful source snapshot.

    Keep provider evidence in its existing catalog tables; the legacy observed
    fields retain GGG/owner observations without mislabelling Ninja as GGG.
    """
    fallback=dict(observed_lifecycle=league['observed_lifecycle'],observed_source=league['observed_source'],observed_at=league['observed_at'])
    if (league['game'],league['realm'])!=('poe2','pc'):return fallback
    observation=c.execute("SELECT observed_at FROM catalog_observations WHERE provider='poe.ninja' AND kind='leagues' ORDER BY id DESC LIMIT 1").fetchone()
    if not observation:return fallback
    # A newer explicit GGG observation can supersede the economy snapshot.
    if league['observed_source']=='ggg' and league['observed_lifecycle']!='unknown' and (league['observed_at'] or '')>=observation['observed_at']:
        return fallback
    for candidate in c.execute("SELECT * FROM league_catalog_entries WHERE provider='poe.ninja' AND game=? AND realm=? AND present=1",(league['game'],league['realm'])):
        matched=matched_league(c,'poe.ninja',candidate)
        if matched and matched['id']==league['id']:
            return dict(observed_lifecycle='active',observed_source='poe.ninja',observed_at=observation['observed_at'])
    return dict(observed_lifecycle='ended',observed_source='poe.ninja',observed_at=observation['observed_at'])


def apply_observed_status(c,league_id):
    league=c.execute('SELECT * FROM leagues WHERE id=?',(league_id,)).fetchone()
    override=c.execute('SELECT lifecycle_override FROM league_policies WHERE league_id=?',(league_id,)).fetchone()
    state=override[0] if override and override[0] is not None else automatic_status(c,league)['observed_lifecycle']
    c.execute('UPDATE leagues SET lifecycle=? WHERE id=?',(state,league_id))


def publish_catalog(c,provider,rows,payload,observed_at=None):
    stamp=observed_at or utc_now()
    observation=c.execute('INSERT INTO catalog_observations(provider,kind,observed_at,payload_json) VALUES(?,?,?,?)',(provider,'leagues',stamp,canonical(payload))).lastrowid
    c.execute('UPDATE league_catalog_entries SET present=0 WHERE provider=?',(provider,))
    for row in rows:
        c.execute('INSERT INTO league_catalog_entries VALUES(?,?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(provider,game,realm,external_id) DO UPDATE SET name=excluded.name,variant_json=excluded.variant_json,lifecycle=excluded.lifecycle,last_seen=excluded.last_seen,present=1,observation_id=excluded.observation_id,payload_json=excluded.payload_json',
                  (provider,row['external_id'],row['game'],row['realm'],row['name'],row['variant_json'],row['lifecycle'],stamp,stamp,observation,row['payload_json']))
        league=matched_league(c,provider,row)
        if league:
            c.execute('INSERT OR IGNORE INTO league_external_ids VALUES(?,?,?)',(league['id'],provider,row['external_id']))
            if provider=='ggg' and row['lifecycle']!='unknown':
                c.execute("UPDATE leagues SET observed_lifecycle=?,variant_json=?,observed_source='ggg',observed_at=? WHERE id=?",(row['lifecycle'],row['variant_json'],stamp,league['id']))
    if provider=='poe.ninja':
        c.execute("UPDATE league_catalog_entries SET lifecycle='ended' WHERE provider='poe.ninja' AND present=0")
    # Re-evaluate missing leagues as well as the ones present in this snapshot.
    for league in c.execute('SELECT id FROM leagues').fetchall():apply_observed_status(c,league['id'])
    return observation


class LeagueCatalogAdapter:
    def stage(self,queue,job,stop):
        outcomes=[]
        try:
            payload=json.loads(NinjaClient(queue.path).fetch(NINJA_ROOT+'/poe2/api/economy/leagues'))
            outcomes.append(('poe.ninja',parse_catalog('poe.ninja',payload),payload,None))
        except (PriceError,ValueError,TypeError) as error:outcomes.append(('poe.ninja',None,None,getattr(error,'code','catalog_invalid')))
        configuration=ggg_configuration()
        if configuration:
            try:
                with connect(queue.path,readonly=True) as c:known=[r[0] for r in c.execute("SELECT name FROM leagues WHERE game='poe2' AND realm='pc'")]
                payload=GGGLeaguesClient(queue.path,configuration).leagues(known,stop)
                outcomes.append(('ggg',parse_catalog('ggg',payload),payload,None))
            except (PriceError,ValueError,TypeError) as error:outcomes.append(('ggg',None,None,getattr(error,'code','catalog_invalid')))
        else:outcomes.append(('ggg',None,None,'ggg_catalog_unconfigured'))
        def publish(c):
            updated=0;errors=[]
            for provider,rows,payload,error in outcomes:
                if error:errors.append(dict(provider=provider,error=error))
                else:publish_catalog(c,provider,rows,payload);updated+=1
                c.execute('INSERT INTO league_catalog_sources VALUES(?,?,?,?) ON CONFLICT(provider) DO UPDATE SET attempted_at=excluded.attempted_at,last_success_at=COALESCE(excluded.last_success_at,league_catalog_sources.last_success_at),error_code=excluded.error_code',(provider,utc_now(),utc_now() if rows is not None else None,error))
            return dict(updated_sources=updated,errors=errors)
        return publish
