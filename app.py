import json
import os

from flask import Flask, Response, jsonify, request, url_for

from poe2logger.cli import _generate_report
from poe2logger.config import LATEST_DASHBOARD_FILE
from poe2logger.refresh import manager


app = Flask(__name__)


def report_revision(stat):
    return f'{stat.st_mtime_ns}:{stat.st_size}'


def refresh_status():
    status = manager.status()
    try:
        status['revision'] = report_revision(os.stat(LATEST_DASHBOARD_FILE))
    except FileNotFoundError:
        status['revision'] = None
    return status


def start_refresh(automatic):
    return manager.run(lambda: _generate_report(fetch_history=True),
                       automatic=automatic, background=True)


@app.route('/')
@app.route(f'/{LATEST_DASHBOARD_FILE}')
def index():
    """Serve the last good snapshot immediately; refresh outside the request."""
    if request.args.get('__snapshot') != '1':
        start_refresh(automatic=True)
    try:
        with open(LATEST_DASHBOARD_FILE, encoding='utf-8') as stream:
            html_content = stream.read()
            revision = report_revision(os.fstat(stream.fileno()))
    except FileNotFoundError:
        revision = None
        html_content = ('<!doctype html><html><head><meta charset="utf-8">'
                        '<title>Guild Report</title></head><body>'
                        '<h1>Guild Report</h1><p>No saved report yet. '
                        'Waiting for the first successful refresh.</p></body></html>')
    status = refresh_status()
    # Relative paths work at / and below a prefix stripped by nginx proxy_pass.
    status.update(revision=revision, status_url=url_for('status').lstrip('/'),
                  refresh_url=url_for('refresh').lstrip('/'))
    bootstrap = json.dumps(status).replace('<', '\\u003c')
    controls = '''
    <style>
      #refresh-toolbar { background:#111827;
        color:#f1f5f9; padding:8px 18px; display:flex; justify-content:flex-end; }
      #refresh-pill { border:1px solid #64748b; border-radius:999px; padding:8px 16px;
        background:#1e293b; color:#f1f5f9; cursor:pointer; font:inherit; }
      #refresh-pill:disabled { cursor:wait; opacity:.7; }
      #refresh-error { background:#991b1b; color:white; padding:12px 18px; }
      #refresh-error[hidden] { display:none; }
    </style>
    <div id="refresh-error" role="alert" hidden>Refresh failed. Showing the last available data.</div>
    <div id="refresh-toolbar"><button id="refresh-pill" type="button"
      title="Click to refresh data">Last refresh: unknown</button></div>
    '''
    html_content = html_content.replace('<body>', '<body>' + controls, 1)
    html_content = html_content.replace('</body>',
        f'<script id="refresh-bootstrap" type="application/json">{bootstrap}</script>'
        f'<script src="{url_for("static", filename="refresh.js").lstrip("/")}"></script></body>', 1)
    return Response(html_content, mimetype='text/html', headers={'Cache-Control': 'no-store'})


@app.get('/api/refresh-status')
def status():
    response = jsonify(refresh_status())
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/api/refresh')
def refresh():
    if request.headers.get('X-Requested-With') != 'Poe2Logger':
        return jsonify(error='Invalid request'), 400
    outcome = start_refresh(automatic=False)
    response = jsonify(outcome=outcome, **refresh_status())
    response.status_code = 202
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/health')
def health():
    """Cheap health check that does not fetch history."""
    return Response('ok\n', mimetype='text/plain')
