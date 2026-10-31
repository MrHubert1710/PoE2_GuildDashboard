"""Render the real dashboard with synthetic data; never touch live reports/API."""
import contextlib
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from poe2logger import dashboard, state


def render():
    for name in ('Alice', 'Bob', 'Carol'):
        state.stash_summary['Test stash'][name]['Divine Orb']['added'] = 10
        state.movement_log.append({
            'account': name, 'stash': 'Test stash', 'item_name': 'Divine Orb',
            'date': '2026-10-31T10:00:00Z', 'parsed_date': datetime.now(timezone.utc),
            'parsed_id': 1, 'quantity': 10, 'rate': 1, 'value': 10, 'action': 'added',
        })
    if '--new-player' in sys.argv:
        state.stash_summary['Test stash']['Aaron']['Divine Orb']['added'] = 1
    with tempfile.TemporaryDirectory() as directory:
        previous = os.getcwd()
        try:
            os.chdir(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                dashboard.print_html_dashboard()
            return Path(dashboard.LATEST_DASHBOARD_FILE).read_text(encoding='utf-8')
        finally:
            os.chdir(previous)


if __name__ == '__main__':
    sys.stdout.buffer.write(render().encode('utf-8'))
