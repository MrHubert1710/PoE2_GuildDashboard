import csv
from collections import defaultdict
import re
from datetime import datetime, timezone, timedelta
import os
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import html
import math

# Configuration
LOG_DIR = 'logs'
HISTORY_FILENAME = 'history.csv'
CSV_FIELDNAMES = ['Date', 'Id', 'League', 'Account', 'Action', 'Stash', 'Item', 'X', 'Y']
LEAGUE_NAME = 'Runes of Aldur'
DISPLAY_TIMEZONE = timezone(timedelta(hours=2), 'CEST')
TARGET_STASHES = {'$$$', 'Deli', 'Ess', 'Aug', 'Ritual', 'Abbys/Expedition'}
STASH_ALIASES = {
    'Abbys/Expediton': 'Abbys/Expedition',
}
OUTPUT_DIR = 'stash_reports'
CHART_DIR = os.path.join(OUTPUT_DIR, 'charts')
PRICE_CACHE_DIR = os.path.join(OUTPUT_DIR, 'price_cache')
PRICE_CACHE_MAX_AGE_HOURS = 12
POE_NINJA_PRICE_URL = 'https://poe.ninja/poe2/api/economy/exchange/current/overview'
PRICE_TYPES = ['Currency', 'Essences', 'Runes', 'Ritual', 'Delirium', 'Abyss', 'Expedition', 'Verisium']

# Data structures
# player -> item_name -> {'added': count, 'removed': count}
player_summary = defaultdict(lambda: defaultdict(lambda: {'added': 0, 'removed': 0}))
# stash -> account -> item_name -> {'added': count, 'removed': count}
stash_summary = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'added': 0, 'removed': 0})))
coordinate_state = {}  # (stash, x, y) -> (current_quantity, item_name)
log_events = []
movement_log = []
final_stash_state = {}
valuation_summary = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
    'added_qty': 0,
    'removed_qty': 0,
    'added_value': 0.0,
    'removed_value': 0.0,
    'priced_added_qty': 0,
    'priced_removed_qty': 0,
})))
unpriced_summary = defaultdict(lambda: {'added_qty': 0, 'removed_qty': 0})
price_metadata = {}
player_value_timeline = defaultdict(list)
stash_value_timeline = defaultdict(list)
player_chart_files = {}
stash_chart_files = {}


def extract_quantity(item_string):
    """Extract quantity from item string like '67x Greater Glacial Rune'."""
    match = re.match(r'(\d+)\s*[x×Ă—]\s*(.+)', item_string.strip(), re.IGNORECASE)
    if match:
        return int(match.group(1)), match.group(2).strip()
    return 1, item_string.strip()  # Default to 1 if no quantity specified


def get_csv_value(row, field_name, default=''):
    """Read a CSV field while tolerating BOM or hidden header characters."""
    if field_name in row:
        return row[field_name]
    
    normalized_name = field_name.strip().lstrip('\ufeff').lower()
    for key, value in row.items():
        if key.strip().lstrip('\ufeff').lower() == normalized_name:
            return value
    
    return default


def get_csv_league(row, fieldnames):
    """Read the league from the CSV, falling back to the third column."""
    league = get_csv_value(row, 'League').strip()
    if league:
        return league
    if fieldnames and len(fieldnames) >= 3:
        return row.get(fieldnames[2], '').strip()
    return ''


def normalize_stash_name(stash_name):
    """Normalize known stash name typos from the log."""
    return STASH_ALIASES.get(stash_name, stash_name)


def safe_chart_filename(prefix, value):
    """Make chart filenames safe for filesystem paths and HTML src attributes."""
    safe_value = re.sub(r'[^A-Za-z0-9._$-]+', '_', value).strip('_')
    return f'{prefix}_{safe_value or "unnamed"}.svg'


def chart_output_path(filename):
    """Return the filesystem path for a chart asset."""
    return os.path.join(CHART_DIR, filename)


def chart_asset_src(filename):
    """Return the dashboard-relative src path for a chart asset."""
    return '/'.join([OUTPUT_DIR, 'charts', filename])


def target_stash_label():
    """Return the configured target stashes as display text."""
    return ', '.join(sorted(TARGET_STASHES))


def parse_event_date(date_string):
    """Parse the CSV date into a sortable value."""
    try:
        return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
    except ValueError:
        return datetime.min


def parse_event_id(id_string):
    """Parse the CSV id into a sortable value."""
    try:
        return int(id_string)
    except ValueError:
        return 0


def display_event_datetime(date_value):
    """Convert a parsed event datetime from UTC to the dashboard display timezone."""
    if date_value == datetime.min:
        return date_value
    
    if date_value.tzinfo is None:
        date_value = date_value.replace(tzinfo=timezone.utc)
    
    return date_value.astimezone(DISPLAY_TIMEZONE)


def latest_dashboard_date():
    """Return the latest operation date in the dashboard display timezone."""
    latest_event_date = max((event['parsed_date'] for event in log_events), default=datetime.now(DISPLAY_TIMEZONE))
    if latest_event_date == datetime.min:
        latest_event_date = datetime.now(DISPLAY_TIMEZONE)
    return display_event_datetime(latest_event_date)


def dashboard_filename():
    """Return the dashboard filename based on the day/month of the latest operation."""
    latest_event_date = latest_dashboard_date()
    return f'GuildReport_{latest_event_date:%d%m}.html'


def dashboard_title():
    """Return the dashboard title based on the latest operation date."""
    latest_event_date = latest_dashboard_date()
    return f'Guild Report - {latest_event_date:%d.%m}'


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
        
        price_metadata[price_type] = 'fetched'
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


def add_operation_entry(account, stash, item_name, quantity, direction):
    """Add one quantity movement into player and stash operation summaries."""
    if quantity <= 0:
        return
    
    if direction == 'added':
        player_summary[account][item_name]['added'] += quantity
        stash_summary[stash][account][item_name]['added'] += quantity
    else:
        player_summary[account][item_name]['removed'] += quantity
        stash_summary[stash][account][item_name]['removed'] += quantity


def calculate_operation_summaries():
    """Replay log events chronologically to calculate per-item add/remove quantities."""
    player_summary.clear()
    stash_summary.clear()
    coordinate_state.clear()
    
    for event in sorted(log_events, key=lambda e: (e['parsed_date'], e['parsed_id'])):
        coord_key = (event['stash'], event['x'], event['y'])
        current_quantity, current_item = coordinate_state.get(coord_key, (0, ''))
        action = event['action']
        quantity = event['quantity']
        item_name = event['item_name']
        
        if action == 'added':
            if current_item and current_item != item_name:
                add_operation_entry(event['account'], event['stash'], current_item, current_quantity, 'removed')
                current_quantity = 0
            add_operation_entry(event['account'], event['stash'], item_name, quantity, 'added')
            coordinate_state[coord_key] = (current_quantity + quantity, item_name)
        elif action == 'removed':
            add_operation_entry(event['account'], event['stash'], item_name, quantity, 'removed')
            new_quantity = current_quantity - quantity if current_item == item_name else 0
            if new_quantity > 0:
                coordinate_state[coord_key] = (new_quantity, item_name)
            else:
                coordinate_state.pop(coord_key, None)
        elif action == 'modified':
            if current_item and current_item != item_name:
                add_operation_entry(event['account'], event['stash'], current_item, current_quantity, 'removed')
                current_quantity = 0
            
            delta = quantity - current_quantity
            if delta > 0:
                add_operation_entry(event['account'], event['stash'], item_name, delta, 'added')
            elif delta < 0:
                add_operation_entry(event['account'], event['stash'], item_name, abs(delta), 'removed')
            
            if quantity > 0:
                coordinate_state[coord_key] = (quantity, item_name)
            else:
                coordinate_state.pop(coord_key, None)


def calculate_final_stash_state():
    """Replay log events in chronological order to calculate final stash contents."""
    global final_stash_state
    state = {}
    
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
                current_quantity = 0
            new_quantity = current_quantity + quantity
        elif action == 'modified':
            new_quantity = quantity
        elif action == 'removed':
            new_quantity = current_quantity - quantity if current_item == item_name else 0
        else:
            continue
        
        if new_quantity > 0:
            state[coord_key] = {
                'quantity': new_quantity,
                'item_name': item_name,
                'account': event['account'],
                'date': event['date'],
                'action': action,
            }
        else:
            state.pop(coord_key, None)
    
    final_stash_state = state


