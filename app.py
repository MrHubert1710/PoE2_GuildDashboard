import html
import threading
import traceback

from flask import Flask, Response

from poe2logger.cli import generate_report
from poe2logger.config import LATEST_DASHBOARD_FILE


app = Flask(__name__)
report_lock = threading.Lock()


def read_latest_dashboard():
    """Read the latest generated dashboard HTML."""
    with open(LATEST_DASHBOARD_FILE, 'r', encoding='utf-8') as f:
        return f.read()


@app.route('/')
@app.route(f'/{LATEST_DASHBOARD_FILE}')
def index():
    """Fetch fresh history, regenerate the report, and return the latest dashboard."""
    try:
        with report_lock:
            generate_report(fetch_history=True)
            html_content = read_latest_dashboard()
        return Response(html_content, mimetype='text/html', headers={'Cache-Control': 'no-store'})
    except Exception as e:
        traceback.print_exc()
        error_html = (
            '<!doctype html><html><head><meta charset="utf-8"><title>Guild Report Error</title></head>'
            '<body><h1>Guild Report Error</h1>'
            f'<pre>{html.escape(str(e))}</pre></body></html>'
        )
        return Response(error_html, status=500, mimetype='text/html')


@app.route('/health')
def health():
    """Cheap health check that does not fetch history."""
    return Response('ok\n', mimetype='text/plain')
