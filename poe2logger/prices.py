import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime

from .config import POE_NINJA_PRICE_URL, PRICE_CACHE_DIR, PRICE_CACHE_MAX_AGE_HOURS, PRICE_TYPES
from .private_config import LEAGUE_NAME
from . import state
from .state import log_events, movement_log, player_value_timeline, price_metadata, stash_value_timeline, unpriced_summary, valuation_summary
from .utils import display_event_datetime, parse_event_date

def normalize_price_key(item_name):
    """Normalize item names for price lookups."""
    return re.sub(r'[^a-z0-9]+', '-', item_name.lower()).strip('-')


def price_cache_path(price_type):
    """Return the cache file path for a poe.ninja category."""
    safe_type = normalize_price_key(price_type)
    return os.path.join(PRICE_CACHE_DIR, f'{safe_type}.json')


def load_cached_prices(price_type, allow_stale=False):
    """Load a cached poe.ninja response when it is fresh enough, or stale if requested."""
    path = price_cache_path(price_type)
    if not os.path.exists(path):
        return None
    
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    if not allow_stale and age_hours > PRICE_CACHE_MAX_AGE_HOURS:
        return None
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def fetch_price_payload(price_type):
    """Fetch a poe.ninja category with a local cache to keep API usage low."""
    if not state.force_price_fetch:
        cached = load_cached_prices(price_type)
        if cached is not None:
            price_metadata[price_type] = 'fresh cache'
            return cached
    
    params = urllib.parse.urlencode({'league': LEAGUE_NAME, 'type': price_type})
    url = f'{POE_NINJA_PRICE_URL}?{params}'
    request = urllib.request.Request(url, headers={'User-Agent': 'Poe2Logger/1.0'})
    
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode('utf-8'))
        
        if not os.path.exists(PRICE_CACHE_DIR):
            os.makedirs(PRICE_CACHE_DIR)
        
        with open(price_cache_path(price_type), 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        
        price_metadata[price_type] = 'force fetched' if state.force_price_fetch else 'fetched'
        return payload
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        stale = load_cached_prices(price_type, allow_stale=True)
        if stale is not None:
            price_metadata[price_type] = f'stale cache ({e})'
            return stale
        
        price_metadata[price_type] = f'unavailable ({e})'
        return None


def build_price_index():
    """Build an item-name price index from the cached poe.ninja category payloads."""
    price_index = {}
    
    for price_type in PRICE_TYPES:
        payload = fetch_price_payload(price_type)
        if not payload:
            continue
        
        items_by_id = {item.get('id'): item for item in payload.get('items', [])}
        for line in payload.get('lines', []):
            item_id = line.get('id')
            item = items_by_id.get(item_id, {})
            item_name = item.get('name')
            
            if not item_name:
                continue
            
            price_data = {
                'name': item_name,
                'type': price_type,
                'primary_value': float(line.get('primaryValue') or 0),
                'sparkline': line.get('sparkline', {}).get('data') or [],
            }
            price_index[normalize_price_key(item_name)] = price_data
            if item.get('detailsId'):
                price_index[normalize_price_key(item['detailsId'])] = price_data
    
    return price_index


def estimate_price_at_event(price_data, event_date, latest_event_date):
    """Estimate historical divine value using poe.ninja's short sparkline when available."""
    current_value = price_data['primary_value']
    
    if price_data.get('name') == 'Divine Orb':
        return 1.0
    
    sparkline = price_data.get('sparkline') or []
    
    if not sparkline or latest_event_date == datetime.min or event_date == datetime.min:
        return current_value
    
    days_ago = (latest_event_date.date() - event_date.date()).days
    index = len(sparkline) - 1 - days_ago
    
    if index < 0 or index >= len(sparkline):
        return current_value
    
    current_change = sparkline[-1]
    event_change = sparkline[index]
    
    if current_change is None or event_change is None or current_change <= -100 or event_change <= -100:
        return current_value
    
    return current_value * ((1 + event_change / 100) / (1 + current_change / 100))


def add_valuation_entry(account, stash, item_name, quantity, event_date, direction, price_index, latest_event_date):
    """Add one valued movement into the valuation summaries."""
    if quantity <= 0:
        return 0.0
    
    item_data = valuation_summary[stash][account][item_name]
    key = normalize_price_key(item_name)
    price_data = price_index.get(key)
    
    if direction == 'added':
        item_data['added_qty'] += quantity
    else:
        item_data['removed_qty'] += quantity
    
    if not price_data or price_data['primary_value'] <= 0:
        unpriced = unpriced_summary[item_name]
        if direction == 'added':
            unpriced['added_qty'] += quantity
        else:
            unpriced['removed_qty'] += quantity
        return 0.0
    
    value = quantity * estimate_price_at_event(price_data, event_date, latest_event_date)
    
    if direction == 'added':
        item_data['added_value'] += value
        item_data['priced_added_qty'] += quantity
    else:
        item_data['removed_value'] += value
        item_data['priced_removed_qty'] += quantity
    
    return value


def calculate_valuation_summary():
    """Replay log events chronologically and estimate total value added/removed."""
    price_index = build_price_index()
    latest_event_date = max((event['parsed_date'] for event in log_events), default=datetime.min)
    state = {}
    player_cumulative = defaultdict(float)
    stash_cumulative = defaultdict(float)
    movement_log.clear()
    
    def apply_value_change(event, item_name, quantity, direction):
        value = add_valuation_entry(
            event['account'], event['stash'], item_name, quantity,
            event['parsed_date'], direction, price_index, latest_event_date
        )
        signed_value = value if direction == 'added' else -value
        movement_log.append({
            'date': event['date'],
            'parsed_date': event['parsed_date'],
            'parsed_id': event['parsed_id'],
            'account': event['account'],
            'stash': event['stash'],
            'action': direction,
            'source_action': event['action'],
            'item_name': item_name,
            'quantity': quantity,
            'x': event['x'],
            'y': event['y'],
            'rate': value / quantity if quantity else 0.0,
            'value': signed_value,
        })
        if value <= 0:
            return
        
        if direction == 'added':
            player_cumulative[event['account']] += value
            stash_cumulative[event['stash']] += value
        else:
            player_cumulative[event['account']] -= value
            stash_cumulative[event['stash']] -= value
        
        if event['parsed_date'] != datetime.min:
            player_value_timeline[event['account']].append((
                event['parsed_date'],
                player_cumulative[event['account']],
            ))
            stash_value_timeline[event['stash']].append((
                event['parsed_date'],
                stash_cumulative[event['stash']],
            ))
    
    for event in sorted(log_events, key=lambda e: (e['parsed_date'], e['parsed_id'])):
        coord_key = (event['stash'], event['x'], event['y'])
        current = state.get(coord_key)
        current_quantity = current['quantity'] if current else 0
        current_item = current['item_name'] if current else ''
        action = event['action']
        quantity = event['quantity']
        item_name = event['item_name']
        
        if action == 'added':
            if current_item and current_item != item_name:
                apply_value_change(event, current_item, current_quantity, 'removed')
                current_quantity = 0
            apply_value_change(event, item_name, quantity, 'added')
            state[coord_key] = {'quantity': current_quantity + quantity, 'item_name': item_name}
        elif action == 'removed':
            apply_value_change(event, item_name, quantity, 'removed')
            new_quantity = current_quantity - quantity if current_item == item_name else 0
            if new_quantity > 0:
                state[coord_key] = {'quantity': new_quantity, 'item_name': item_name}
            else:
                state.pop(coord_key, None)
        elif action == 'modified':
            if current_item and current_item != item_name:
                apply_value_change(event, current_item, current_quantity, 'removed')
                current_quantity = 0
            
            delta = quantity - current_quantity
            if delta > 0:
                apply_value_change(event, item_name, delta, 'added')
            elif delta < 0:
                apply_value_change(event, item_name, abs(delta), 'removed')
            
            if quantity > 0:
                state[coord_key] = {'quantity': quantity, 'item_name': item_name}
            else:
                state.pop(coord_key, None)