def reset_report_data():
    """Clear derived data before processing source log files."""
    player_summary.clear()
    stash_summary.clear()
    coordinate_state.clear()
    log_events.clear()
    movement_log.clear()
    final_stash_state.clear()
    valuation_summary.clear()
    unpriced_summary.clear()
    price_metadata.clear()
    player_value_timeline.clear()
    stash_value_timeline.clear()
    player_chart_files.clear()
    stash_chart_files.clear()


def discover_log_files():
    """Return all CSV files in the log directory, independent of filename."""
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    return [
        os.path.join(LOG_DIR, filename)
        for filename in sorted(os.listdir(LOG_DIR))
        if os.path.isfile(os.path.join(LOG_DIR, filename)) and filename.lower().endswith('.csv')
    ]


def history_file_path():
    """Return the canonical merged history path."""
    return os.path.join(LOG_DIR, HISTORY_FILENAME)


def build_raw_event_key(row):
    """Build a stable identity for de-duplicating raw CSV transactions."""
    return tuple(row[field_name] for field_name in CSV_FIELDNAMES)


def normalize_transaction_row(row, fieldnames):
    """Return a canonical current-league CSV row, or None if it should not be kept."""
    league = get_csv_league(row, fieldnames)
    if league != LEAGUE_NAME:
        return None
    
    normalized = {
        'Date': get_csv_value(row, 'Date').strip(),
        'Id': get_csv_value(row, 'Id').strip(),
        'League': league,
        'Account': get_csv_value(row, 'Account').strip(),
        'Action': get_csv_value(row, 'Action').strip(),
        'Stash': normalize_stash_name(get_csv_value(row, 'Stash').strip()),
        'Item': get_csv_value(row, 'Item').strip(),
        'X': get_csv_value(row, 'X').strip(),
        'Y': get_csv_value(row, 'Y').strip(),
    }
    
    if any(normalized[field_name] == '' for field_name in CSV_FIELDNAMES):
        return None
    
    return normalized


def merge_log_files():
    """Merge source CSV files into history.csv and remove redundant CSV files."""
    log_files = discover_log_files()
    history_path = history_file_path()
    
    if not log_files:
        return []
    
    if log_files == [history_path]:
        return log_files
    
    merged_rows = {}
    total_rows = 0
    skipped_rows = 0
    duplicate_rows = 0
    read_failed = False
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                
                if reader.fieldnames is None:
                    print(f"Warning: '{log_file}' appears to be empty, skipping")
                    continue
                
                for row in reader:
                    total_rows += 1
                    normalized = normalize_transaction_row(row, reader.fieldnames)
                    if normalized is None:
                        skipped_rows += 1
                        continue
                    
                    event_key = build_raw_event_key(normalized)
                    if event_key in merged_rows:
                        duplicate_rows += 1
                        continue
                    merged_rows[event_key] = normalized
        except OSError as e:
            print(f"Warning: Could not read '{log_file}': {e}")
            read_failed = True
    
    if read_failed:
        print("Warning: Log merge skipped because at least one source file could not be read")
        return log_files
    
    ordered_rows = sorted(
        merged_rows.values(),
        key=lambda row: (parse_event_date(row['Date']), parse_event_id(row['Id']))
    )
    temp_history_path = f'{history_path}.tmp'
    
    with open(temp_history_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(ordered_rows)
    
    os.replace(temp_history_path, history_path)
    
    removed_files = 0
    for log_file in log_files:
        if os.path.abspath(log_file) == os.path.abspath(history_path):
            continue
        try:
            os.remove(log_file)
            removed_files += 1
        except OSError as e:
            print(f"Warning: Could not remove redundant log file '{log_file}': {e}")
    
    print(
        f"Merged {len(ordered_rows)} unique {LEAGUE_NAME} transactions into {history_path} "
        f"({duplicate_rows} duplicates skipped, {skipped_rows} rows skipped, {removed_files} redundant files removed)"
    )
    
    return [history_path]


def build_event_key(date_value, id_value, stash, account, action, item, x, y):
    """Build a stable identity for de-duplicating overlapping log files."""
    return (
        date_value,
        id_value,
        stash,
        account,
        action,
        item,
        str(x),
        str(y),
    )


def process_log():
    """Process all source log files and generate dashboard data."""
    reset_report_data()
    log_files = merge_log_files()
    
    if not log_files:
        print(f"No log files found in '{LOG_DIR}'")
        return
    
    total_rows = 0
    duplicate_rows = 0
    accepted_events = 0
    skipped_league_rows = 0
    seen_events = set()
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                
                if reader.fieldnames is None:
                    print(f"Warning: '{log_file}' appears to be empty, skipping")
                    continue
                
                file_rows = 0
                file_events = 0
                file_duplicates = 0
                file_skipped_league = 0
                for row in reader:
                    file_rows += 1
                    total_rows += 1
                    
                    row_league = get_csv_league(row, reader.fieldnames)
                    if row_league != LEAGUE_NAME:
                        skipped_league_rows += 1
                        file_skipped_league += 1
                        continue
                    
                    if any(get_csv_value(row, key) == '' for key in ['Stash', 'Account', 'Action', 'Item', 'X', 'Y']):
                        print(f"Warning: {log_file} row {file_rows} missing required fields, skipping")
                        continue
                    
                    stash = normalize_stash_name(get_csv_value(row, 'Stash').strip())
                    
                    if stash not in TARGET_STASHES:
                        continue
                    
                    account = get_csv_value(row, 'Account').strip()
                    action = get_csv_value(row, 'Action').strip()
                    item = get_csv_value(row, 'Item').strip()
                    
                    try:
                        x = int(get_csv_value(row, 'X').strip())
                        y = int(get_csv_value(row, 'Y').strip())
                    except ValueError:
                        print(f"Warning: {log_file} row {file_rows} has invalid X or Y coordinates, skipping")
                        continue
                    
                    date_value = get_csv_value(row, 'Date').strip()
                    id_value = get_csv_value(row, 'Id').strip()
                    event_key = build_event_key(date_value, id_value, stash, account, action, item, x, y)
                    if event_key in seen_events:
                        duplicate_rows += 1
                        file_duplicates += 1
                        continue
                    seen_events.add(event_key)
                    
                    quantity, item_name = extract_quantity(item)
                    log_events.append({
                        'date': date_value,
                        'parsed_date': parse_event_date(date_value),
                        'parsed_id': parse_event_id(id_value),
                        'stash': stash,
                        'account': account,
                        'action': action,
                        'quantity': quantity,
                        'item_name': item_name,
                        'x': x,
                        'y': y,
                    })
                    accepted_events += 1
                    file_events += 1
                
                print(
                    f"Processed {file_rows} rows from {log_file} "
                    f"({file_events} unique target events, {file_duplicates} duplicates, "
                    f"{file_skipped_league} other-league rows skipped)"
                )
        except OSError as e:
            print(f"Warning: Could not read '{log_file}': {e}")
    
    print(f"Processed {total_rows} rows from {len(log_files)} log files")
    print(f"Unique target events: {accepted_events} ({duplicate_rows} duplicates skipped)")
    print(f"Skipped rows from other leagues: {skipped_league_rows}")
    
    calculate_operation_summaries()
    calculate_final_stash_state()
    calculate_valuation_summary()


def nice_number(value, should_round):
    """Return a rounded 1/2/5/10-style number for chart axes."""
    if value <= 0:
        return 1.0
    
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)
    
    if should_round:
        if fraction < 1.5:
            nice_fraction = 1
        elif fraction < 3:
            nice_fraction = 2
        elif fraction < 7:
            nice_fraction = 5
        else:
            nice_fraction = 10
    else:
        if fraction <= 1:
            nice_fraction = 1
        elif fraction <= 2:
            nice_fraction = 2
        elif fraction <= 5:
            nice_fraction = 5
        else:
            nice_fraction = 10
    
    return nice_fraction * (10 ** exponent)


def calculate_value_axis(values, target_ticks=6):
    """Return rounded chart bounds and tick values for net divine value."""
    raw_min = min(0.0, min(values))
    raw_max = max(0.0, max(values))
    
    if raw_min == raw_max:
        spread = max(abs(raw_min) * 0.2, 1.0)
        raw_min -= spread
        raw_max += spread
    
    nice_range = nice_number(raw_max - raw_min, False)
    tick_step = nice_number(nice_range / max(target_ticks - 1, 1), True)
    axis_min = math.floor(raw_min / tick_step) * tick_step
    axis_max = math.ceil(raw_max / tick_step) * tick_step
    
    tick_values = []
    value = axis_min
    while value <= axis_max + (tick_step * 0.5):
        tick_values.append(0.0 if abs(value) < tick_step / 1000 else value)
        value += tick_step
    
    return axis_min, axis_max, tick_values, tick_step


