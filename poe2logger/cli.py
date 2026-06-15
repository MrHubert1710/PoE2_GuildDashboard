import argparse
from types import SimpleNamespace

from .charts import print_individual_value_charts, print_player_value_chart, print_stash_value_chart
from .dashboard import print_html_dashboard
from .fetcher import fetch_guild_history
from .processing import process_log
from . import state

def parse_args():
    """Parse command line options."""
    parser = argparse.ArgumentParser(description='Fetch guild stash history and generate the Poe2Logger dashboard.')
    parser.add_argument('--fetch-history', action='store_true', help='Fetch guild stash history before generating the dashboard.')
    parser.add_argument('--fetch-prices', action='store_true', help='Force fetching poe.ninja prices instead of using fresh cache.')
    parser.add_argument('--guild-id', default='', help='Path of Exile guild id. Defaults to POE_GUILD_ID, then config.py GUILD_ID.')
    parser.add_argument('--session-id', default='', help='POESESSID value. Defaults to POESESSID/POE_SESSION_ID, then config.py SESSION_ID.')
    parser.add_argument('--from', dest='from_timestamp', default='', help='Override newer Unix timestamp boundary for guild history.')
    parser.add_argument('--end', dest='end_timestamp', default='', help='Override older Unix timestamp boundary for guild history.')
    parser.add_argument('--fromid', dest='from_id', default='', help='Override initial guild history pagination cursor.')
    return parser.parse_args()


def generate_report(fetch_history=False, fetch_prices=False, guild_id='', session_id='', from_timestamp='', end_timestamp='', from_id=''):
    """Run optional fetch, then generate all report outputs."""
    state.force_price_fetch = fetch_prices
    
    if fetch_history:
        fetch_args = SimpleNamespace(
            guild_id=guild_id,
            session_id=session_id,
            from_timestamp=from_timestamp,
            end_timestamp=end_timestamp,
            from_id=from_id,
        )
        fetch_guild_history(fetch_args)
    
    process_log()
    print_player_value_chart()
    print_stash_value_chart()
    print_individual_value_charts()
    print_html_dashboard()


def run():
    """Run from the command line."""
    args = parse_args()
    generate_report(
        fetch_history=args.fetch_history,
        fetch_prices=args.fetch_prices,
        guild_id=args.guild_id,
        session_id=args.session_id,
        from_timestamp=args.from_timestamp,
        end_timestamp=args.end_timestamp,
        from_id=args.from_id,
    )

