import csv
from collections import defaultdict
import re
from datetime import datetime
import os
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import html
import math

# Configuration
LOG_FILE = 'log.csv'
LEAGUE_NAME = 'Runes of Aldur'
TARGET_STASHES = {'$$$', 'Deli', 'Ess', 'Aug', 'Ritual', 'Abbys/Expedition'}
STASH_ALIASES = {
    'Abbys/Expediton': 'Abbys/Expedition',
}
OUTPUT_DIR = 'stash_reports'
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


def normalize_stash_name(stash_name):
    """Normalize known stash name typos from the log."""
    return STASH_ALIASES.get(stash_name, stash_name)


def safe_filename(value):
    """Make report filenames safe for Windows paths."""
    return re.sub(r'[<>:"/\\|?*]+', '_', value)


def safe_chart_filename(prefix, value):
    """Make chart filenames safe for filesystem paths and HTML src attributes."""
    safe_value = re.sub(r'[^A-Za-z0-9._$-]+', '_', value).strip('_')
    return f'{prefix}_{safe_value or "unnamed"}.svg'


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
    
    def apply_value_change(event, item_name, quantity, direction):
        value = add_valuation_entry(
            event['account'], event['stash'], item_name, quantity,
            event['parsed_date'], direction, price_index, latest_event_date
        )
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


def process_log():
    """Process the log file and generate summary"""
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            if reader.fieldnames is None:
                print("Error: CSV file appears to be empty")
                return
            
            row_count = 0
            for row in reader:
                row_count += 1
                
                # Validate required fields
                if not all(key in row for key in ['Stash', 'Account', 'Action', 'Item', 'X', 'Y']):
                    print(f"Warning: Row {row_count} missing required fields, skipping")
                    continue
                
                stash = normalize_stash_name(row['Stash'].strip())
                
                # Filter for target stashes only
                if stash not in TARGET_STASHES:
                    continue
                
                account = row['Account'].strip()
                action = row['Action'].strip()
                item = row['Item'].strip()
                
                try:
                    x = int(row['X'].strip())
                    y = int(row['Y'].strip())
                except ValueError:
                    print(f"Warning: Row {row_count} has invalid X or Y coordinates, skipping")
                    continue
                
                quantity, item_name = extract_quantity(item)
                date_value = get_csv_value(row, 'Date').strip()
                id_value = get_csv_value(row, 'Id').strip()
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
            
            print(f"Processed {row_count} rows from log file")
            calculate_operation_summaries()
            calculate_final_stash_state()
            calculate_valuation_summary()
            
    except FileNotFoundError:
        print(f"Error: Log file '{LOG_FILE}' not found")
        return
    except Exception as e:
        print(f"Error processing log file: {e}")
        return


def print_summary():
    """Generate output files per player with item breakdown grouped by stash"""
    if not stash_summary:
        print("No data to display")
        return
    
    # Create output directory if it doesn't exist
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    # Create summary file
    summary_file = os.path.join(OUTPUT_DIR, '_SUMMARY.txt')
    
    files_created = []
    
    # Get all unique players
    all_players = set()
    for stash in stash_summary.values():
        all_players.update(stash.keys())
    
    with open(summary_file, 'w', encoding='utf-8') as summary_f:
        summary_f.write("=" * 130 + "\n")
        summary_f.write("LEGACY SUMMARY NOTICE\n")
        summary_f.write(f"Stashes counted: {target_stash_label()}\n")
        summary_f.write("=" * 130 + "\n\n")
        summary_f.write("Generic typeless item-count totals have been removed.\n")
        summary_f.write("Use the individual player reports or REPORT_DASHBOARD.html for detailed per-item counts.\n")
        
        # Write each player to individual file and summary
        for player in sorted(all_players):
            # Create player file
            player_file = os.path.join(OUTPUT_DIR, f"{player}.txt")
            
            with open(player_file, 'w', encoding='utf-8') as player_f:
                player_f.write("=" * 130 + "\n")
                player_f.write(f"STASH OPERATIONS REPORT: {player}\n")
                player_f.write(f"Stashes counted: {target_stash_label()}\n")
                player_f.write("=" * 130 + "\n\n")
                
                # Iterate through each stash in order
                for stash in sorted(stash_summary.keys()):
                    if player not in stash_summary[stash]:
                        continue
                    
                    items_data = stash_summary[stash][player]
                    
                    # Write stash section
                    player_f.write(f"Stash: {stash}\n")
                    player_f.write("-" * 130 + "\n")
                    player_f.write(f"{'Item Name':<50} {'Added':>12} {'Removed':>12} {'Net Change':>12}\n")
                    player_f.write("-" * 130 + "\n")
                    
                    # Sort items by name for each stash
                    for item_name in sorted(items_data.keys()):
                        item_stats = items_data[item_name]
                        added = item_stats['added']
                        removed = item_stats['removed']
                        net = added - removed
                        
                        net_display = f"{net:+d}" if net != 0 else "0"
                        player_f.write(f"{item_name:<50} {added:>12} {removed:>12} {net_display:>12}\n")
                    
                    player_f.write("-" * 130 + "\n")
                    player_f.write("\n")
                
                player_f.write("=" * 130 + "\n")
                player_f.write("End of detailed per-item report\n")
                player_f.write("=" * 130 + "\n")
            
            files_created.append(player_file)
        summary_f.write("=" * 130 + "\n")
    
    files_created.append(summary_file)
    
    # Print completion message
    print()
    print("=" * 80)
    print("FILES CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Summary file: {summary_file}")
    print(f"\nIndividual player reports ({len(files_created) - 1} files):")
    for f in sorted(files_created[:-1]):
        print(f"  - {f}")
    print("=" * 80)
    print()


