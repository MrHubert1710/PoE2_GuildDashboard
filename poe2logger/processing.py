import csv
import os
from datetime import datetime, timezone

from .config import CSV_FIELDNAMES, HISTORY_FILENAME, LOG_DIR
from .private_config import LEAGUE_NAME, TARGET_STASHES
from .prices import calculate_valuation_summary
from .state import (coordinate_state, final_stash_state, log_events, movement_log, player_chart_files, player_summary, player_value_timeline, price_metadata, stash_chart_files, stash_summary, stash_value_timeline, unpriced_summary, valuation_summary)
from .utils import extract_quantity, get_csv_value, get_csv_league, normalize_stash_name, parse_event_date, parse_event_id

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
    
    final_stash_state.clear()
    final_stash_state.update(state)


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
    if row.get('Id'):
        return ('id', row['Id'])
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

