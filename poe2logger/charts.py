import html
import math
import os
from datetime import datetime, timedelta

from .config import CHART_DIR, OUTPUT_DIR
from .private_config import DISPLAY_TIMEZONE, LEAGUE_NAME
from .state import log_events, player_chart_files, player_value_timeline, stash_chart_files, stash_value_timeline
from .utils import chart_output_path, display_event_datetime, safe_chart_filename

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


def ceil_to_hour_multiple(date_value, hour_step):
    """Round a datetime up to the next local hour multiple."""
    rounded = date_value.replace(minute=0, second=0, microsecond=0)
    if rounded < date_value:
        rounded += timedelta(hours=1)
    
    remainder = rounded.hour % hour_step
    if remainder:
        rounded += timedelta(hours=hour_step - remainder)
    
    return rounded


def append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height, hour_step=6):
    """Append day ticks and hour sub-ticks for the chart time axis."""
    min_local = datetime.fromtimestamp(min_ts, DISPLAY_TIMEZONE)
    max_local = datetime.fromtimestamp(max_ts, DISPLAY_TIMEZONE)
    day_tick = min_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if day_tick.timestamp() < min_ts:
        day_tick += timedelta(days=1)
    
    minor_tick = ceil_to_hour_multiple(min_local, hour_step)
    while minor_tick.timestamp() <= max_ts:
        if minor_tick.timestamp() >= min_ts and minor_tick.hour != 0:
            x = scale_x(minor_tick)
            svg.append(
                f'<line class="subgrid" x1="{x:.2f}" y1="{margin_top}" '
                f'x2="{x:.2f}" y2="{margin_top + plot_height}"/>'
            )
            svg.append(
                f'<text class="subtick" x="{x:.2f}" y="{margin_top + plot_height + 22}" '
                f'text-anchor="middle">{html.escape(minor_tick.strftime("%H"))}</text>'
            )
        minor_tick += timedelta(hours=hour_step)
    
    while day_tick.timestamp() <= max_ts:
        if day_tick.timestamp() >= min_ts:
            x = scale_x(day_tick)
            svg.append(
                f'<line class="grid day-grid" x1="{x:.2f}" y1="{margin_top}" '
                f'x2="{x:.2f}" y2="{margin_top + plot_height}"/>'
            )
            svg.append(
                f'<text class="tick" x="{x:.2f}" y="{margin_top + plot_height + 42}" '
                f'text-anchor="middle">{html.escape(day_tick.strftime("%d-%m"))}</text>'
            )
        day_tick += timedelta(days=1)