def format_axis_value(value, tick_step):
    """Format a rounded chart tick value without noisy decimals."""
    if abs(value) < tick_step / 1000:
        value = 0.0
    
    if tick_step >= 1:
        return f'{value:.0f}'
    if tick_step >= 0.1:
        return f'{value:.1f}'
    if tick_step >= 0.01:
        return f'{value:.2f}'
    return f'{value:.3f}'


def ceil_to_hour_multiple(date_value, hour_step):
    """Round a datetime up to the next local hour multiple."""
    rounded = date_value.replace(minute=0, second=0, microsecond=0)
    if rounded < date_value:
        rounded += timedelta(hours=1)
    
    remainder = rounded.hour % hour_step
    if remainder:
        rounded += timedelta(hours=hour_step - remainder)
    
    return rounded


def append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height, hour_step=6):
    """Append day ticks and hour sub-ticks for the chart time axis."""
    min_local = datetime.fromtimestamp(min_ts, DISPLAY_TIMEZONE)
    max_local = datetime.fromtimestamp(max_ts, DISPLAY_TIMEZONE)
    day_tick = min_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if day_tick.timestamp() < min_ts:
        day_tick += timedelta(days=1)
    
    minor_tick = ceil_to_hour_multiple(min_local, hour_step)
    while minor_tick.timestamp() <= max_ts:
        if minor_tick.timestamp() >= min_ts and minor_tick.hour != 0:
            x = scale_x(minor_tick)
            svg.append(
                f'<line class="subgrid" x1="{x:.2f}" y1="{margin_top}" '
                f'x2="{x:.2f}" y2="{margin_top + plot_height}"/>'
            )
            svg.append(
                f'<text class="subtick" x="{x:.2f}" y="{margin_top + plot_height + 22}" '
                f'text-anchor="middle">{html.escape(minor_tick.strftime("%H"))}</text>'
            )
        minor_tick += timedelta(hours=hour_step)
    
    while day_tick.timestamp() <= max_ts:
        if day_tick.timestamp() >= min_ts:
            x = scale_x(day_tick)
            svg.append(
                f'<line class="grid day-grid" x1="{x:.2f}" y1="{margin_top}" '
                f'x2="{x:.2f}" y2="{margin_top + plot_height}"/>'
            )
            svg.append(
                f'<text class="tick" x="{x:.2f}" y="{margin_top + plot_height + 42}" '
                f'text-anchor="middle">{html.escape(day_tick.strftime("%d-%m"))}</text>'
            )
        day_tick += timedelta(days=1)