def print_stash_summary():
    """Generate output files grouped by stash with player breakdown"""
    if not stash_summary:
        print("No stash data to display")
        return
    
    # Create output directory if it doesn't exist
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    # Create master stash summary file
    master_file = os.path.join(OUTPUT_DIR, '0_STASH_MASTER_SUMMARY.txt')
    
    files_created = []
    
    with open(master_file, 'w', encoding='utf-8') as master_f:
        master_f.write("=" * 130 + "\n")
        master_f.write("LEGACY STASH SUMMARY NOTICE\n")
        master_f.write("=" * 130 + "\n\n")
        master_f.write("Generic typeless item-count totals have been removed.\n")
        master_f.write("Use STASH_*.txt or REPORT_DASHBOARD.html for detailed per-item counts.\n")
        
        # Write each stash to individual file and master summary
        for stash in sorted(stash_summary.keys()):
            accounts_data = stash_summary[stash]
            
            # Create stash file
            stash_file = os.path.join(OUTPUT_DIR, f"STASH_{safe_filename(stash)}.txt")
            
            with open(stash_file, 'w', encoding='utf-8') as stash_f:
                stash_f.write("=" * 130 + "\n")
                stash_f.write(f"STASH OPERATIONS REPORT: {stash}\n")
                stash_f.write("=" * 130 + "\n\n")
                
                # Write player sections
                for account in sorted(accounts_data.keys()):
                    items_data = accounts_data[account]
                    
                    stash_f.write(f"Player: {account}\n")
                    stash_f.write("-" * 130 + "\n")
                    stash_f.write(f"{'Item Name':<50} {'Added':>12} {'Removed':>12} {'Net Change':>12}\n")
                    stash_f.write("-" * 130 + "\n")
                    
                    # Sort items alphabetically
                    for item_name in sorted(items_data.keys()):
                        item_stats = items_data[item_name]
                        added = item_stats['added']
                        removed = item_stats['removed']
                        net = added - removed
                        
                        net_display = f"{net:+d}" if net != 0 else "0"
                        stash_f.write(f"{item_name:<50} {added:>12} {removed:>12} {net_display:>12}\n")
                    
                    stash_f.write("-" * 130 + "\n")
                    stash_f.write("\n")
                
                stash_f.write("=" * 130 + "\n")
                stash_f.write("End of detailed per-item report\n")
                stash_f.write("=" * 130 + "\n")
            
            files_created.append(stash_file)
        master_f.write("=" * 130 + "\n")
    
    files_created.append(master_file)
    
    # Print completion message
    print()
    print("=" * 80)
    print("STASH-GROUPED FILES CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Master stash summary: {master_file}")
    print(f"\nIndividual stash reports ({len(files_created) - 1} files):")
    for f in sorted(files_created[:-1]):
        print(f"  - {f}")
    print("=" * 80)
    print()


