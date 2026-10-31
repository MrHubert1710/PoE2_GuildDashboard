import os
from .league_paths import league_paths
from .private_config import LEAGUE_NAME


LEAGUE_PATHS = league_paths(LEAGUE_NAME)
LEGACY_LOG_DIR = 'logs'
LOG_DIR = os.fspath(LEAGUE_PATHS.logs)
HISTORY_FILENAME = 'history.csv'
LATEST_DASHBOARD_NAME = 'GuildReport_Latest.html'
LATEST_DASHBOARD_FILE = os.fspath(LEAGUE_PATHS.latest_dashboard)
LEGACY_DASHBOARD_FILE = LATEST_DASHBOARD_NAME
API_COOLDOWN_FILE = os.path.join(LEGACY_LOG_DIR, 'api_cooldown.json')
CSV_FIELDNAMES = ['Date', 'Id', 'League', 'Account', 'Action', 'Stash', 'Item', 'X', 'Y']
OUTPUT_DIR = os.fspath(LEAGUE_PATHS.reports)
CHART_DIR = os.path.join(OUTPUT_DIR, 'charts')
PRICE_CACHE_DIR = os.path.join(OUTPUT_DIR, 'price_cache')
PRICE_CACHE_MAX_AGE_HOURS = 12
POE_NINJA_PRICE_URL = 'https://poe.ninja/poe2/api/economy/exchange/current/overview'
POE_GUILD_HISTORY_URL = 'https://www.pathofexile.com/api/guild/{guild_id}/stash/history'
POE_API_USER_AGENT = 'OAuth Poe2Logger/1.0.0 (contact: local)'
PRICE_TYPES = [
    'Currency',
    'Fragments',
    'Abyss',
    'UncutGems',
    'LineageSupportGems',
    'Essences',
    'SoulCores',
    'Idols',
    'Runes',
    'Ritual',
    'Expedition',
    'Delirium',
    'Breach',
    'Verisium',
]
HISTORY_FETCH_OVERLAP_DAYS = 0.2
HISTORY_FETCH_DELAY_SECONDS = 0.3
HISTORY_FETCH_MAX_RETRIES = 5
RATE_LIMIT_SAFETY_MARGIN = 1
RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS = 10
AUTO_REFRESH_LIMIT = 2
AUTO_REFRESH_WINDOW_SECONDS = 3600
