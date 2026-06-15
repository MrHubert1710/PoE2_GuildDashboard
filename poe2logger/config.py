import os


LOG_DIR = 'logs'
HISTORY_FILENAME = 'history.csv'
LATEST_DASHBOARD_FILE = 'GuildReport_Latest.html'
CSV_FIELDNAMES = ['Date', 'Id', 'League', 'Account', 'Action', 'Stash', 'Item', 'X', 'Y']
OUTPUT_DIR = 'stash_reports'
CHART_DIR = os.path.join(OUTPUT_DIR, 'charts')
PRICE_CACHE_DIR = os.path.join(OUTPUT_DIR, 'price_cache')
PRICE_CACHE_MAX_AGE_HOURS = 12
POE_NINJA_PRICE_URL = 'https://poe.ninja/poe2/api/economy/exchange/current/overview'
POE_GUILD_HISTORY_URL = 'https://www.pathofexile.com/api/guild/{guild_id}/stash/history'
POE_API_USER_AGENT = 'OAuth Poe2Logger/1.0.0 (contact: local)'
PRICE_TYPES = ['Currency', 'Essences', 'Runes', 'Ritual', 'Delirium', 'Abyss', 'Expedition', 'Verisium']
HISTORY_FETCH_OVERLAP_DAYS = 1
HISTORY_FETCH_DELAY_SECONDS = 1.0
HISTORY_FETCH_MAX_RETRIES = 5
RATE_LIMIT_SAFETY_MARGIN = 1
RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS = 10
WEB_HOST = '0.0.0.0'
WEB_PORT = 8000