def print_final_state_summary():
    """Generate output files showing the final contents of each target stash."""
    if not final_stash_state:
        print("No final stash state data to display")
        return
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    master_file = os.path.join(OUTPUT_DIR, '0_FINAL_STATE_MASTER_SUMMARY.txt')
    files_created = []
    
    with open(master_file, 'w', encoding='utf-8') as master_f:
        master_f.write("=" * 130 + "\n")
        master_f.write("FINAL STASH STATE SUMMARY - ALL STASHES\n")
        master_f.write("=" * 130 + "\n\n")
        master_f.write(f"{'Stash':<20} {'Stacks':>12} {'Unique Items':>14}\n")
        master_f.write("-" * 130 + "\n")
        
        grand_stacks = 0
        grand_unique_items = set()
        
        for stash in sorted(TARGET_STASHES):
            positions = {
                (x, y): data
                for (state_stash, x, y), data in final_stash_state.items()
                if state_stash == stash
            }
            item_totals = defaultdict(lambda: {'quantity': 0, 'stacks': 0})
            
            for data in positions.values():
                item_totals[data['item_name']]['quantity'] += data['quantity']
                item_totals[data['item_name']]['stacks'] += 1
            
            stash_stacks = len(positions)
            stash_unique_items = len(item_totals)
            
            grand_stacks += stash_stacks
            grand_unique_items.update(item_totals.keys())
            
            final_state_file = os.path.join(OUTPUT_DIR, f"FINAL_STATE_{safe_filename(stash)}.txt")
            with open(final_state_file, 'w', encoding='utf-8') as stash_f:
                stash_f.write("=" * 130 + "\n")
                stash_f.write(f"FINAL STASH STATE REPORT: {stash}\n")
                stash_f.write("=" * 130 + "\n\n")
                
                stash_f.write("Item totals\n")
                stash_f.write("-" * 130 + "\n")
                stash_f.write(f"{'Item Name':<70} {'Quantity':>12} {'Stacks':>12}\n")
                stash_f.write("-" * 130 + "\n")
                
                for item_name in sorted(item_totals.keys()):
                    totals = item_totals[item_name]
                    stash_f.write(f"{item_name:<70} {totals['quantity']:>12} {totals['stacks']:>12}\n")
                
                stash_f.write("-" * 130 + "\n")
                stash_f.write("\n")
                
                stash_f.write("Coordinate details\n")
                stash_f.write("-" * 130 + "\n")
                stash_f.write(f"{'X':>4} {'Y':>4} {'Quantity':>12} {'Item Name':<60} {'Last Action':<12} {'Last Player':<30}\n")
                stash_f.write("-" * 130 + "\n")
                
                for (x, y), data in sorted(positions.items(), key=lambda pos: (pos[0][1], pos[0][0])):
                    stash_f.write(
                        f"{x:>4} {y:>4} {data['quantity']:>12} {data['item_name']:<60} "
                        f"{data['action']:<12} {data['account']:<30}\n"
                    )
                
                stash_f.write("=" * 130 + "\n")
            
            files_created.append(final_state_file)
            master_f.write(f"{stash:<20} {stash_stacks:>12} {stash_unique_items:>14}\n")
        
        master_f.write("-" * 130 + "\n")
        master_f.write(f"{'TOTAL':<20} {grand_stacks:>12} {len(grand_unique_items):>14}\n")
        master_f.write("=" * 130 + "\n")
    
    files_created.append(master_file)
    
    print()
    print("=" * 80)
    print("FINAL STATE FILES CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Master final state summary: {master_file}")
    print(f"\nIndividual final state reports ({len(files_created) - 1} files):")
    for f in sorted(files_created[:-1]):
        print(f"  - {f}")
    print("=" * 80)
    print()


def get_divine_to_exalted_rate():
    """Return current divine-to-exalted rate from cached currency data."""
    payload = load_cached_prices('Currency', allow_stale=True)
    if not payload:
        return 0
    return float(payload.get('core', {}).get('rates', {}).get('exalted') or 0)


def write_value_table_row(file_handle, label, added_value, removed_value, divine_to_exalted):
    """Write one value summary row in divine and exalted terms."""
    net_value = added_value - removed_value
    added_ex = added_value * divine_to_exalted if divine_to_exalted else 0
    removed_ex = removed_value * divine_to_exalted if divine_to_exalted else 0
    net_ex = net_value * divine_to_exalted if divine_to_exalted else 0
    file_handle.write(
        f"{label:<30} {added_value:>14.4f} {removed_value:>14.4f} {net_value:>14.4f} "
        f"{added_ex:>14.2f} {removed_ex:>14.2f} {net_ex:>14.2f}\n"
    )


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


