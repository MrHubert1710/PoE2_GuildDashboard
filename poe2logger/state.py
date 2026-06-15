from collections import defaultdict

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
force_price_fetch = False
player_value_timeline = defaultdict(list)
stash_value_timeline = defaultdict(list)
player_chart_files = {}
stash_chart_files = {}
