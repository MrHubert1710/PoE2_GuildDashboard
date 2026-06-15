import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.parse
import urllib.request

from .config import (
    CSV_FIELDNAMES,
    HISTORY_FETCH_DELAY_SECONDS,
    HISTORY_FETCH_MAX_RETRIES,
    HISTORY_FETCH_OVERLAP_DAYS,
    HISTORY_FILENAME,
    LOG_DIR,
    POE_API_USER_AGENT,
    POE_GUILD_HISTORY_URL,
    RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS,
    RATE_LIMIT_SAFETY_MARGIN,
)
from .private_config import GUILD_ID, LEAGUE_NAME, SESSION_ID
from .utils import display_event_datetime, get_csv_value, get_csv_league, normalize_stash_name, parse_event_date, parse_event_id

def first_present(mapping, keys, default=''):
    """Return the first non-empty value from possible API field names."""
    for key in keys:
        if key in mapping and mapping[key] not in (None, ''):
            return mapping[key]
    return default


def normalize_api_datetime(value):
    """Convert API timestamp/date values into the CSV UTC ISO format."""
    if value in (None, ''):
        return ''
    
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    
    value = str(value).strip()
    if value.isdigit():
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    
    parsed = parse_event_date(value)
    if parsed != datetime.min:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    
    return value


def extract_history_entries(payload):
    """Extract a transaction list from known/likely guild history response shapes."""
    if isinstance(payload, list):
        return payload
    
    if not isinstance(payload, dict):
        return []
    
    for key in ['entries', 'history', 'transactions', 'events', 'data', 'result']:
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            entries = extract_history_entries(value)
            if entries:
                return entries
    
    return []


def api_entry_to_csv_row(entry):
    """Convert one guild history API entry into the canonical CSV schema."""
    if not isinstance(entry, dict):
        return None
    
    stash = first_present(entry, ['Stash', 'stash', 'stashName', 'stash_name', 'tab', 'tabName'])
    item = first_present(entry, ['Item', 'item', 'itemName', 'item_name', 'name'])
    if isinstance(item, dict):
        item = first_present(item, ['name', 'itemName', 'typeLine', 'baseType', 'displayName'])
    account = first_present(entry, ['Account', 'account', 'accountName', 'account_name', 'user', 'player'])
    if isinstance(account, dict):
        account = first_present(account, ['name', 'accountName', 'account_name', 'id'])
    
    normalized = {
        'Date': normalize_api_datetime(first_present(entry, ['Date', 'date', 'time', 'timestamp', 'createdAt', 'created_at'])),
        'Id': str(first_present(entry, ['Id', 'id', 'transactionId', 'transaction_id', 'historyId', 'history_id'])).strip(),
        'League': str(first_present(entry, ['League', 'league'], LEAGUE_NAME)).strip(),
        'Account': str(account).strip(),
        'Action': str(first_present(entry, ['Action', 'action', 'event', 'type'])).strip(),
        'Stash': normalize_stash_name(str(stash).strip()),
        'Item': str(item).strip(),
        'X': str(first_present(entry, ['X', 'x', 'left', 'column'], '')).strip(),
        'Y': str(first_present(entry, ['Y', 'y', 'top', 'row'], '')).strip(),
    }
    
    if any(normalized[field_name] == '' for field_name in CSV_FIELDNAMES):
        return None
    
    return normalized


def entry_cursor(entry):
    """Return the pagination cursor id from an API entry."""
    if not isinstance(entry, dict):
        return ''
    return str(first_present(entry, ['Id', 'id', 'transactionId', 'transaction_id', 'historyId', 'history_id'])).strip()


def entry_timestamp(entry):
    """Return the pagination cursor timestamp from an API entry."""
    if not isinstance(entry, dict):
        return ''
    return str(first_present(entry, ['time', 'timestamp', 'Date', 'date', 'createdAt', 'created_at'])).strip()


def response_is_truncated(payload):
    """Return whether a guild history response has more pages."""
    if isinstance(payload, dict):
        return bool(payload.get('truncated', False))
    return False


def history_file_path():
    """Return the canonical merged history path."""
    return os.path.join(LOG_DIR, HISTORY_FILENAME)


def build_raw_event_key(row):
    """Build a stable identity for de-duplicating raw CSV transactions."""
    if row.get('Id'):
        return ('id', row['Id'])
    return tuple(row[field_name] for field_name in CSV_FIELDNAMES)