def print_player_value_chart():
    """Generate one SVG chart with cumulative net value over time for each player."""
    if not player_value_timeline:
        print("No player value timeline data to chart")
        return
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    chart_file = os.path.join(OUTPUT_DIR, 'VALUE_OVER_TIME_BY_PLAYER.svg')
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    width = 1400
    height = 820
    margin_left = 90
    margin_top = 70
    margin_bottom = 90
    plot_width = 980
    plot_height = 620
    legend_x = margin_left + plot_width + 60
    
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
        '.tick { font-size: 12px; fill: #4b5563; }',
        '.title { font-size: 24px; font-weight: 700; }',
        '.subtitle { font-size: 13px; fill: #6b7280; }',
        '.legend { font-size: 13px; }',
        '</style>',
        f'<text class="title" x="{margin_left}" y="34">Total stash value over time by player</text>',
        f'<text class="subtitle" x="{margin_left}" y="56">Cumulative net value in Divine Orb, estimated from cached poe.ninja data</text>',
    ]
    
    # Y-axis grid and labels
    for value in tick_values:
        y = scale_y(value)
        svg.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_width}" y2="{y:.2f}"/>')
        svg.append(
            f'<text class="tick" x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end">{html.escape(format_axis_value(value, tick_step))}</text>'
        )
    
    # X-axis grid and labels
    for i in range(6):
        ts = min_ts + ((max_ts - min_ts) * i / 5)
        date_value = datetime.fromtimestamp(ts, tz=min_time.tzinfo)
        x = margin_left + (plot_width * i / 5)
        label = date_value.strftime('%m-%d %H:%M')
        svg.append(f'<line class="grid" x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{margin_top + plot_height}"/>')
        svg.append(
            f'<text class="tick" x="{x:.2f}" y="{margin_top + plot_height + 28}" text-anchor="middle">{html.escape(label)}</text>'
        )
    
    svg.extend([
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}"/>',
        f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}"/>',
        f'<text class="tick" x="{margin_left - 60}" y="{margin_top + plot_height / 2}" transform="rotate(-90 {margin_left - 60} {margin_top + plot_height / 2})" text-anchor="middle">Net value (Divine Orb)</text>',
        f'<text class="tick" x="{margin_left + plot_width / 2}" y="{margin_top + plot_height + 62}" text-anchor="middle">Time</text>',
        f'<text class="legend" x="{legend_x}" y="{margin_top}" font-weight="700">Player</text>',
    ])
    
    for index, player in enumerate(sorted(player_value_timeline.keys())):
        points = player_value_timeline[player]
        if not points:
            continue
        
        color = colors[index % len(colors)]
        point_string = ' '.join(
            f'{scale_x(date_value):.2f},{scale_y(value):.2f}'
            for date_value, value in points
        )
        final_value = points[-1][1]
        legend_y = margin_top + 28 + (index * 26)
        
        svg.append(
            f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="2.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        svg.append(f'<line x1="{legend_x}" y1="{legend_y - 5}" x2="{legend_x + 28}" y2="{legend_y - 5}" stroke="{color}" stroke-width="3"/>')
        svg.append(
            f'<text class="legend" x="{legend_x + 38}" y="{legend_y}">'
            f'{html.escape(player)} ({final_value:.2f} div)</text>'
        )
    
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


def write_single_value_chart(chart_file, title, subtitle, points, color='#2563eb'):
    """Write one SVG chart for a single cumulative value timeline."""
    dated_points = [
        (date_value, value)
        for date_value, value in points
        if date_value != datetime.min
    ]
    if not dated_points:
        return False
    
    width = 1100
    height = 560
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
        '.tick { font-size: 12px; fill: #4b5563; }',
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
    
    for i in range(6):
        ts = min_ts + ((max_ts - min_ts) * i / 5)
        date_value = datetime.fromtimestamp(ts, tz=min_time.tzinfo)
        x = margin_left + (plot_width * i / 5)
        label = date_value.strftime('%m-%d %H:%M')
        svg.append(f'<line class="grid" x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{margin_top + plot_height}"/>')
        svg.append(
            f'<text class="tick" x="{x:.2f}" y="{margin_top + plot_height + 28}" text-anchor="middle">{html.escape(label)}</text>'
        )
    
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
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    player_chart_files.clear()
    stash_chart_files.clear()
    
    for index, player in enumerate(sorted(player_value_timeline.keys())):
        filename = safe_chart_filename('CHART_PLAYER', player)
        chart_file = os.path.join(OUTPUT_DIR, filename)
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
        chart_file = os.path.join(OUTPUT_DIR, filename)
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


def html_table(headers, rows, class_name=''):
    """Render a simple HTML table."""
    class_attr = f' class="{class_name}"' if class_name else ''
    output = [f'<table{class_attr}>', '<thead><tr>']
    
    for header in headers:
        output.append(f'<th>{html.escape(str(header))}</th>')
    
    output.append('</tr></thead><tbody>')
    
    for row in rows:
        output.append('<tr>')
        for cell in row:
            output.append(f'<td>{html.escape(str(cell))}</td>')
        output.append('</tr>')
    
    output.append('</tbody></table>')
    return '\n'.join(output)


def format_signed(value):
    """Format signed integer values for reports."""
    return f'{value:+d}' if value != 0 else '0'


def format_value(value):
    """Format divine values for reports."""
    return f'{value:.4f}'


def collect_quantity_totals():
    """Deprecated: generic typeless quantity totals are intentionally not reported."""
    return {}, {}


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


def render_inline_chart(filename, alt_text):
    """Render a detail chart image when its SVG exists."""
    if not filename or not os.path.exists(os.path.join(OUTPUT_DIR, filename)):
        return ''
    
    return (
        '<div class="detail-chart">'
        f'<img class="chart" src="{html.escape(filename)}" alt="{html.escape(alt_text)}">'
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
        panels.append(
            f'<section id="{target_id}" class="subtab-panel{active_class}">'
            f'<div class="subtab-title">{html.escape(player)}</div>'
            f'{render_inline_chart(player_chart_files.get(player), f"{player} value over time")}'
            f'{html_table(["Stash", "Item", "Added", "Removed", "Net", "Rate", "Value"], rows)}'
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
    """Render stash detail sections for the HTML dashboard."""
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
        panels.append(
            f'<section id="{target_id}" class="subtab-panel{active_class}">'
            f'<div class="subtab-title">{html.escape(stash)}</div>'
            f'{render_inline_chart(stash_chart_files.get(stash), f"{stash} value over time")}'
            f'{html_table(["Player", "Item", "Added", "Removed", "Net", "Rate", "Value"], rows)}'
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
    """Render final stash contents for the HTML dashboard."""
    buttons = []
    panels = []
    current_rates = {}
    latest_event_date = max((event['parsed_date'] for event in log_events), default=datetime.min)
    latest_label = latest_event_date.strftime('%Y-%m-%d %H:%M:%S') if latest_event_date != datetime.min else 'unknown'
    
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
        panels.append(
            f'<section id="{target_id}" class="subtab-panel{active_class}">'
            f'<div class="subtab-title">{html.escape(stash)} <span class="subtab-meta">Last transaction: {html.escape(latest_label)}</span></div>'
            f'{html_table(["Item", "Quantity", "Stacks", "Rate", "Value"], rows)}'
            '</section>'
        )
    
    return (
        '<h2>Final state</h2>'
        '<div class="subtab-layout">'
        f'<nav class="subtab-nav" aria-label="Final state stashes">{"".join(buttons)}</nav>'
        f'<div class="subtab-content">{"".join(panels)}</div>'
        '</div>'
    )


def render_time_chart_subtabs(title, aria_label, chart_files, timelines, id_prefix):
    """Render chart images in compact left-side sub-tabs."""
    if not chart_files:
        return ''
    
    buttons = []
    panels = []
    
    for index, name in enumerate(sorted(chart_files.keys())):
        points = timelines.get(name, [])
        final_value = points[-1][1] if points else 0.0
        active_class = ' active' if index == 0 else ''
        target_id = f'{id_prefix}-chart-subtab-{index}'
        filename = chart_files[name]
        buttons.append(
            f'<button class="subtab-button{active_class}" data-subtab-target="{target_id}" data-subtab-value="{format_value(final_value)}">'
            f'<span class="subtab-label">{html.escape(name)}</span>'
            f'<span class="subtab-value">{format_value(final_value)} div</span>'
            '</button>'
        )
        panels.append(
            f'<section id="{target_id}" class="subtab-panel{active_class}">'
            f'<div class="subtab-title">{html.escape(name)}</div>'
            f'<img class="chart" src="{html.escape(filename)}" alt="{html.escape(name)} value over time">'
            '</section>'
        )
    
    return (
        f'<h3>{html.escape(title)}</h3>'
        '<div class="subtab-layout chart-subtabs">'
        f'<nav class="subtab-nav" aria-label="{html.escape(aria_label)}">{"".join(buttons)}</nav>'
        f'<div class="subtab-content">{"".join(panels)}</div>'
        '</div>'
    )


def render_chart_sections():
    """Render the combined timeline chart for the dashboard."""
    sections = ['<h2>Total value over time</h2>']
    combined_chart = 'VALUE_OVER_TIME_BY_PLAYER.svg'
    
    if os.path.exists(os.path.join(OUTPUT_DIR, combined_chart)):
        sections.append(
            '<div class="card chart-card">'
            '<h3>All players</h3>'
            f'<img class="chart" src="{combined_chart}" alt="Total stash value over time by player">'
            '</div>'
        )
    
    return '\n'.join(section for section in sections if section)


def render_value_sections():
    """Render value detail sections for the HTML dashboard."""
    sections = []
    
    for stash in sorted(valuation_summary.keys()):
        rows = []
        for account in sorted(valuation_summary[stash].keys()):
            for item_name in sorted(valuation_summary[stash][account].keys()):
                stats = valuation_summary[stash][account][item_name]
                added = stats['added_value']
                removed = stats['removed_value']
                rows.append([
                    account,
                    item_name,
                    stats['added_qty'],
                    stats['removed_qty'],
                    format_value(added),
                    format_value(removed),
                    format_value(added - removed),
                ])
        
        sections.append(
            f'<details><summary>{html.escape(stash)}</summary>'
            f'{html_table(["Player", "Item", "Added Qty", "Removed Qty", "Added Div", "Removed Div", "Net Div"], rows)}'
            '</details>'
        )
    
    return '\n'.join(sections)


def print_html_dashboard():
    """Generate a tabbed HTML dashboard as the future replacement for text reports."""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    dashboard_file = os.path.join(OUTPUT_DIR, 'REPORT_DASHBOARD.html')
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
    <title>Poe2Logger Reports</title>
    <style>
        :root {{
            color-scheme: light;
            --bg: #f8fafc;
            --panel: #ffffff;
            --text: #111827;
            --muted: #6b7280;
            --line: #d1d5db;
            --accent: #2563eb;
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
            top: 78px;
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
            overflow: auto;
        }}
        .subtab-layout {{
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 12px;
            align-items: start;
        }}
        .subtab-nav {{
            position: sticky;
            top: 140px;
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
            overflow: auto;
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
        }}
        .chart-card {{
            margin-bottom: 18px;
        }}
        .detail-chart {{
            margin-bottom: 12px;
            overflow: auto;
        }}
        .detail-chart .chart {{
            max-height: 360px;
            object-fit: contain;
        }}
        .chart-subtabs {{
            margin-bottom: 18px;
        }}
        .legacy {{
            color: var(--muted);
            margin-top: 10px;
            font-size: 13px;
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
        }}
    </style>
</head>
<body>
    <header>
        <h1>Poe2Logger Reports</h1>
        <div class="subtitle">League: {html.escape(LEAGUE_NAME)} | Stashes: {html.escape(target_stash_label())}</div>
        <div class="legacy">Text reports are still generated for now, but this dashboard is the phase-out path.</div>
    </header>
    <nav class="tabs" aria-label="Report tabs">
        <button class="tab-button active" data-tab="totals">Totals</button>
        <button class="tab-button" data-tab="by-player">By player</button>
        <button class="tab-button" data-tab="by-stash">By stash</button>
        <button class="tab-button" data-tab="final-state">Final state</button>
        <button class="tab-button" data-tab="chart">Chart</button>
        <button class="tab-button" data-tab="unpriced">Unpriced</button>
    </nav>
    <main>
        <section id="totals" class="tab-panel active">
            <div class="grid">
                <div class="card"><h2>Value by stash</h2>{html_table(["Stash", "Added Div", "Removed Div", "Net Div"], stash_value_rows)}</div>
                <div class="card"><h2>Value by player</h2>{html_table(["Player", "Added Div", "Removed Div", "Net Div"], player_value_rows)}</div>
            </div>
        </section>
        <section id="by-player" class="tab-panel">{render_player_sections()}</section>
        <section id="by-stash" class="tab-panel">{render_stash_sections()}</section>
        <section id="final-state" class="tab-panel">{render_final_state_sections()}</section>
        <section id="chart" class="tab-panel">{render_chart_sections()}</section>
        <section id="unpriced" class="tab-panel"><h2>Unpriced items</h2><div class="card">{html_table(["Item", "Added Qty", "Removed Qty"], unpriced_rows)}</div></section>
    </main>
    <footer>
        <strong>Price cache</strong>
        <div class="cache-items">{cache_footer_items}</div>
    </footer>
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
        document.querySelectorAll('table').forEach((table) => {{
            const headers = Array.from(table.querySelectorAll('th'));
            const tbody = table.querySelector('tbody');
            if (!tbody) {{
                return;
            }}
            Array.from(tbody.querySelectorAll('tr')).forEach((row, index) => {{
                row.dataset.originalIndex = index;
            }});
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
        }});
        function getTableSortGroup(table) {{
            const panel = table.closest('.tab-panel');
            return panel?.id || 'global';
        }}
        function updateSortGroup(table, columnIndex, state) {{
            const group = getTableSortGroup(table);
            document.querySelectorAll(`.tab-panel#${{group}} table`).forEach((groupTable) => {{
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


def print_value_summary():
    """Generate value reports for added and removed stash operations."""
    if not valuation_summary:
        print("No valuation data to display")
        return
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    divine_to_exalted = get_divine_to_exalted_rate()
    master_file = os.path.join(OUTPUT_DIR, '0_VALUE_MASTER_SUMMARY.txt')
    player_file = os.path.join(OUTPUT_DIR, 'VALUE_BY_PLAYER.txt')
    unpriced_file = os.path.join(OUTPUT_DIR, 'VALUE_UNPRICED_ITEMS.txt')
    files_created = []
    
    stash_totals = defaultdict(lambda: {'added_value': 0.0, 'removed_value': 0.0})
    player_totals = defaultdict(lambda: {'added_value': 0.0, 'removed_value': 0.0})
    
    for stash, accounts in valuation_summary.items():
        for account, items in accounts.items():
            for stats in items.values():
                stash_totals[stash]['added_value'] += stats['added_value']
                stash_totals[stash]['removed_value'] += stats['removed_value']
                player_totals[account]['added_value'] += stats['added_value']
                player_totals[account]['removed_value'] += stats['removed_value']
    
    with open(master_file, 'w', encoding='utf-8') as master_f:
        master_f.write("=" * 130 + "\n")
        master_f.write("ESTIMATED VALUE SUMMARY - ALL STASHES\n")
        master_f.write(f"League: {LEAGUE_NAME}\n")
        master_f.write("Values are estimated in Divine Orb using poe.ninja PoE 2 exchange data.\n")
        master_f.write("=" * 130 + "\n\n")
        master_f.write("Price cache/API status\n")
        master_f.write("-" * 130 + "\n")
        for price_type in PRICE_TYPES:
            master_f.write(f"{price_type:<20} {price_metadata.get(price_type, 'not loaded')}\n")
        master_f.write("\n")
        
        if divine_to_exalted:
            master_f.write(f"Current conversion used for display: 1 Divine Orb = {divine_to_exalted:.2f} Exalted Orb\n\n")
        
        master_f.write(
            f"{'Stash':<30} {'Added Div':>14} {'Removed Div':>14} {'Net Div':>14} "
            f"{'Added Ex':>14} {'Removed Ex':>14} {'Net Ex':>14}\n"
        )
        master_f.write("-" * 130 + "\n")
        
        total_added = 0.0
        total_removed = 0.0
        for stash in sorted(stash_totals.keys()):
            added = stash_totals[stash]['added_value']
            removed = stash_totals[stash]['removed_value']
            total_added += added
            total_removed += removed
            write_value_table_row(master_f, stash, added, removed, divine_to_exalted)
        
        master_f.write("-" * 130 + "\n")
        write_value_table_row(master_f, 'TOTAL', total_added, total_removed, divine_to_exalted)
        master_f.write("=" * 130 + "\n")
    
    with open(player_file, 'w', encoding='utf-8') as player_f:
        player_f.write("=" * 130 + "\n")
        player_f.write("ESTIMATED VALUE SUMMARY - BY PLAYER\n")
        player_f.write("=" * 130 + "\n\n")
        player_f.write(
            f"{'Player':<30} {'Added Div':>14} {'Removed Div':>14} {'Net Div':>14} "
            f"{'Added Ex':>14} {'Removed Ex':>14} {'Net Ex':>14}\n"
        )
        player_f.write("-" * 130 + "\n")
        
        total_added = 0.0
        total_removed = 0.0
        for player in sorted(player_totals.keys()):
            added = player_totals[player]['added_value']
            removed = player_totals[player]['removed_value']
            total_added += added
            total_removed += removed
            write_value_table_row(player_f, player, added, removed, divine_to_exalted)
        
        player_f.write("-" * 130 + "\n")
        write_value_table_row(player_f, 'TOTAL', total_added, total_removed, divine_to_exalted)
        player_f.write("=" * 130 + "\n")
    
    files_created.extend([master_file, player_file])
    
    for stash in sorted(valuation_summary.keys()):
        stash_file = os.path.join(OUTPUT_DIR, f"VALUE_STASH_{safe_filename(stash)}.txt")
        
        with open(stash_file, 'w', encoding='utf-8') as stash_f:
            stash_f.write("=" * 130 + "\n")
            stash_f.write(f"ESTIMATED VALUE REPORT: {stash}\n")
            stash_f.write("=" * 130 + "\n\n")
            
            for account in sorted(valuation_summary[stash].keys()):
                account_items = valuation_summary[stash][account]
                account_added = sum(stats['added_value'] for stats in account_items.values())
                account_removed = sum(stats['removed_value'] for stats in account_items.values())
                
                stash_f.write(f"Player: {account}\n")
                stash_f.write("-" * 130 + "\n")
                stash_f.write(
                    f"{'Item Name':<50} {'Added Qty':>10} {'Removed Qty':>12} "
                    f"{'Added Div':>12} {'Removed Div':>12} {'Net Div':>12}\n"
                )
                stash_f.write("-" * 130 + "\n")
                
                for item_name in sorted(account_items.keys()):
                    stats = account_items[item_name]
                    added_value = stats['added_value']
                    removed_value = stats['removed_value']
                    net_value = added_value - removed_value
                    stash_f.write(
                        f"{item_name:<50} {stats['added_qty']:>10} {stats['removed_qty']:>12} "
                        f"{added_value:>12.4f} {removed_value:>12.4f} {net_value:>12.4f}\n"
                    )
                
                stash_f.write("-" * 130 + "\n")
                stash_f.write(
                    f"{'  PLAYER TOTAL':<50} {'':>10} {'':>12} "
                    f"{account_added:>12.4f} {account_removed:>12.4f} {account_added - account_removed:>12.4f}\n\n"
                )
            
            stash_total = stash_totals[stash]
            stash_f.write("=" * 130 + "\n")
            stash_f.write(
                f"{'STASH TOTAL':<50} {'':>10} {'':>12} "
                f"{stash_total['added_value']:>12.4f} {stash_total['removed_value']:>12.4f} "
                f"{stash_total['added_value'] - stash_total['removed_value']:>12.4f}\n"
            )
            stash_f.write("=" * 130 + "\n")
        
        files_created.append(stash_file)
    
    with open(unpriced_file, 'w', encoding='utf-8') as unpriced_f:
        unpriced_f.write("=" * 130 + "\n")
        unpriced_f.write("UNPRICED ITEMS\n")
        unpriced_f.write("These items were counted in quantity reports but had no matching poe.ninja exchange price.\n")
        unpriced_f.write("=" * 130 + "\n\n")
        unpriced_f.write(f"{'Item Name':<70} {'Added Qty':>12} {'Removed Qty':>12}\n")
        unpriced_f.write("-" * 130 + "\n")
        
        for item_name in sorted(unpriced_summary.keys()):
            stats = unpriced_summary[item_name]
            unpriced_f.write(f"{item_name:<70} {stats['added_qty']:>12} {stats['removed_qty']:>12}\n")
        
        unpriced_f.write("=" * 130 + "\n")
    
    files_created.append(unpriced_file)
    
    print()
    print("=" * 80)
    print("VALUE FILES CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Master value summary: {master_file}")
    print(f"Player value summary: {player_file}")
    print(f"Unpriced items: {unpriced_file}")
    print(f"\nIndividual stash value reports ({len(files_created) - 3} files):")
    for f in sorted(files_created[2:-1]):
        print(f"  - {f}")
    print("=" * 80)
    print()


if __name__ == '__main__':
    process_log()
    print_summary()
    print_stash_summary()
    print_final_state_summary()
    print_value_summary()
    print_player_value_chart()
    print_individual_value_charts()
    print_html_dashboard()