def print_player_value_chart():
    """Generate one SVG chart with cumulative net value over time for each player."""
    if not player_value_timeline:
        print("No player value timeline data to chart")
        return
    
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)
    
    chart_file = chart_output_path('VALUE_OVER_TIME_BY_PLAYER.svg')
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    width = 1600
    height = 720
    margin_left = 90
    margin_top = 70
    margin_bottom = 82
    margin_right = 40
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    
    all_points = [
        point
        for points in player_value_timeline.values()
        for point in points
        if point[0] != datetime.min
    ]
    
    if not all_points:
        print("No dated player value timeline data to chart")
        return
    
    min_time = min(point[0] for point in all_points)
    max_time = max(point[0] for point in all_points)
    min_value, max_value, tick_values, tick_step = calculate_value_axis([point[1] for point in all_points])
    
    min_ts = min_time.timestamp()
    max_ts = max_time.timestamp()
    if min_ts == max_ts:
        min_ts -= 1
        max_ts += 1
    
    def scale_x(date_value):
        return margin_left + ((date_value.timestamp() - min_ts) / (max_ts - min_ts)) * plot_width
    
    def scale_y(value):
        return margin_top + ((max_value - value) / (max_value - min_value)) * plot_height
    
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>',
        'text { font-family: Segoe UI, Arial, sans-serif; fill: #111827; }',
        '.axis { stroke: #111827; stroke-width: 1.5; }',
        '.grid { stroke: #e5e7eb; stroke-width: 1; }',
        '.day-grid { stroke: #cbd5e1; stroke-width: 1.2; }',
        '.subgrid { stroke: #f1f5f9; stroke-width: 1; }',
        '.tick { font-size: 12px; fill: #4b5563; }',
        '.subtick { font-size: 10px; fill: #9ca3af; }',
        '.title { font-size: 24px; font-weight: 700; }',
        '.subtitle { font-size: 13px; fill: #6b7280; }',
        '.legend { font-size: 13px; }',
        '.legend-box { fill: rgba(255,255,255,0.86); stroke: #d1d5db; stroke-width: 1; }',
        '</style>',
        f'<text class="title" x="{margin_left}" y="34">Total value over time by player</text>',
        f'<text class="subtitle" x="{margin_left}" y="56">Cumulative net value in Divine Orb, estimated from cached poe.ninja data</text>',
    ]
    
    # Y-axis grid and labels
    for value in tick_values:
        y = scale_y(value)
        svg.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_width}" y2="{y:.2f}"/>')
        svg.append(
            f'<text class="tick" x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end">{html.escape(format_axis_value(value, tick_step))}</text>'
        )
    
    append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height)
    
    svg.extend([
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}"/>',
        f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}"/>',
        f'<text class="tick" x="{margin_left - 60}" y="{margin_top + plot_height / 2}" transform="rotate(-90 {margin_left - 60} {margin_top + plot_height / 2})" text-anchor="middle">Net value (Divine Orb)</text>',
        f'<text class="tick" x="{margin_left + plot_width / 2}" y="{margin_top + plot_height + 62}" text-anchor="middle">Time</text>',
    ])
    
    players_with_points = [
        player
        for player in sorted(player_value_timeline.keys())
        if player_value_timeline[player]
    ]
    legend_x = margin_left + 14
    legend_y = margin_top + 14
    legend_width = 290
    legend_height = 28 + (len(players_with_points) * 24)
    legend_svg = [
        f'<rect class="legend-box" x="{legend_x}" y="{legend_y}" width="{legend_width}" '
        f'height="{legend_height}" rx="6"/>',
        f'<text class="legend" x="{legend_x + 12}" y="{legend_y + 20}" font-weight="700">Player</text>',
    ]
    
    for index, player in enumerate(players_with_points):
        points = player_value_timeline[player]
        color = colors[index % len(colors)]
        point_string = ' '.join(
            f'{scale_x(date_value):.2f},{scale_y(value):.2f}'
            for date_value, value in points
        )
        final_value = points[-1][1]
        legend_item_y = legend_y + 46 + (index * 24)
        
        svg.append(
            f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="2.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        legend_svg.append(f'<line x1="{legend_x + 12}" y1="{legend_item_y - 5}" x2="{legend_x + 40}" y2="{legend_item_y - 5}" stroke="{color}" stroke-width="3"/>')
        legend_svg.append(
            f'<text class="legend" x="{legend_x + 50}" y="{legend_item_y}">'
            f'{html.escape(player)} ({final_value:.2f} div)</text>'
        )
    
    svg.extend(legend_svg)
    svg.append('</svg>')
    
    with open(chart_file, 'w', encoding='utf-8') as chart_f:
        chart_f.write('\n'.join(svg))
    
    print()
    print("=" * 80)
    print("VALUE CHART CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Player value chart: {chart_file}")
    print("=" * 80)
    print()


def print_stash_value_chart():
    """Generate one SVG chart with cumulative net value over time for each stash."""
    if not stash_value_timeline:
        print("No stash value timeline data to chart")
        return
    
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)
    
    chart_file = chart_output_path('VALUE_OVER_TIME_BY_STASH.svg')
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    width = 1600
    height = 720
    margin_left = 90
    margin_top = 70
    margin_bottom = 82
    margin_right = 40
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    
    all_points = [
        point
        for points in stash_value_timeline.values()
        for point in points
        if point[0] != datetime.min
    ]
    
    if not all_points:
        print("No dated stash value timeline data to chart")
        return
    
    min_time = min(point[0] for point in all_points)
    max_time = max(point[0] for point in all_points)
    min_value, max_value, tick_values, tick_step = calculate_value_axis([point[1] for point in all_points])
    
    min_ts = min_time.timestamp()
    max_ts = max_time.timestamp()
    if min_ts == max_ts:
        min_ts -= 1
        max_ts += 1
    
    def scale_x(date_value):
        return margin_left + ((date_value.timestamp() - min_ts) / (max_ts - min_ts)) * plot_width
    
    def scale_y(value):
        return margin_top + ((max_value - value) / (max_value - min_value)) * plot_height
    
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>',
        'text { font-family: Segoe UI, Arial, sans-serif; fill: #111827; }',
        '.axis { stroke: #111827; stroke-width: 1.5; }',
        '.grid { stroke: #e5e7eb; stroke-width: 1; }',
        '.day-grid { stroke: #cbd5e1; stroke-width: 1.2; }',
        '.subgrid { stroke: #f1f5f9; stroke-width: 1; }',
        '.tick { font-size: 12px; fill: #4b5563; }',
        '.subtick { font-size: 10px; fill: #9ca3af; }',
        '.title { font-size: 24px; font-weight: 700; }',
        '.subtitle { font-size: 13px; fill: #6b7280; }',
        '.legend { font-size: 13px; }',
        '.legend-box { fill: rgba(255,255,255,0.86); stroke: #d1d5db; stroke-width: 1; }',
        '</style>',
        f'<text class="title" x="{margin_left}" y="34">Total value over time by stash</text>',
        f'<text class="subtitle" x="{margin_left}" y="56">Cumulative net value in Divine Orb, estimated from cached poe.ninja data</text>',
    ]
    
    for value in tick_values:
        y = scale_y(value)
        svg.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_width}" y2="{y:.2f}"/>')
        svg.append(
            f'<text class="tick" x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end">{html.escape(format_axis_value(value, tick_step))}</text>'
        )
    
    append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height)
    
    svg.extend([
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}"/>',
        f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}"/>',
        f'<text class="tick" x="{margin_left - 60}" y="{margin_top + plot_height / 2}" transform="rotate(-90 {margin_left - 60} {margin_top + plot_height / 2})" text-anchor="middle">Net value (Divine Orb)</text>',
        f'<text class="tick" x="{margin_left + plot_width / 2}" y="{margin_top + plot_height + 62}" text-anchor="middle">Time</text>',
    ])
    
    stashes_with_points = [
        stash
        for stash in sorted(stash_value_timeline.keys())
        if stash_value_timeline[stash]
    ]
    legend_x = margin_left + 14
    legend_y = margin_top + 14
    legend_width = 260
    legend_height = 28 + (len(stashes_with_points) * 24)
    legend_svg = [
        f'<rect class="legend-box" x="{legend_x}" y="{legend_y}" width="{legend_width}" '
        f'height="{legend_height}" rx="6"/>',
        f'<text class="legend" x="{legend_x + 12}" y="{legend_y + 20}" font-weight="700">Stash</text>',
    ]
    
    for index, stash in enumerate(stashes_with_points):
        points = stash_value_timeline[stash]
        color = colors[index % len(colors)]
        point_string = ' '.join(
            f'{scale_x(date_value):.2f},{scale_y(value):.2f}'
            for date_value, value in points
        )
        final_value = points[-1][1]
        legend_item_y = legend_y + 46 + (index * 24)
        
        svg.append(
            f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="2.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        legend_svg.append(f'<line x1="{legend_x + 12}" y1="{legend_item_y - 5}" x2="{legend_x + 40}" y2="{legend_item_y - 5}" stroke="{color}" stroke-width="3"/>')
        legend_svg.append(
            f'<text class="legend" x="{legend_x + 50}" y="{legend_item_y}">'
            f'{html.escape(stash)} ({final_value:.2f} div)</text>'
        )
    
    svg.extend(legend_svg)
    svg.append('</svg>')
    
    with open(chart_file, 'w', encoding='utf-8') as chart_f:
        chart_f.write('\n'.join(svg))
    
    print()
    print("=" * 80)
    print("STASH VALUE CHART CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Stash value chart: {chart_file}")
    print("=" * 80)
    print()


def write_single_value_chart(chart_file, title, subtitle, points, color='#2563eb'):
    """Write one SVG chart for a single cumulative value timeline."""
    dated_points = [
        (date_value, value)
        for date_value, value in points
        if date_value != datetime.min
    ]
    if not dated_points:
        return False
    
    width = 1280
    height = 520
    margin_left = 82
    margin_top = 70
    margin_right = 38
    margin_bottom = 82
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    
    min_time = min(point[0] for point in dated_points)
    max_time = max(point[0] for point in dated_points)
    min_value, max_value, tick_values, tick_step = calculate_value_axis([point[1] for point in dated_points])
    
    min_ts = min_time.timestamp()
    max_ts = max_time.timestamp()
    if min_ts == max_ts:
        min_ts -= 1
        max_ts += 1
    
    def scale_x(date_value):
        return margin_left + ((date_value.timestamp() - min_ts) / (max_ts - min_ts)) * plot_width
    
    def scale_y(value):
        return margin_top + ((max_value - value) / (max_value - min_value)) * plot_height
    
    point_string = ' '.join(
        f'{scale_x(date_value):.2f},{scale_y(value):.2f}'
        for date_value, value in dated_points
    )
    final_value = dated_points[-1][1]
    
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>',
        'text { font-family: Segoe UI, Arial, sans-serif; fill: #111827; }',
        '.axis { stroke: #111827; stroke-width: 1.4; }',
        '.grid { stroke: #e5e7eb; stroke-width: 1; }',
        '.day-grid { stroke: #cbd5e1; stroke-width: 1.2; }',
        '.subgrid { stroke: #f1f5f9; stroke-width: 1; }',
        '.tick { font-size: 12px; fill: #4b5563; }',
        '.subtick { font-size: 10px; fill: #9ca3af; }',
        '.title { font-size: 22px; font-weight: 700; }',
        '.subtitle { font-size: 13px; fill: #6b7280; }',
        '</style>',
        f'<text class="title" x="{margin_left}" y="34">{html.escape(title)}</text>',
        f'<text class="subtitle" x="{margin_left}" y="56">{html.escape(subtitle)} Final: {final_value:.4f} div</text>',
    ]
    
    for value in tick_values:
        y = scale_y(value)
        svg.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_width}" y2="{y:.2f}"/>')
        svg.append(
            f'<text class="tick" x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end">{html.escape(format_axis_value(value, tick_step))}</text>'
        )
    
    append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height)
    
    svg.extend([
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}"/>',
        f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}"/>',
        f'<text class="tick" x="{margin_left - 58}" y="{margin_top + plot_height / 2}" transform="rotate(-90 {margin_left - 58} {margin_top + plot_height / 2})" text-anchor="middle">Net value (Divine Orb)</text>',
        f'<text class="tick" x="{margin_left + plot_width / 2}" y="{margin_top + plot_height + 58}" text-anchor="middle">Time</text>',
        f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round"/>',
        f'<circle cx="{scale_x(dated_points[-1][0]):.2f}" cy="{scale_y(final_value):.2f}" r="4" fill="{color}"/>',
        '</svg>',
    ])
    
    with open(chart_file, 'w', encoding='utf-8') as chart_f:
        chart_f.write('\n'.join(svg))
    
    return True


def print_individual_value_charts():
    """Generate individual cumulative value charts for each player and stash."""
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)
    
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    player_chart_files.clear()
    stash_chart_files.clear()
    
    for index, player in enumerate(sorted(player_value_timeline.keys())):
        filename = safe_chart_filename('CHART_PLAYER', player)
        chart_file = chart_output_path(filename)
        if write_single_value_chart(
            chart_file,
            f'{player} value over time',
            'Cumulative net value in Divine Orb.',
            player_value_timeline[player],
            colors[index % len(colors)],
        ):
            player_chart_files[player] = filename
    
    for index, stash in enumerate(sorted(stash_value_timeline.keys())):
        filename = safe_chart_filename('CHART_STASH', stash)
        chart_file = chart_output_path(filename)
        if write_single_value_chart(
            chart_file,
            f'{stash} value over time',
            'Cumulative net value in Divine Orb.',
            stash_value_timeline[stash],
            colors[index % len(colors)],
        ):
            stash_chart_files[stash] = filename
    
    print()
    print("=" * 80)
    print("INDIVIDUAL VALUE CHARTS CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Player charts: {len(player_chart_files)}")
    print(f"Stash charts: {len(stash_chart_files)}")
    print("=" * 80)
    print()