def read_latest_history_row():
    """Return the newest transaction row from history.csv."""
    path = history_file_path()
    if not os.path.exists(path):
        return None
    
    latest_row = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), 0)
    
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            
            for row in reader:
                date_value = parse_event_date(get_csv_value(row, 'Date').strip())
                if date_value == datetime.min:
                    date_value = datetime.min.replace(tzinfo=timezone.utc)
                id_value = parse_event_id(get_csv_value(row, 'Id').strip())
                key = (date_value, id_value)
                if key > latest_key:
                    latest_key = key
                    latest_row = row
    except OSError as e:
        print(f"Warning: Could not read '{path}' for fetch defaults: {e}")
        return None
    
    return latest_row


def local_day_start_timestamp(date_value, overlap_days=0):
    """Return UTC Unix time for local midnight before date_value, with optional day overlap."""
    local_date = display_event_datetime(date_value)
    local_day_start = local_date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=overlap_days)
    return int(local_day_start.astimezone(timezone.utc).timestamp())


def default_history_fetch_bounds(fetch_timestamp):
    """Return automatic history fetch bounds with date overlap."""
    latest_row = read_latest_history_row()
    if latest_row is None:
        end_timestamp = fetch_timestamp - 24 * 60 * 60
        return fetch_timestamp, end_timestamp, ''
    
    latest_date = parse_event_date(get_csv_value(latest_row, 'Date').strip())
    if latest_date == datetime.min:
        end_timestamp = fetch_timestamp - 24 * 60 * 60
    else:
        end_timestamp = local_day_start_timestamp(latest_date, HISTORY_FETCH_OVERLAP_DAYS)
    
    return fetch_timestamp, end_timestamp, ''


def fetch_history_output_path(fetch_timestamp):
    """Return a unique raw fetched-history CSV path for this run."""
    return os.path.join(LOG_DIR, f'history_fetch_{fetch_timestamp}.csv')


def parse_rate_limit_triples(value):
    """Parse comma-delimited Path of Exile rate-limit triples."""
    triples = []
    for chunk in str(value or '').split(','):
        parts = chunk.strip().split(':')
        if len(parts) != 3:
            continue
        try:
            triples.append(tuple(int(part) for part in parts))
        except ValueError:
            continue
    return triples


def header_int(headers, name, default=0):
    """Read an integer response header."""
    try:
        return int(headers.get(name, default) or default)
    except (TypeError, ValueError):
        return default


def rate_limit_wait_seconds(headers):
    """Return how long to wait based on Path of Exile rate-limit headers."""
    wait_seconds = max(0, header_int(headers, 'Retry-After', 0))
    rules = [
        rule.strip()
        for rule in str(headers.get('X-Rate-Limit-Rules', '')).split(',')
        if rule.strip()
    ]
    
    for rule in rules:
        limits = parse_rate_limit_triples(headers.get(f'X-Rate-Limit-{rule}', ''))
        states = parse_rate_limit_triples(headers.get(f'X-Rate-Limit-{rule}-State', ''))
        for index, state in enumerate(states):
            current_hits, period_seconds, active_restriction = state
            max_hits, limit_period, restriction_seconds = limits[index] if index < len(limits) else (0, period_seconds, 0)
            
            if active_restriction > 0:
                wait_seconds = max(wait_seconds, active_restriction)
                continue
            
            if max_hits > 0 and current_hits >= max_hits - RATE_LIMIT_SAFETY_MARGIN:
                wait_seconds = max(wait_seconds, limit_period or period_seconds or restriction_seconds)
    
    return wait_seconds


def sleep_for_rate_limit(headers):
    """Sleep when response headers indicate the next request should wait."""
    wait_seconds = rate_limit_wait_seconds(headers)
    if wait_seconds <= 0:
        return
    
    wait_seconds += 1
    print(f"Rate limit guard: waiting {wait_seconds}s before next guild history request")
    time.sleep(wait_seconds)


def build_guild_history_request(guild_id, session_id, from_timestamp, end_timestamp, from_id=''):
    """Build one guild history request."""
    params = {
        'from': str(from_timestamp),
        'end': str(end_timestamp),
    }
    if from_id:
        params['fromid'] = str(from_id)
    
    url = POE_GUILD_HISTORY_URL.format(guild_id=urllib.parse.quote(str(guild_id), safe='')) + '?' + urllib.parse.urlencode(params)
    return urllib.request.Request(
        url,
        headers={
            'User-Agent': POE_API_USER_AGENT,
            'Accept': 'application/json',
            'Cookie': f'POESESSID={session_id}',
        },
    )


def request_guild_history_page(guild_id, session_id, from_timestamp, end_timestamp, from_id=''):
    """Fetch one page and return payload plus response headers."""
    request = build_guild_history_request(guild_id, session_id, from_timestamp, end_timestamp, from_id)
    
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode('utf-8')), response.headers


