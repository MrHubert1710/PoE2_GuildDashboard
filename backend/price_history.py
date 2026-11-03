"""Dated daily economy samples, preserving provider payloads and clock anchors."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal,ROUND_HALF_EVEN
from email.utils import parsedate_to_datetime
import hashlib
from .archive_import import canonical
from .database import utc_now
from .ninja import PriceError
from .prices import ATOMIC,CURRENCY,amount,name_key


def timestamp(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:raise ValueError()
        return result.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    except (ValueError,TypeError,AttributeError,OverflowError):raise PriceError('price_history_time_invalid') from None


def history_snapshot(league,category,item,response,*,references=None,primary='divine'):
    feed=category['feed'];payload=response['payload'];points=[]
    if feed=='exchange':
        if not isinstance(payload,dict) or not isinstance(payload.get('pairs'),list) or payload.get('item',{}).get('id')!=item['id']:
            raise PriceError('price_history_invalid')
        pairs=payload['pairs']
        if item['id']=='divine':
            points=[(timestamp(p['timestamp']),Decimal(1)) for pair in pairs for p in pair.get('history',[])]
        else:
            divine=[pair for pair in pairs if pair.get('id')=='divine']
            if len(divine)!=1:raise PriceError('price_history_currency_unknown')
            points=[(timestamp(p['timestamp']),amount(p['rate'])) for p in divine[0].get('history',[])]
        variant=None;identity=str(item['id'])
    elif feed=='stash':
        if not isinstance(payload,list):raise PriceError('price_history_invalid')
        headers=response.get('headers',{})
        try:
            anchor=datetime.fromisoformat(headers['X-League-EndAt'].replace('Z','+00:00')) if headers.get('X-League-EndAt') else parsedate_to_datetime(headers['Date'])
            if anchor.tzinfo is None:raise ValueError()
            anchor=anchor.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError):raise PriceError('price_history_time_invalid') from None
        for point in payload:
            days=point.get('daysAgo')
            if type(days) is not int or not 0<=days<=20000:raise PriceError('price_history_time_invalid')
            at=timestamp((anchor-timedelta(days=days)).isoformat())
            price=amount(point.get('value'))
            if primary!='divine':
                # Never convert a dated price with today's cross-rate.
                rate=(references or {}).get(primary,{}).get(at)
                if rate is None:continue
                price*=rate
            points.append((at,price))
        variant=canonical({k:item[k] for k in ('variant','corrupted','gemLevel','gemQuality','links') if item.get(k) not in (None,False,'')})
        if variant=='{}':variant=None
        identity=str(item['id'])
    else:raise PriceError('price_history_invalid')
    if not points:raise PriceError('price_history_empty')
    samples={}
    for at,price in points:
        if price>Decimal(10**9):raise PriceError('price_payload_invalid')
        atomic=str(int((price*ATOMIC).quantize(Decimal(1),rounding=ROUND_HALF_EVEN)))
        if at in samples and samples[at]!=atomic:raise PriceError('price_history_invalid')
        samples[at]=atomic
    # Relative days depend on source headers; immutable payload includes that anchor.
    source={key:value for key,value in response.items() if key!='retrieved_at'}
    raw=canonical(dict(source=source,item=item,primary=primary,normalized_samples=samples))
    digest=hashlib.sha256(raw.encode()).hexdigest()
    sid=hashlib.sha256(canonical([league,feed,category['category'],digest,'history_daily']).encode()).hexdigest()
    quotes=[dict(quote_key=identity+'@'+at,name=item['name'],name_key=name_key(item['name']),price_atomic=price,variant=variant,effective_at=at) for at,price in sorted(samples.items())]
    return dict(id=sid,league_id=league,feed=feed,category=category['category'],observed_at=response.get('retrieved_at') or utc_now(),effective_at=None,
                provenance='history_daily',sha256=digest,payload_json=raw,currency=CURRENCY,quotes=quotes)
