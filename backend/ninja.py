"""Isolated, cached adapter for the documented poe.ninja economy surface."""
from html.parser import HTMLParser
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .database import connect, utc_now

ROOT = 'https://poe.ninja'
DOCS = ROOT + '/docs/api'
USER_AGENT = 'PathOfAccounting/1.0 (+https://dyyyl.ovh/poe2guild/)'


class PriceError(ValueError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)


class CategoryDocument(HTMLParser):
    """Only accept table rows in explicitly identified PoE 2 economy sections."""
    def __init__(self):
        super().__init__();self.section=None;self.game=None;self.heading=None;self.text=[];self.cells=[];self.cell=None;self.categories=[];self.accepting=False
    def handle_starttag(self,tag,attrs):
        if tag in ('h2','h3','h4'):self.heading=tag;self.text=[]
        if tag=='tr':self.cells=[]
        if tag in ('td','th'):self.cell=[]
    def handle_data(self,data):
        if '/poe2/api/economy/exchange/current/overview' in data:self.section='exchange';self.game=None
        if '/poe2/api/economy/stash/current/item/overview' in data:self.section='stash';self.game=None
        if '/poe1/api/economy/stash/current/currency/overview' in data:self.section=None;self.game=None
        if self.heading:self.text.append(data)
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag==self.heading:
            value=' '.join(''.join(self.text).split()).casefold()
            if tag=='h2':self.section='exchange' if value=='exchange overview' else 'stash' if value=='stash item overview' else None;self.game=None
            if tag=='h3':
                self.accepting=value=='accepted type values'
                self.game=None
            if tag=='h4':self.game=2 if value=='poe 2' else 1 if value=='poe 1' else None
            self.heading=None
        if tag in ('td','th') and self.cell is not None:self.cells.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.section and self.accepting and self.game==2 and len(self.cells)==2:
            key,label=self.cells
            if re.fullmatch('[A-Za-z][A-Za-z0-9]{0,79}',key) and key!='Value':self.categories.append(dict(feed=self.section,category=key,label=label))


def parse_catalog(body):
    parser=CategoryDocument();parser.feed(body)
    result=parser.categories
    # A changed/empty document is an error, never an empty replacement catalog.
    if len(result)<2 or {row['feed'] for row in result}!={'exchange','stash'} or len({(r['feed'],r['category']) for r in result})!=len(result):
        raise PriceError('category_catalog_invalid')
    return result


class NinjaClient:
    def __init__(self,database,opener=urlopen,clock=time.time):self.database=database;self.opener=opener;self.clock=clock
    def fetch(self,url,minimum=3600):
        if not (url==DOCS or url.startswith(ROOT+'/poe2/api/economy/')):raise PriceError('price_url_rejected')
        now=self.clock()
        with connect(self.database,readonly=True) as c:cached=c.execute('SELECT * FROM price_http_cache WHERE url=?',(url,)).fetchone()
        if cached and cached['expires_at']>now:
            if cached['error_code']:raise PriceError(cached['error_code'])
            return cached['body']
        headers={'User-Agent':USER_AGENT,'Accept':'application/json, text/html'}
        if cached and cached['etag']:headers['If-None-Match']=cached['etag']
        body=None;etag=None;error=None;delay=minimum
        try:
            with self.opener(Request(url,headers=headers),timeout=20) as response:
                if response.status!=200:raise PriceError('price_source_unavailable')
                raw=response.read(16*1024*1024+1)
                if len(raw)>16*1024*1024:raise PriceError('price_response_too_large')
                body=raw.decode('utf-8');etag=response.headers.get('ETag')
                age=re.search(r'(?:s-maxage|max-age)=(\d+)',response.headers.get('Cache-Control',''))
                if age:delay=max(delay,int(age[1]))
        except HTTPError as failure:
            if failure.code==304 and cached and cached['body']:
                body=cached['body'];etag=cached['etag']
            else:
                error='price_source_limited' if failure.code==429 else 'price_source_unavailable'
                retry=(failure.headers or {}).get('Retry-After','')
                if retry.isdigit():delay=max(delay,int(retry))
                elif retry:
                    from email.utils import parsedate_to_datetime
                    try:delay=max(delay,int(parsedate_to_datetime(retry).timestamp()-now))
                    except (TypeError,ValueError,OverflowError):pass
        except (URLError,OSError,UnicodeError,PriceError):error='price_source_unavailable'
        with connect(self.database) as c:
            c.execute('INSERT OR REPLACE INTO price_http_cache VALUES(?,?,?,?,?,?)',(url,body or (cached['body'] if cached else None),etag or (cached['etag'] if cached else None),now+delay,utc_now(),error))
        if error:raise PriceError(error)
        return body
    def catalog(self):return parse_catalog(self.fetch(DOCS,86400))
    def league_id(self,name):
        try:data=json.loads(self.fetch(ROOT+'/poe2/api/economy/leagues'))
        except (ValueError,TypeError):raise PriceError('price_leagues_invalid')
        if not isinstance(data,list):raise PriceError('price_leagues_invalid')
        rows=[row for row in data if isinstance(row,dict) and row.get('name')==name and isinstance(row.get('id'),str)]
        if len(rows)!=1:raise PriceError('price_league_unavailable')
        return rows[0]['id']
    def prices(self,league,category):
        from urllib.parse import urlencode
        path='/poe2/api/economy/'+('exchange/current/overview' if category['feed']=='exchange' else 'stash/current/item/overview')
        try:return json.loads(self.fetch(ROOT+path+'?'+urlencode({'league':league,'type':category['category']})))
        except (ValueError,TypeError):raise PriceError('price_payload_invalid')