def html_table(headers, rows, class_name='', default_sort=True):
    """Render a simple HTML table."""
    class_attr = f' class="{class_name}"' if class_name else ''
    default_sort_attr = '' if default_sort else ' data-default-sort="none"'
    output = [
        '<div class="table-filter"><input class="table-filter-input" type="search" placeholder="Filter..." aria-label="Filter table"></div>',
        '<div class="table-scroll">',
        f'<table{class_attr}{default_sort_attr}>',
        '<thead><tr>',
    ]
    
    for header in headers:
        output.append(f'<th>{html.escape(str(header))}</th>')
    
    output.append('</tr></thead><tbody>')
    
    for row in rows:
        output.append('<tr>')
        for cell in row:
            output.append(f'<td>{html.escape(str(cell))}</td>')
        output.append('</tr>')
    
    output.append('</tbody></table></div>')
    return '\n'.join(output)


def format_signed(value):
    """Format signed integer values for reports."""
    return f'{value:+d}' if value != 0 else '0'


def format_value(value):
    """Format divine values for reports."""
    return f'{value:.4f}'


def format_signed_value(value):
    """Format signed divine values for movement logs."""
    if value > 0:
        return f'+{value:.4f}'
    if value < 0:
        return f'{value:.4f}'
    return '0.0000'


def format_log_date(date_value):
    """Format an event date for compact chronological tables."""
    parsed = parse_event_date(date_value)
    if parsed == datetime.min:
        return date_value
    return display_event_datetime(parsed).strftime('%Y-%m-%d %H:%M:%S')


def render_filtered_log_table(filter_name, filter_value):
    """Render chronological add/remove movement rows for one player or stash."""
    rows = []
    for entry in sorted(movement_log, key=lambda item: (item['parsed_date'], item['parsed_id']), reverse=True):
        if entry.get(filter_name) != filter_value:
            continue
        if entry['rate'] <= 0:
            continue
        
        quantity = entry['quantity'] if entry['action'] == 'added' else -entry['quantity']
        rows.append([
            format_log_date(entry['date']),
            entry['account'],
            entry['item_name'],
            format_signed(quantity),
            format_value(entry['rate']),
            format_signed_value(entry['value']),
        ])
    
    return html_table(
        ["Date", "Player", "Item", "Qty", "Rate", "Value"],
        rows,
        class_name='log-table',
        default_sort=False,
    )


def render_toggle_panel(summary_html, log_html):
    """Render summary/log view toggle with summary selected by default."""
    return (
        '<div class="view-toggle" role="group" aria-label="Table view">'
        '<button class="view-button active" data-view="summary" type="button">Summary</button>'
        '<button class="view-button" data-view="log" type="button">Log</button>'
        '</div>'
        '<div class="view-panel active" data-view-panel="summary">'
        f'{summary_html}'
        '</div>'
        '<div class="view-panel" data-view-panel="log">'
        f'{log_html}'
        '</div>'
    )


def collect_value_totals():
    """Collect value totals by player and stash."""
    player_totals = defaultdict(lambda: {'added_value': 0.0, 'removed_value': 0.0})
    stash_totals = defaultdict(lambda: {'added_value': 0.0, 'removed_value': 0.0})
    
    for stash, accounts in valuation_summary.items():
        for account, items in accounts.items():
            for stats in items.values():
                player_totals[account]['added_value'] += stats['added_value']
                player_totals[account]['removed_value'] += stats['removed_value']
                stash_totals[stash]['added_value'] += stats['added_value']
                stash_totals[stash]['removed_value'] += stats['removed_value']
    
    return player_totals, stash_totals


def render_cache_footer_items():
    """Render compact price cache timestamps for the dashboard footer."""
    items = []
    
    for price_type in PRICE_TYPES:
        path = price_cache_path(price_type)
        status = price_metadata.get(price_type, 'not loaded')
        
        if os.path.exists(path):
            fetched_at = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
            label = f'{price_type}: {fetched_at}'
        else:
            label = f'{price_type}: {status}'
        
        items.append(f'<span>{html.escape(label)}</span>')
    
    return '\n'.join(items)


def get_row_value_stats(stash, account, item_name, net_quantity):
    """Return effective rate and net value in divine for one item row."""
    stats = valuation_summary.get(stash, {}).get(account, {}).get(item_name)
    if not stats:
        return '0.0000', '0.0000'
    
    added_qty = stats['priced_added_qty']
    removed_qty = stats['priced_removed_qty']
    total_priced_qty = added_qty + removed_qty
    added_value = stats['added_value']
    removed_value = stats['removed_value']
    net_value = added_value - removed_value
    
    if total_priced_qty > 0:
        rate = (added_value + removed_value) / total_priced_qty
    else:
        rate = 0.0
    
    if net_quantity != 0:
        net_value = net_quantity * rate
    
    return format_value(rate), format_value(net_value)


def get_current_item_rate(item_name):
    """Return current item rate in divine from cached poe.ninja data."""
    price_index = build_price_index()
    price_data = price_index.get(normalize_price_key(item_name))
    
    if not price_data or price_data['primary_value'] <= 0:
        return 0.0
    
    return 1.0 if price_data.get('name') == 'Divine Orb' else price_data['primary_value']


def embed_svg_file(filename):
    """Read SVG file and return embedded content, or empty string if not found."""
    if not filename:
        return ''
    
    filepath = chart_output_path(filename)
    if not os.path.exists(filepath):
        return ''
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def render_inline_chart(filename, alt_text):
    """Render a detail chart by embedding SVG content directly into HTML."""
    if not filename or not os.path.exists(chart_output_path(filename)):
        return ''
    
    svg_content = embed_svg_file(filename)
    if not svg_content:
        return ''
    
    return (
        '<div class="detail-chart">'
        f'{svg_content}'
        '</div>'
    )


def render_player_sections():
    """Render player detail sections for the HTML dashboard."""
    buttons = []
    panels = []
    
    all_players = set()
    for accounts in stash_summary.values():
        all_players.update(accounts.keys())
    
    for index, player in enumerate(sorted(all_players)):
        rows = []
        player_value = 0.0
        for stash in sorted(stash_summary.keys()):
            if player not in stash_summary[stash]:
                continue
            
            for item_name in sorted(stash_summary[stash][player].keys()):
                stats = stash_summary[stash][player][item_name]
                net = stats['added'] - stats['removed']
                rate, value = get_row_value_stats(stash, player, item_name, net)
                player_value += float(value)
                rows.append([stash, item_name, stats['added'], stats['removed'], format_signed(net), rate, value])
        
        active_class = ' active' if index == 0 else ''
        target_id = f'player-subtab-{index}'
        buttons.append(
            f'<button class="subtab-button{active_class}" data-subtab-target="{target_id}" data-subtab-value="{format_value(player_value)}">'
            f'<span class="subtab-label">{html.escape(player)}</span>'
            f'<span class="subtab-value">{format_value(player_value)} div</span>'
            '</button>'
        )
        summary_table = html_table(["Stash", "Item", "Added", "Removed", "Net", "Rate", "Value"], rows)
        log_table = render_filtered_log_table("account", player)
        panels.append(
            f'<section id="{target_id}" class="subtab-panel{active_class}">'
            f'<div class="subtab-title">{html.escape(player)}</div>'
            f'{render_inline_chart(player_chart_files.get(player), f"{player} value over time")}'
            f'{render_toggle_panel(summary_table, log_table)}'
            '</section>'
        )
    
    return (
        '<h2>By player</h2>'
        '<div class="subtab-layout">'
        f'<nav class="subtab-nav" aria-label="Players">{"".join(buttons)}</nav>'
        f'<div class="subtab-content">{"".join(panels)}</div>'
        '</div>'
    )


