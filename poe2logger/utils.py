import os
import re
from datetime import datetime, timezone

from .config import CHART_DIR, OUTPUT_DIR
from .private_config import DISPLAY_TIMEZONE, STASH_ALIASES, TARGET_STASHES
from .state import log_events

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