def print_player_value_chart():
    """Generate one SVG chart with cumulative net value over time for each player."""
    if not player_value_timeline:
        print("No player value timeline data to chart")
        return
    
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)
    
    chart_file = chart_output_path('VALUE_OVER_TIME_BY_PLAYER.svg')
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    width = 1600
    height = 720
    margin_left = 90
    margin_top = 70
    margin_bottom = 82
    margin_right = 40
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    
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
        '.day-grid { stroke: #cbd5e1; stroke-width: 1.2; }',
        '.subgrid { stroke: #f1f5f9; stroke-width: 1; }',
        '.tick { font-size: 12px; fill: #4b5563; }',
        '.subtick { font-size: 10px; fill: #9ca3af; }',
        '.title { font-size: 24px; font-weight: 700; }',
        '.subtitle { font-size: 13px; fill: #6b7280; }',
        '.legend { font-size: 13px; }',
        '.legend-box { fill: rgba(255,255,255,0.86); stroke: #d1d5db; stroke-width: 1; }',
        '</style>',
        f'<text class="title" x="{margin_left}" y="34">Total value over time by player</text>',
        f'<text class="subtitle" x="{margin_left}" y="56">Cumulative net value in Divine Orb, estimated from cached poe.ninja data</text>',
    ]
    
    # Y-axis grid and labels
    for value in tick_values:
        y = scale_y(value)
        svg.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_width}" y2="{y:.2f}"/>')
        svg.append(
            f'<text class="tick" x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end">{html.escape(format_axis_value(value, tick_step))}</text>'
        )
    
    append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height)
    
    svg.extend([
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}"/>',
        f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}"/>',
        f'<text class="tick" x="{margin_left - 60}" y="{margin_top + plot_height / 2}" transform="rotate(-90 {margin_left - 60} {margin_top + plot_height / 2})" text-anchor="middle">Net value (Divine Orb)</text>',
        f'<text class="tick" x="{margin_left + plot_width / 2}" y="{margin_top + plot_height + 62}" text-anchor="middle">Time</text>',
    ])
    
    players_with_points = [
        player
        for player in sorted(player_value_timeline.keys())
        if player_value_timeline[player]
    ]
    legend_x = margin_left + 14
    legend_y = margin_top + 14
    legend_width = 290
    legend_height = 28 + (len(players_with_points) * 24)
    legend_svg = [
        f'<rect class="legend-box" x="{legend_x}" y="{legend_y}" width="{legend_width}" '
        f'height="{legend_height}" rx="6"/>',
        f'<text class="legend" x="{legend_x + 12}" y="{legend_y + 20}" font-weight="700">Player</text>',
    ]
    
    for index, player in enumerate(players_with_points):
        points = player_value_timeline[player]
        color = colors[index % len(colors)]
        point_string = ' '.join(
            f'{scale_x(date_value):.2f},{scale_y(value):.2f}'
            for date_value, value in points
        )
        final_value = points[-1][1]
        legend_item_y = legend_y + 46 + (index * 24)
        
        svg.append(
            f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="2.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        legend_svg.append(f'<line x1="{legend_x + 12}" y1="{legend_item_y - 5}" x2="{legend_x + 40}" y2="{legend_item_y - 5}" stroke="{color}" stroke-width="3"/>')
        legend_svg.append(
            f'<text class="legend" x="{legend_x + 50}" y="{legend_item_y}">'
            f'{html.escape(player)} ({final_value:.2f} div)</text>'
        )
    
    svg.extend(legend_svg)
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


def print_stash_value_chart():
    """Generate one SVG chart with cumulative net value over time for each stash."""
    if not stash_value_timeline:
        print("No stash value timeline data to chart")
        return
    
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)
    
    chart_file = chart_output_path('VALUE_OVER_TIME_BY_STASH.svg')
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    width = 1600
    height = 720
    margin_left = 90
    margin_top = 70
    margin_bottom = 82
    margin_right = 40
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    
    all_points = [
        point
        for points in stash_value_timeline.values()
        for point in points
        if point[0] != datetime.min
    ]
    
    if not all_points:
        print("No dated stash value timeline data to chart")
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
        '.day-grid { stroke: #cbd5e1; stroke-width: 1.2; }',
        '.subgrid { stroke: #f1f5f9; stroke-width: 1; }',
        '.tick { font-size: 12px; fill: #4b5563; }',
        '.subtick { font-size: 10px; fill: #9ca3af; }',
        '.title { font-size: 24px; font-weight: 700; }',
        '.subtitle { font-size: 13px; fill: #6b7280; }',
        '.legend { font-size: 13px; }',
        '.legend-box { fill: rgba(255,255,255,0.86); stroke: #d1d5db; stroke-width: 1; }',
        '</style>',
        f'<text class="title" x="{margin_left}" y="34">Total value over time by stash</text>',
        f'<text class="subtitle" x="{margin_left}" y="56">Cumulative net value in Divine Orb, estimated from cached poe.ninja data</text>',
    ]
    
    for value in tick_values:
        y = scale_y(value)
        svg.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_width}" y2="{y:.2f}"/>')
        svg.append(
            f'<text class="tick" x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end">{html.escape(format_axis_value(value, tick_step))}</text>'
        )
    
    append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height)
    
    svg.extend([
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}"/>',
        f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}"/>',
        f'<text class="tick" x="{margin_left - 60}" y="{margin_top + plot_height / 2}" transform="rotate(-90 {margin_left - 60} {margin_top + plot_height / 2})" text-anchor="middle">Net value (Divine Orb)</text>',
        f'<text class="tick" x="{margin_left + plot_width / 2}" y="{margin_top + plot_height + 62}" text-anchor="middle">Time</text>',
    ])
    
    stashes_with_points = [
        stash
        for stash in sorted(stash_value_timeline.keys())
        if stash_value_timeline[stash]
    ]
    legend_x = margin_left + 14
    legend_y = margin_top + 14
    legend_width = 260
    legend_height = 28 + (len(stashes_with_points) * 24)
    legend_svg = [
        f'<rect class="legend-box" x="{legend_x}" y="{legend_y}" width="{legend_width}" '
        f'height="{legend_height}" rx="6"/>',
        f'<text class="legend" x="{legend_x + 12}" y="{legend_y + 20}" font-weight="700">Stash</text>',
    ]
    
    for index, stash in enumerate(stashes_with_points):
        points = stash_value_timeline[stash]
        color = colors[index % len(colors)]
        point_string = ' '.join(
            f'{scale_x(date_value):.2f},{scale_y(value):.2f}'
            for date_value, value in points
        )
        final_value = points[-1][1]
        legend_item_y = legend_y + 46 + (index * 24)
        
        svg.append(
            f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="2.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        legend_svg.append(f'<line x1="{legend_x + 12}" y1="{legend_item_y - 5}" x2="{legend_x + 40}" y2="{legend_item_y - 5}" stroke="{color}" stroke-width="3"/>')
        legend_svg.append(
            f'<text class="legend" x="{legend_x + 50}" y="{legend_item_y}">'
            f'{html.escape(stash)} ({final_value:.2f} div)</text>'
        )
    
    svg.extend(legend_svg)
    svg.append('</svg>')
    
    with open(chart_file, 'w', encoding='utf-8') as chart_f:
        chart_f.write('\n'.join(svg))
    
    print()
    print("=" * 80)
    print("STASH VALUE CHART CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Stash value chart: {chart_file}")
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
    
    width = 1280
    height = 520
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
        '.day-grid { stroke: #cbd5e1; stroke-width: 1.2; }',
        '.subgrid { stroke: #f1f5f9; stroke-width: 1; }',
        '.tick { font-size: 12px; fill: #4b5563; }',
        '.subtick { font-size: 10px; fill: #9ca3af; }',
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
    
    append_time_axis(svg, min_ts, max_ts, scale_x, margin_top, plot_height)
    
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
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)
    
    colors = [
        '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c',
        '#0891b2', '#be123c', '#4f46e5', '#65a30d', '#c026d3',
    ]
    player_chart_files.clear()
    stash_chart_files.clear()
    
    for index, player in enumerate(sorted(player_value_timeline.keys())):
        filename = safe_chart_filename('CHART_PLAYER', player)
        chart_file = chart_output_path(filename)
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
        chart_file = chart_output_path(filename)
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