def render_stash_sections():
    """Render stash detail sections for the HTML dashboard.
    Note: Uses historical weighted average item rates calculated from all transactions in each stash."""
    buttons = []
    panels = []
    
    for index, stash in enumerate(sorted(stash_summary.keys())):
        rows = []
        stash_value = 0.0
        for account in sorted(stash_summary[stash].keys()):
            for item_name in sorted(stash_summary[stash][account].keys()):
                stats = stash_summary[stash][account][item_name]
                net = stats['added'] - stats['removed']
                rate, value = get_row_value_stats(stash, account, item_name, net)
                stash_value += float(value)
                rows.append([account, item_name, stats['added'], stats['removed'], format_signed(net), rate, value])
        
        active_class = ' active' if index == 0 else ''
        target_id = f'stash-subtab-{index}'
        buttons.append(
            f'<button class="subtab-button{active_class}" data-subtab-target="{target_id}" data-subtab-value="{format_value(stash_value)}">'
            f'<span class="subtab-label">{html.escape(stash)}</span>'
            f'<span class="subtab-value">{format_value(stash_value)} div</span>'
            '</button>'
        )
        summary_table = html_table(["Player", "Item", "Added", "Removed", "Net", "Rate", "Value"], rows)
        log_table = render_filtered_log_table("stash", stash)
        panels.append(
            f'<section id="{target_id}" class="subtab-panel{active_class}">'
            f'<div class="subtab-title">{html.escape(stash)} <span class="subtab-meta">Pricing: historical average from transactions</span></div>'
            f'{render_inline_chart(stash_chart_files.get(stash), f"{stash} value over time")}'
            f'{render_toggle_panel(summary_table, log_table)}'
            '</section>'
        )
    
    return (
        '<h2>By stash</h2>'
        '<div class="subtab-layout">'
        f'<nav class="subtab-nav" aria-label="Stashes">{"".join(buttons)}</nav>'
        f'<div class="subtab-content">{"".join(panels)}</div>'
        '</div>'
    )


def render_final_state_sections():
    """Render final stash contents for the HTML dashboard.
    Note: Uses current poe.ninja rates for final inventory valuation (different from historical rates in 'By stash' tab)."""
    buttons = []
    panels = []
    current_rates = {}
    latest_event_date = max((event['parsed_date'] for event in log_events), default=datetime.min)
    latest_label = display_event_datetime(latest_event_date).strftime('%Y-%m-%d %H:%M:%S CEST') if latest_event_date != datetime.min else 'unknown'
    
    for index, stash in enumerate(sorted(TARGET_STASHES)):
        item_totals = defaultdict(lambda: {'quantity': 0, 'stacks': 0})
        stash_value = 0.0
        for (state_stash, x, y), data in final_stash_state.items():
            if state_stash != stash:
                continue
            item_totals[data['item_name']]['quantity'] += data['quantity']
            item_totals[data['item_name']]['stacks'] += 1
        
        rows = []
        for item_name, totals in sorted(item_totals.items()):
            if item_name not in current_rates:
                current_rates[item_name] = get_current_item_rate(item_name)
            rate = current_rates[item_name]
            value = totals['quantity'] * rate
            stash_value += value
            rows.append([
                item_name,
                totals['quantity'],
                totals['stacks'],
                format_value(rate),
                format_value(value),
            ])
        active_class = ' active' if index == 0 else ''
        target_id = f'final-state-subtab-{index}'
        buttons.append(
            f'<button class="subtab-button{active_class}" data-subtab-target="{target_id}" data-subtab-value="{format_value(stash_value)}">'
            f'<span class="subtab-label">{html.escape(stash)}</span>'
            f'<span class="subtab-value">{format_value(stash_value)} div</span>'
            '</button>'
        )
        summary_table = html_table(["Item", "Quantity", "Stacks", "Rate", "Value"], rows)
        log_table = render_filtered_log_table("stash", stash)
        panels.append(
            f'<section id="{target_id}" class="subtab-panel{active_class}">'
            f'<div class="subtab-title">{html.escape(stash)} <span class="subtab-meta">Last transaction: {html.escape(latest_label)} | Pricing: current poe.ninja rates</span></div>'
            f'{render_toggle_panel(summary_table, log_table)}'
            '</section>'
        )
    
    return (
        '<h2>Final state</h2>'
        '<div class="subtab-layout">'
        f'<nav class="subtab-nav" aria-label="Final state stashes">{"".join(buttons)}</nav>'
        f'<div class="subtab-content">{"".join(panels)}</div>'
        '</div>'
    )


def render_chart_sections():
    """Render combined timeline charts for the dashboard totals tab."""
    sections = []
    charts = [
        ('VALUE_OVER_TIME_BY_STASH.svg', 'Total value over time by stash'),
        ('VALUE_OVER_TIME_BY_PLAYER.svg', 'Total value over time by player'),
    ]
    
    for filename, alt_text in charts:
        if not os.path.exists(chart_output_path(filename)):
            continue
        svg_content = embed_svg_file(filename)
        if not svg_content:
            continue
        sections.append(
            '<div class="card chart-card">'
            f'{svg_content}'
            '</div>'
        )
    
    if not sections:
        return ''
    
    return '<div class="total-chart-grid">' + ''.join(sections) + '</div>'