def fetch_guild_history_page(guild_id, session_id, from_timestamp, end_timestamp, from_id=''):
    """Fetch one page of guild stash history from pathofexile.com."""
    payload, _headers = request_guild_history_page(guild_id, session_id, from_timestamp, end_timestamp, from_id)
    return payload


def fetch_guild_history_page_with_retries(guild_id, session_id, from_timestamp, end_timestamp, from_id=''):
    """Fetch a guild history page while respecting retry/rate-limit responses."""
    attempt = 0
    while True:
        try:
            payload, headers = request_guild_history_page(guild_id, session_id, from_timestamp, end_timestamp, from_id)
            return payload, headers
        except urllib.error.HTTPError as e:
            retry_after = header_int(e.headers, 'Retry-After', 0)
            if e.code == 429:
                if attempt >= HISTORY_FETCH_MAX_RETRIES:
                    raise
                wait_seconds = max(retry_after, rate_limit_wait_seconds(e.headers), RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS) + 1
                print(f"Rate limited by Path of Exile API; waiting {wait_seconds}s before retry")
                time.sleep(wait_seconds)
            elif e.code in (500, 502, 503, 504):
                if attempt >= HISTORY_FETCH_MAX_RETRIES:
                    raise
                wait_seconds = max(retry_after, RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS, 2 ** attempt)
                print(f"Temporary API error {e.code}; waiting {wait_seconds}s before retry")
                time.sleep(wait_seconds)
            else:
                raise
        except urllib.error.URLError:
            if attempt >= HISTORY_FETCH_MAX_RETRIES:
                raise
            wait_seconds = max(RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS, 2 ** attempt)
            print(f"Network error while fetching guild history; waiting {wait_seconds}s before retry")
            time.sleep(wait_seconds)
        
        attempt += 1


def fetch_guild_history(args):
    """Fetch guild stash history into a temporary CSV source for the merge step."""
    guild_id = args.guild_id or os.environ.get('POE_GUILD_ID', '') or GUILD_ID
    session_id = args.session_id or os.environ.get('POESESSID', '') or os.environ.get('POE_SESSION_ID', '') or SESSION_ID
    
    if not guild_id:
        raise ValueError('Missing guild id. Pass --guild-id, set POE_GUILD_ID, or set GUILD_ID in config.py.')
    if not session_id:
        raise ValueError('Missing session id. Pass --session-id, set POESESSID, or set SESSION_ID in config.py.')
    
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    fetch_timestamp = int(time.time())
    default_from, default_end, default_from_id = default_history_fetch_bounds(fetch_timestamp)
    from_timestamp = args.from_timestamp or str(default_from)
    end_timestamp = args.end_timestamp or str(default_end)
    from_id = args.from_id or default_from_id
    fetched_rows = {}
    
    print(
        f"Fetching guild history from={from_timestamp} end={end_timestamp} "
        f"fromid={from_id or 'none'} overlap_days={HISTORY_FETCH_OVERLAP_DAYS}"
    )
    
    page_number = 1
    while True:
        payload, headers = fetch_guild_history_page_with_retries(guild_id, session_id, from_timestamp, end_timestamp, from_id)
        entries = extract_history_entries(payload)
        if not entries:
            print(f"Fetched page {page_number}: no entries returned")
            sleep_for_rate_limit(headers)
            break
        
        page_new_rows = 0
        for entry in entries:
            normalized = api_entry_to_csv_row(entry)
            if normalized is None:
                continue
            event_key = build_raw_event_key(normalized)
            if event_key in fetched_rows:
                continue
            fetched_rows[event_key] = normalized
            page_new_rows += 1
        
        next_from_timestamp = entry_timestamp(entries[-1])
        next_from_id = entry_cursor(entries[-1])
        truncated = response_is_truncated(payload)
        print(
            f"Fetched page {page_number}: {len(entries)} entries, {page_new_rows} usable new rows, "
            f"truncated={truncated}, next from={next_from_timestamp or 'none'} fromid={next_from_id or 'none'}"
        )
        
        if not truncated:
            break
        if not next_from_timestamp or not next_from_id:
            break
        if next_from_timestamp == str(from_timestamp) and next_from_id == from_id:
            break
        
        from_timestamp = next_from_timestamp
        from_id = next_from_id
        page_number += 1
        sleep_for_rate_limit(headers)
        time.sleep(HISTORY_FETCH_DELAY_SECONDS)
    
    if not fetched_rows:
        print("No usable guild history rows fetched")
        return None
    
    output_path = fetch_history_output_path(fetch_timestamp)
    ordered_rows = sorted(
        fetched_rows.values(),
        key=lambda row: (parse_event_date(row['Date']), parse_event_id(row['Id']))
    )
    
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(ordered_rows)
    
    print(f"Fetched {len(ordered_rows)} guild history rows into {output_path}")
    return output_path
