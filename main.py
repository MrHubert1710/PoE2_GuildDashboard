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
    sparkline = price_data.get('sparkline') or []
    
    if not sparkline or latest_event_date == datetime.min or event_date == datetime.min:
        return current_value
    
    days_ago = (latest_event_date.date() - event_date.date()).days
    index = len(sparkline) - 1 - days_ago
    
    if index < 0 or index >= len(sparkline):
        return current_value
    
    current_change = sparkline[-1]
    event_change = sparkline[index]
    
    if current_change is None or event_change is None or current_change <= -100:
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
    
    def apply_value_change(event, item_name, quantity, direction):
        value = add_valuation_entry(
            event['account'], event['stash'], item_name, quantity,
            event['parsed_date'], direction, price_index, latest_event_date
        )
        if value <= 0:
            return
        
        if direction == 'added':
            player_cumulative[event['account']] += value
        else:
            player_cumulative[event['account']] -= value
        
        if event['parsed_date'] != datetime.min:
            player_value_timeline[event['account']].append((
                event['parsed_date'],
                player_cumulative[event['account']],
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
                
                coord_key = (stash, x, y)
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
                
                if action == 'added':
                    player_summary[account][item_name]['added'] += quantity
                    stash_summary[stash][account][item_name]['added'] += quantity
                    coordinate_state[coord_key] = (coordinate_state.get(coord_key, (0, ''))[0] + quantity, item_name)
                    
                elif action == 'removed':
                    player_summary[account][item_name]['removed'] += quantity
                    stash_summary[stash][account][item_name]['removed'] += quantity
                    old_qty, old_name = coordinate_state.get(coord_key, (0, ''))
                    coordinate_state[coord_key] = (old_qty - quantity, item_name)
                    
                elif action == 'modified':
                    old_quantity, old_name = coordinate_state.get(coord_key, (0, ''))
                    new_quantity = quantity
                    delta = new_quantity - old_quantity
                    
                    if delta > 0:
                        player_summary[account][item_name]['added'] += delta
                        stash_summary[stash][account][item_name]['added'] += delta
                    elif delta < 0:
                        player_summary[account][item_name]['removed'] += abs(delta)
                        stash_summary[stash][account][item_name]['removed'] += abs(delta)
                    
                    coordinate_state[coord_key] = (new_quantity, item_name)
            
            print(f"Processed {row_count} rows from log file")
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
    
    total_added = 0
    total_removed = 0
    files_created = []
    
    # Get all unique players
    all_players = set()
    for stash in stash_summary.values():
        all_players.update(stash.keys())
    
    with open(summary_file, 'w', encoding='utf-8') as summary_f:
        # Write header
        summary_f.write("=" * 130 + "\n")
        summary_f.write("STASH OPERATIONS SUMMARY - ALL PLAYERS\n")
        summary_f.write(f"Stashes counted: {target_stash_label()}\n")
        summary_f.write("=" * 130 + "\n\n")
        summary_f.write(f"{'Player':<30} {'Added':>12} {'Removed':>12} {'Net Change':>12}\n")
        summary_f.write("-" * 130 + "\n")
        
        # Write each player to individual file and summary
        for player in sorted(all_players):
            player_added = 0
            player_removed = 0
            
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
                    stash_added = 0
                    stash_removed = 0
                    
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
                        
                        stash_added += added
                        stash_removed += removed
                        player_added += added
                        player_removed += removed
                        
                        net_display = f"{net:+d}" if net != 0 else "0"
                        player_f.write(f"{item_name:<50} {added:>12} {removed:>12} {net_display:>12}\n")
                    
                    stash_net = stash_added - stash_removed
                    stash_net_display = f"{stash_net:+d}"
                    player_f.write("-" * 130 + "\n")
                    player_f.write(f"{'  STASH TOTAL':<50} {stash_added:>12} {stash_removed:>12} {stash_net_display:>12}\n")
                    player_f.write("\n")
                
                player_net = player_added - player_removed
                player_net_display = f"{player_net:+d}"
                player_f.write("=" * 130 + "\n")
                player_f.write(f"{'PLAYER TOTAL':<50} {player_added:>12} {player_removed:>12} {player_net_display:>12}\n")
                player_f.write("=" * 130 + "\n")
            
            files_created.append(player_file)
            total_added += player_added
            total_removed += player_removed
            
            # Add to summary
            player_net = player_added - player_removed
            player_net_display = f"{player_net:+d}"
            summary_f.write(f"{player:<30} {player_added:>12} {player_removed:>12} {player_net_display:>12}\n")
        
        # Write summary totals
        summary_f.write("-" * 130 + "\n")
        total_net = total_added - total_removed
        total_net_display = f"{total_net:+d}"
        summary_f.write(f"{'TOTAL':<30} {total_added:>12} {total_removed:>12} {total_net_display:>12}\n")
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
    
    total_added = 0
    total_removed = 0
    files_created = []
    
    with open(master_file, 'w', encoding='utf-8') as master_f:
        # Write header
        master_f.write("=" * 130 + "\n")
        master_f.write("STASH OPERATIONS SUMMARY - ALL STASHES\n")
        master_f.write("=" * 130 + "\n\n")
        master_f.write(f"{'Stash':<20} {'Added':>12} {'Removed':>12} {'Net Change':>12}\n")
        master_f.write("-" * 130 + "\n")
        
        # Write each stash to individual file and master summary
        for stash in sorted(stash_summary.keys()):
            accounts_data = stash_summary[stash]
            stash_added = 0
            stash_removed = 0
            
            # Create stash file
            stash_file = os.path.join(OUTPUT_DIR, f"STASH_{safe_filename(stash)}.txt")
            
            with open(stash_file, 'w', encoding='utf-8') as stash_f:
                stash_f.write("=" * 130 + "\n")
                stash_f.write(f"STASH OPERATIONS REPORT: {stash}\n")
                stash_f.write("=" * 130 + "\n\n")
                
                # Write player sections
                for account in sorted(accounts_data.keys()):
                    items_data = accounts_data[account]
                    account_added = 0
                    account_removed = 0
                    
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
                        
                        account_added += added
                        account_removed += removed
                        stash_added += added
                        stash_removed += removed
                        
                        net_display = f"{net:+d}" if net != 0 else "0"
                        stash_f.write(f"{item_name:<50} {added:>12} {removed:>12} {net_display:>12}\n")
                    
                    account_net = account_added - account_removed
                    account_net_display = f"{account_net:+d}"
                    stash_f.write("-" * 130 + "\n")
                    stash_f.write(f"{'  PLAYER TOTAL':<50} {account_added:>12} {account_removed:>12} {account_net_display:>12}\n")
                    stash_f.write("\n")
                
                stash_net = stash_added - stash_removed
                stash_net_display = f"{stash_net:+d}"
                stash_f.write("=" * 130 + "\n")
                stash_f.write(f"{'STASH TOTAL':<50} {stash_added:>12} {stash_removed:>12} {stash_net_display:>12}\n")
                stash_f.write("=" * 130 + "\n")
            
            files_created.append(stash_file)
            total_added += stash_added
            total_removed += stash_removed
            
            # Add to master summary
            stash_net = stash_added - stash_removed
            stash_net_display = f"{stash_net:+d}"
            master_f.write(f"{stash:<20} {stash_added:>12} {stash_removed:>12} {stash_net_display:>12}\n")
        
        # Write master totals
        master_f.write("-" * 130 + "\n")
        total_net = total_added - total_removed
        total_net_display = f"{total_net:+d}"
        master_f.write(f"{'TOTAL':<20} {total_added:>12} {total_removed:>12} {total_net_display:>12}\n")
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
        master_f.write(f"{'Stash':<20} {'Total Quantity':>16} {'Stacks':>12} {'Unique Items':>14}\n")
        master_f.write("-" * 130 + "\n")
        
        grand_quantity = 0
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
            
            stash_quantity = sum(data['quantity'] for data in positions.values())
            stash_stacks = len(positions)
            stash_unique_items = len(item_totals)
            
            grand_quantity += stash_quantity
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
                stash_f.write(f"{'STASH TOTAL':<70} {stash_quantity:>12} {stash_stacks:>12}\n")
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
            master_f.write(f"{stash:<20} {stash_quantity:>16} {stash_stacks:>12} {stash_unique_items:>14}\n")
        
        master_f.write("-" * 130 + "\n")
        master_f.write(f"{'TOTAL':<20} {grand_quantity:>16} {grand_stacks:>12} {len(grand_unique_items):>14}\n")
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
    min_value = min(0.0, min(point[1] for point in all_points))
    max_value = max(0.0, max(point[1] for point in all_points))
    
    if min_value == max_value:
        min_value -= 1
        max_value += 1
    else:
        padding = (max_value - min_value) * 0.08
        min_value -= padding
        max_value += padding
    
    min_ts = min_time.timestamp()
    max_ts = max_time.timestamp()
    if min_ts == max_ts:
        min_ts -= 1
        max_ts += 1
    
    def scale_x(date_value):
        return margin_left + ((date_value.timestamp() - min_ts) / (max_ts - min_ts)) * plot_width
    
    def scale_y(value):
        return margin_top + ((max_value - value) / (max_value - min_value)) * plot_height
    
    def fmt_value(value):
        if abs(value) >= 100:
            return f'{value:.0f}'
        if abs(value) >= 10:
            return f'{value:.1f}'
        return f'{value:.2f}'
    
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
    for i in range(6):
        value = min_value + ((max_value - min_value) * i / 5)
        y = scale_y(value)
        svg.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_width}" y2="{y:.2f}"/>')
        svg.append(
            f'<text class="tick" x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end">{html.escape(fmt_value(value))}</text>'
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
    """Collect quantity totals by player and stash."""
    player_totals = defaultdict(lambda: {'added': 0, 'removed': 0})
    stash_totals = defaultdict(lambda: {'added': 0, 'removed': 0})
    
    for stash, accounts in stash_summary.items():
        for account, items in accounts.items():
            for stats in items.values():
                player_totals[account]['added'] += stats['added']
                player_totals[account]['removed'] += stats['removed']
                stash_totals[stash]['added'] += stats['added']
                stash_totals[stash]['removed'] += stats['removed']
    
    return player_totals, stash_totals


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


def render_player_sections():
    """Render player detail sections for the HTML dashboard."""
    sections = []
    
    all_players = set()
    for accounts in stash_summary.values():
        all_players.update(accounts.keys())
    
    for player in sorted(all_players):
        rows = []
        for stash in sorted(stash_summary.keys()):
            if player not in stash_summary[stash]:
                continue
            
            for item_name in sorted(stash_summary[stash][player].keys()):
                stats = stash_summary[stash][player][item_name]
                net = stats['added'] - stats['removed']
                rows.append([stash, item_name, stats['added'], stats['removed'], format_signed(net)])
        
        sections.append(
            f'<details><summary>{html.escape(player)}</summary>'
            f'{html_table(["Stash", "Item", "Added", "Removed", "Net"], rows)}'
            '</details>'
        )
    
    return '\n'.join(sections)


def render_stash_sections():
    """Render stash detail sections for the HTML dashboard."""
    sections = []
    
    for stash in sorted(stash_summary.keys()):
        rows = []
        for account in sorted(stash_summary[stash].keys()):
            for item_name in sorted(stash_summary[stash][account].keys()):
                stats = stash_summary[stash][account][item_name]
                net = stats['added'] - stats['removed']
                rows.append([account, item_name, stats['added'], stats['removed'], format_signed(net)])
        
        sections.append(
            f'<details><summary>{html.escape(stash)}</summary>'
            f'{html_table(["Player", "Item", "Added", "Removed", "Net"], rows)}'
            '</details>'
        )
    
    return '\n'.join(sections)


def render_final_state_sections():
    """Render final stash contents for the HTML dashboard."""
    sections = []
    
    for stash in sorted(TARGET_STASHES):
        item_totals = defaultdict(lambda: {'quantity': 0, 'stacks': 0})
        for (state_stash, x, y), data in final_stash_state.items():
            if state_stash != stash:
                continue
            item_totals[data['item_name']]['quantity'] += data['quantity']
            item_totals[data['item_name']]['stacks'] += 1
        
        rows = [
            [item_name, totals['quantity'], totals['stacks']]
            for item_name, totals in sorted(item_totals.items())
        ]
        sections.append(
            f'<details><summary>{html.escape(stash)}</summary>'
            f'{html_table(["Item", "Quantity", "Stacks"], rows)}'
            '</details>'
        )
    
    return '\n'.join(sections)


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
    player_quantity_totals, stash_quantity_totals = collect_quantity_totals()
    player_value_totals, stash_value_totals = collect_value_totals()
    
    stash_quantity_rows = []
    for stash in sorted(stash_quantity_totals.keys()):
        stats = stash_quantity_totals[stash]
        stash_quantity_rows.append([stash, stats['added'], stats['removed'], format_signed(stats['added'] - stats['removed'])])
    
    player_quantity_rows = []
    for player in sorted(player_quantity_totals.keys()):
        stats = player_quantity_totals[player]
        player_quantity_rows.append([player, stats['added'], stats['removed'], format_signed(stats['added'] - stats['removed'])])
    
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
    
    cache_rows = [[price_type, price_metadata.get(price_type, 'not loaded')] for price_type in PRICE_TYPES]
    unpriced_rows = [
        [item_name, stats['added_qty'], stats['removed_qty']]
        for item_name, stats in sorted(unpriced_summary.items())
    ]
    
    chart_path = 'VALUE_OVER_TIME_BY_PLAYER.svg'
    chart_html = ''
    if os.path.exists(os.path.join(OUTPUT_DIR, chart_path)):
        chart_html = f'<img class="chart" src="{chart_path}" alt="Total stash value over time by player">'
    
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
        .legacy {{
            color: var(--muted);
            margin-top: 10px;
            font-size: 13px;
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
        <button class="tab-button" data-tab="values">Values</button>
        <button class="tab-button" data-tab="final-state">Final state</button>
        <button class="tab-button" data-tab="chart">Chart</button>
        <button class="tab-button" data-tab="unpriced">Unpriced</button>
    </nav>
    <main>
        <section id="totals" class="tab-panel active">
            <div class="grid">
                <div class="card"><h2>Quantity by stash</h2>{html_table(["Stash", "Added", "Removed", "Net"], stash_quantity_rows)}</div>
                <div class="card"><h2>Quantity by player</h2>{html_table(["Player", "Added", "Removed", "Net"], player_quantity_rows)}</div>
                <div class="card"><h2>Value by stash</h2>{html_table(["Stash", "Added Div", "Removed Div", "Net Div"], stash_value_rows)}</div>
                <div class="card"><h2>Value by player</h2>{html_table(["Player", "Added Div", "Removed Div", "Net Div"], player_value_rows)}</div>
                <div class="card"><h2>Price cache</h2>{html_table(["Category", "Status"], cache_rows)}</div>
            </div>
        </section>
        <section id="by-player" class="tab-panel"><h2>By player</h2>{render_player_sections()}</section>
        <section id="by-stash" class="tab-panel"><h2>By stash</h2>{render_stash_sections()}</section>
        <section id="values" class="tab-panel"><h2>Values</h2>{render_value_sections()}</section>
        <section id="final-state" class="tab-panel"><h2>Final state</h2>{render_final_state_sections()}</section>
        <section id="chart" class="tab-panel"><h2>Total value over time</h2>{chart_html}</section>
        <section id="unpriced" class="tab-panel"><h2>Unpriced items</h2><div class="card">{html_table(["Item", "Added Qty", "Removed Qty"], unpriced_rows)}</div></section>
    </main>
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