def print_html_dashboard():
    """Generate the tabbed HTML dashboard."""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    dashboard_file = dashboard_filename()
    page_title = dashboard_title()
    player_value_totals, stash_value_totals = collect_value_totals()
    
    stash_value_rows = []
    for stash in sorted(stash_value_totals.keys()):
        stats = stash_value_totals[stash]
        added = stats['added_value']
        removed = stats['removed_value']
        stash_value_rows.append([stash, format_value(added), format_value(removed), format_value(added - removed)])
    
    player_value_rows = []
    for player in sorted(player_value_totals.keys()):
        stats = player_value_totals[player]
        added = stats['added_value']
        removed = stats['removed_value']
        player_value_rows.append([player, format_value(added), format_value(removed), format_value(added - removed)])
    
    cache_footer_items = render_cache_footer_items()
    unpriced_rows = [
        [item_name, stats['added_qty'], stats['removed_qty']]
        for item_name, stats in sorted(unpriced_summary.items())
    ]
    
    page = f'''<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(page_title)}</title>
    <style>
        :root {{
            color-scheme: light;
            --bg: #f8fafc;
            --panel: #ffffff;
            --text: #111827;
            --muted: #6b7280;
            --line: #d1d5db;
            --accent: #2563eb;
            --header-height: 92px;
            --tabs-height: 58px;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: Segoe UI, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
        }}
        header {{
            padding: 24px 32px 16px;
            border-bottom: 1px solid var(--line);
            background: var(--panel);
            position: sticky;
            top: 0;
            z-index: 2;
        }}
        h1 {{ margin: 0 0 6px; font-size: 28px; }}
        h2 {{ margin: 0 0 16px; font-size: 20px; }}
        h3 {{ margin: 24px 0 10px; font-size: 16px; }}
        .section-total {{
            display: inline-block;
            margin-left: 8px;
            padding: 2px 7px;
            border: 1px solid var(--line);
            border-radius: 999px;
            color: var(--muted);
            font-size: 12px;
            font-weight: 500;
            vertical-align: middle;
        }}
        .subtitle {{ color: var(--muted); }}
        .tabs {{
            display: flex;
            gap: 8px;
            padding: 12px 32px;
            border-bottom: 1px solid var(--line);
            background: #eef2ff;
            position: sticky;
            top: var(--header-height);
            z-index: 2;
            overflow-x: auto;
        }}
        .tab-button {{
            border: 1px solid var(--line);
            background: var(--panel);
            color: var(--text);
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            white-space: nowrap;
        }}
        .tab-button.active {{
            background: var(--accent);
            border-color: var(--accent);
            color: #ffffff;
        }}
        main {{ padding: 24px 32px 40px; }}
        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
            gap: 20px;
        }}
        .card {{
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 16px;
            overflow: hidden;
        }}
        .subtab-layout {{
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 12px;
            align-items: start;
        }}
        .subtab-nav {{
            position: sticky;
            top: calc(var(--header-height) + var(--tabs-height) + 12px);
            display: flex;
            flex-direction: column;
            gap: 4px;
            width: 280px;
            min-width: 260px;
            max-width: min(520px, 45vw);
            max-height: calc(100vh - 170px);
            resize: horizontal;
            overflow-y: auto;
            overflow-x: auto;
            padding: 6px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--panel);
        }}
        .subtab-button {{
            width: 100%;
            min-width: 240px;
            border: 0;
            border-radius: 5px;
            background: transparent;
            color: var(--text);
            cursor: pointer;
            padding: 6px 8px;
            text-align: left;
            font-size: 12px;
            line-height: 1.25;
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 8px;
            align-items: center;
        }}
        .subtab-button:hover {{
            background: #eef2ff;
        }}
        .subtab-button.active {{
            background: var(--accent);
            color: #ffffff;
        }}
        .subtab-label {{
            min-width: 0;
            white-space: nowrap;
        }}
        .subtab-value {{
            color: var(--muted);
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }}
        .subtab-button.active .subtab-value {{
            color: #dbeafe;
        }}
        .subtab-content {{
            min-width: 0;
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--panel);
        }}
        .subtab-panel {{
            display: none;
            padding: 10px 12px 12px;
        }}
        .subtab-panel.active {{
            display: block;
        }}
        .subtab-title {{
            margin-bottom: 8px;
            font-size: 14px;
            font-weight: 700;
        }}
        .subtab-meta {{
            margin-left: 10px;
            color: var(--muted);
            font-size: 12px;
            font-weight: 400;
        }}
        .view-toggle {{
            display: inline-flex;
            gap: 2px;
            margin-bottom: 8px;
            padding: 2px;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: #f9fafb;
        }}
        .view-button {{
            border: 0;
            border-radius: 4px;
            background: transparent;
            color: var(--text);
            cursor: pointer;
            padding: 5px 10px;
            font-size: 12px;
        }}
        .view-button.active {{
            background: var(--accent);
            color: #ffffff;
        }}
        .view-panel {{
            display: none;
        }}
        .view-panel.active {{
            display: block;
        }}
        .table-filter {{
            margin-bottom: 6px;
        }}
        .table-filter-input {{
            width: min(100%, 360px);
            padding: 6px 8px;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            background: #ffffff;
            color: var(--text);
            font-size: 12px;
        }}
        .table-filter-input:focus {{
            outline: 2px solid #bfdbfe;
            border-color: var(--accent);
        }}
        .table-scroll {{
            min-height: 180px;
            height: calc((100vh - var(--header-height) - var(--tabs-height) - 220px) * 2);
            overflow: auto;
            resize: vertical;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
        }}
        .card .table-scroll {{
            height: 640px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            padding: 7px 9px;
            border-bottom: 1px solid #e5e7eb;
            text-align: right;
            white-space: nowrap;
        }}
        th:first-child, td:first-child,
        th:nth-child(2), td:nth-child(2) {{
            text-align: left;
        }}
        th {{
            position: sticky;
            top: 0;
            background: #f9fafb;
            font-weight: 600;
            z-index: 1;
        }}
        th.sortable {{
            cursor: pointer;
            user-select: none;
        }}
        th.sortable::after {{
            content: "";
            display: inline-block;
            margin-left: 6px;
            color: var(--muted);
            font-size: 10px;
        }}
        th.sortable[data-sort-state="asc"]::after {{
            content: "^";
        }}
        th.sortable[data-sort-state="desc"]::after {{
            content: "v";
        }}
        details {{
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 8px;
            margin-bottom: 12px;
            overflow: auto;
        }}
        summary {{
            cursor: pointer;
            padding: 12px 14px;
            font-weight: 600;
            background: #f9fafb;
            border-bottom: 1px solid var(--line);
        }}
        details:not([open]) summary {{
            border-bottom: none;
        }}
        .chart {{
            width: 100%;
            max-width: 1400px;
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 8px;
            cursor: zoom-in;
        }}
        svg {{
            display: block;
        }}
        .chart-card svg,
        .detail-chart svg {{
            cursor: zoom-in;
        }}
        .chart-card {{
            margin-bottom: 20px;
        }}
        .total-chart-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            margin-bottom: 16px;
        }}
        #totals .chart-card {{
            max-width: none;
            margin: 0;
            padding: 12px;
        }}
        #totals .chart-card svg {{
            display: block;
            max-height: 38vh;
            width: auto;
            height: auto;
            margin: 0 auto;
        }}
        .detail-chart {{
            margin-bottom: 12px;
            overflow: hidden;
            display: flex;
            justify-content: center;
            align-items: center;
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 12px;
        }}
        .detail-chart svg {{
            max-height: 500px;
            max-width: 100%;
            width: auto;
            height: auto;
        }}
        .chart-modal {{
            position: fixed;
            inset: 0;
            z-index: 20;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 0;
            background: rgba(17, 24, 39, 0.78);
        }}
        .chart-modal.active {{
            display: flex;
        }}
        .chart-modal-panel {{
            position: relative;
            width: 100vw;
            height: 100vh;
            padding: 14px;
            border-radius: 0;
            background: var(--panel);
            overflow: hidden;
        }}
        .chart-modal-title {{
            height: 28px;
            margin: 0 44px 8px 2px;
            font-size: 14px;
            font-weight: 700;
        }}
        .chart-modal-close {{
            position: absolute;
            top: 10px;
            right: 10px;
            width: 32px;
            height: 32px;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: #ffffff;
            color: var(--text);
            cursor: pointer;
            font-size: 20px;
            line-height: 1;
        }}
        .chart-modal-image {{
            display: block;
            width: 100%;
            height: calc(100vh - 50px);
            object-fit: contain;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: #ffffff;
        }}
        footer {{
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
            padding: 10px 32px;
            border-top: 1px solid var(--line);
            background: var(--panel);
            color: var(--muted);
            font-size: 12px;
        }}
        footer strong {{
            color: var(--text);
            font-weight: 600;
        }}
        .cache-items {{
            display: flex;
            gap: 8px 12px;
            flex-wrap: wrap;
        }}
        .cache-items span {{
            white-space: nowrap;
        }}
        @media (max-width: 800px) {{
            header,
            .tabs {{
                position: static;
            }}
            .subtab-layout {{
                grid-template-columns: 1fr;
            }}
            .subtab-nav {{
                position: static;
                flex-direction: row;
                width: auto;
                min-width: 0;
                max-width: none;
                resize: none;
                max-height: none;
                overflow-x: auto;
            }}
            .subtab-button {{
                width: auto;
                min-width: 120px;
            }}
            .total-chart-grid {{
                grid-template-columns: 1fr;
            }}
            .table-scroll,
            .card .table-scroll {{
                height: 110vh;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>{html.escape(page_title)}</h1>
        <div class="subtitle">League: {html.escape(LEAGUE_NAME)} | Stashes: {html.escape(target_stash_label())} | Time: CEST</div>
    </header>
    <nav class="tabs" aria-label="Report tabs">
        <button class="tab-button active" data-tab="totals">Totals</button>
        <button class="tab-button" data-tab="by-player">By player</button>
        <button class="tab-button" data-tab="by-stash">By stash</button>
        <button class="tab-button" data-tab="final-state">Final state</button>
        <button class="tab-button" data-tab="unpriced">Unpriced</button>
    </nav>
    <main>
        <section id="totals" class="tab-panel active">
            {render_chart_sections()}
            <div class="grid">
                <div class="card"><h2>Value by stash</h2>{html_table(["Stash", "Added Div", "Removed Div", "Net Div"], stash_value_rows)}</div>
                <div class="card"><h2>Value by player</h2>{html_table(["Player", "Added Div", "Removed Div", "Net Div"], player_value_rows)}</div>
            </div>
        </section>
        <section id="by-player" class="tab-panel">{render_player_sections()}</section>
        <section id="by-stash" class="tab-panel">{render_stash_sections()}</section>
        <section id="final-state" class="tab-panel">{render_final_state_sections()}</section>
        <section id="unpriced" class="tab-panel"><h2>Unpriced items</h2><div class="card">{html_table(["Item", "Added Qty", "Removed Qty"], unpriced_rows)}</div></section>
    </main>
    <footer>
        <strong>Price cache</strong>
        <div class="cache-items">{cache_footer_items}</div>
    </footer>
    <div class="chart-modal" id="chart-modal" aria-hidden="true">
        <div class="chart-modal-panel" role="dialog" aria-modal="true" aria-labelledby="chart-modal-title">
            <button class="chart-modal-close" type="button" aria-label="Close enlarged chart">&times;</button>
            <div class="chart-modal-title" id="chart-modal-title"></div>
            <img class="chart-modal-image" alt="">
        </div>
    </div>
    <script>
        const buttons = Array.from(document.querySelectorAll('.tab-button'));
        const panels = Array.from(document.querySelectorAll('.tab-panel'));
        buttons.forEach((button) => {{
            button.addEventListener('click', () => {{
                buttons.forEach((item) => item.classList.remove('active'));
                panels.forEach((item) => item.classList.remove('active'));
                button.classList.add('active');
                document.getElementById(button.dataset.tab).classList.add('active');
            }});
        }});
        document.querySelectorAll('.subtab-layout').forEach((layout) => {{
            const subtabButtons = Array.from(layout.querySelectorAll('.subtab-button'));
            const subtabPanels = Array.from(layout.querySelectorAll('.subtab-panel'));
            subtabButtons.forEach((button) => {{
                button.addEventListener('click', () => {{
                    subtabButtons.forEach((item) => item.classList.remove('active'));
                    subtabPanels.forEach((item) => item.classList.remove('active'));
                    button.classList.add('active');
                    const target = layout.querySelector(`#${{button.dataset.subtabTarget}}`);
                    if (target) {{
                        target.classList.add('active');
                    }}
                }});
            }});
        }});
        document.querySelectorAll('.subtab-panel').forEach((panel) => {{
            const viewButtons = Array.from(panel.querySelectorAll('.view-button'));
            const viewPanels = Array.from(panel.querySelectorAll('.view-panel'));
            viewButtons.forEach((button) => {{
                button.addEventListener('click', () => {{
                    viewButtons.forEach((item) => item.classList.remove('active'));
                    viewPanels.forEach((item) => item.classList.remove('active'));
                    button.classList.add('active');
                    const target = panel.querySelector(`[data-view-panel="${{button.dataset.view}}"]`);
                    if (target) {{
                        target.classList.add('active');
                    }}
                }});
            }});
        }});
        const chartModal = document.getElementById('chart-modal');
        const chartModalImage = chartModal?.querySelector('.chart-modal-image');
        const chartModalTitle = chartModal?.querySelector('.chart-modal-title');
        const chartModalClose = chartModal?.querySelector('.chart-modal-close');
        function closeChartModal() {{
            if (!chartModal || !chartModalImage || !chartModalTitle) {{
                return;
            }}
            chartModal.classList.remove('active');
            chartModal.setAttribute('aria-hidden', 'true');
            chartModalImage.removeAttribute('src');
            chartModalImage.alt = '';
            chartModalTitle.textContent = '';
        }}
        function openChartModalFromSvg(chart) {{
            if (!chartModal || !chartModalImage || !chartModalTitle) {{
                return;
            }}
            const chartClone = chart.cloneNode(true);
            chartClone.removeAttribute('style');
            const serialized = new XMLSerializer().serializeToString(chartClone);
            const title = chart.querySelector('.title')?.textContent || 'Chart';
            chartModalImage.src = `data:image/svg+xml;charset=utf-8,${{encodeURIComponent(serialized)}}`;
            chartModalImage.alt = title;
            chartModalTitle.textContent = title;
            chartModal.classList.add('active');
            chartModal.setAttribute('aria-hidden', 'false');
            chartModalClose?.focus();
        }}
        function openChartModalFromImage(chart) {{
            if (!chartModal || !chartModalImage || !chartModalTitle) {{
                return;
            }}
            chartModalImage.src = chart.src;
            chartModalImage.alt = chart.alt || 'Enlarged chart';
            chartModalTitle.textContent = chart.alt || 'Chart';
            chartModal.classList.add('active');
            chartModal.setAttribute('aria-hidden', 'false');
            chartModalClose?.focus();
        }}
        document.querySelectorAll('.chart-card svg, .detail-chart svg').forEach((chart) => {{
            chart.addEventListener('click', () => openChartModalFromSvg(chart));
        }});
        document.querySelectorAll('img.chart').forEach((chart) => {{
            chart.addEventListener('click', () => openChartModalFromImage(chart));
        }});
        chartModalClose?.addEventListener('click', closeChartModal);
        chartModal?.addEventListener('click', (event) => {{
            if (event.target === chartModal) {{
                closeChartModal();
            }}
        }});
        document.addEventListener('keydown', (event) => {{
            if (event.key === 'Escape' && chartModal?.classList.contains('active')) {{
                closeChartModal();
            }}
        }});
        document.querySelectorAll('table').forEach((table) => {{
            const headers = Array.from(table.querySelectorAll('th'));
            const tbody = table.querySelector('tbody');
            if (!tbody) {{
                return;
            }}
            Array.from(tbody.querySelectorAll('tr')).forEach((row, index) => {{
                row.dataset.originalIndex = index;
            }});
            const filterInput = table.closest('.table-scroll')?.previousElementSibling?.querySelector('.table-filter-input');
            if (filterInput) {{
                filterInput.addEventListener('input', () => {{
                    applyTableFilter(table, filterInput.value);
                }});
            }}
            table.dataset.sortColumn = '';
            table.dataset.sortState = 'normal';
            headers.forEach((header, columnIndex) => {{
                header.classList.add('sortable');
                header.dataset.sortState = 'normal';
                header.addEventListener('click', () => {{
                    const currentState = header.dataset.sortState;
                    const nextState = currentState === 'normal' ? 'asc' : currentState === 'asc' ? 'desc' : 'normal';
                    applyTableSort(table, columnIndex, nextState);
                }});
            }});
            const defaultColumnIndex = getDefaultSortColumn(headers);
            if (defaultColumnIndex >= 0 && table.dataset.defaultSort !== 'none') {{
                applyTableSort(table, defaultColumnIndex, 'desc', false);
            }}
        }});
        function applyTableFilter(table, query) {{
            const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            rows.forEach((row) => {{
                if (terms.length === 0) {{
                    row.hidden = false;
                    return;
                }}
                const rowText = row.textContent.toLowerCase();
                row.hidden = !terms.every((term) => rowText.includes(term));
            }});
        }}
        function getDefaultSortColumn(headers) {{
            const labels = headers.map((header) => header.textContent.trim());
            const valueIndex = labels.indexOf('Value');
            if (valueIndex >= 0) {{
                return valueIndex;
            }}
            const netDivIndex = labels.indexOf('Net Div');
            if (netDivIndex >= 0) {{
                return netDivIndex;
            }}
            return -1;
        }}
        function getTableSortGroup(table) {{
            const panel = table.closest('.tab-panel');
            return panel?.id || 'global';
        }}
        function getTableSignature(table) {{
            return Array.from(table.querySelectorAll('th')).map((header) => header.textContent.trim()).join('|');
        }}
        function updateSortGroup(table, columnIndex, state) {{
            const group = getTableSortGroup(table);
            const signature = getTableSignature(table);
            document.querySelectorAll(`.tab-panel#${{group}} table`).forEach((groupTable) => {{
                if (getTableSignature(groupTable) !== signature) {{
                    return;
                }}
                groupTable.dataset.sortColumn = state === 'normal' ? '' : String(columnIndex);
                groupTable.dataset.sortState = state;
                applyTableSort(groupTable, columnIndex, state, false);
            }});
        }}
        function applyTableSort(table, columnIndex, state, syncGroup = true) {{
            if (syncGroup) {{
                updateSortGroup(table, columnIndex, state);
                return;
            }}
            const headers = Array.from(table.querySelectorAll('th'));
            const tbody = table.querySelector('tbody');
            if (!tbody) {{
                return;
            }}
            table.dataset.sortColumn = state === 'normal' ? '' : String(columnIndex);
            table.dataset.sortState = state;
            headers.forEach((item) => {{
                item.dataset.sortState = 'normal';
            }});
            if (state !== 'normal' && headers[columnIndex]) {{
                headers[columnIndex].dataset.sortState = state;
            }}
            const rows = Array.from(tbody.querySelectorAll('tr'));
            if (state === 'normal') {{
                rows.sort((a, b) => Number(a.dataset.originalIndex) - Number(b.dataset.originalIndex));
            }} else {{
                rows.sort((a, b) => {{
                    const aText = (a.children[columnIndex]?.textContent || '').trim();
                    const bText = (b.children[columnIndex]?.textContent || '').trim();
                    const aNumber = Number(aText.replace(/,/g, ''));
                    const bNumber = Number(bText.replace(/,/g, ''));
                    const bothNumeric = aText !== '' && bText !== '' && !Number.isNaN(aNumber) && !Number.isNaN(bNumber);
                    let result;
                    if (bothNumeric) {{
                        result = aNumber - bNumber;
                    }} else {{
                        result = aText.localeCompare(bText, undefined, {{ numeric: true, sensitivity: 'base' }});
                    }}
                    return state === 'asc' ? result : -result;
                }});
            }}
            rows.forEach((row) => tbody.appendChild(row));
        }}
    </script>
</body>
</html>
'''
    
    with open(dashboard_file, 'w', encoding='utf-8') as dashboard_f:
        dashboard_f.write(page)
    
    print()
    print("=" * 80)
    print("HTML DASHBOARD CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Dashboard: {dashboard_file}")
    print("=" * 80)
    print()


if __name__ == '__main__':
    process_log()
    print_player_value_chart()
    print_stash_value_chart()
    print_individual_value_charts()
    print_html_dashboard()
