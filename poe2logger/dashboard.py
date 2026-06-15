import html
import os
from collections import defaultdict
from datetime import datetime

from .config import LATEST_DASHBOARD_FILE, OUTPUT_DIR, PRICE_TYPES
from .private_config import LEAGUE_NAME, TARGET_STASHES
from .prices import build_price_index, normalize_price_key, price_cache_path
from .state import final_stash_state, log_events, movement_log, player_chart_files, player_summary, price_metadata, stash_chart_files, stash_summary, unpriced_summary, valuation_summary
from .utils import chart_asset_src, chart_output_path, dashboard_filename, dashboard_title, display_event_datetime, parse_event_date, target_stash_label

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
    dashboard_files = [dashboard_file, LATEST_DASHBOARD_FILE]
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
    
    for output_file in dashboard_files:
        with open(output_file, 'w', encoding='utf-8') as dashboard_f:
            dashboard_f.write(page)
    
    print()
    print("=" * 80)
    print("HTML DASHBOARD CREATED SUCCESSFULLY")
    print("=" * 80)
    for output_file in dashboard_files:
        print(f"Dashboard: {output_file}")
    print("=" * 80)
    print()

