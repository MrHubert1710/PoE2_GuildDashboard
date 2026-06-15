import html
import os
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .cli import generate_report
from .config import LATEST_DASHBOARD_FILE, WEB_HOST, WEB_PORT


report_lock = threading.Lock()


def read_latest_dashboard():
    """Read the latest generated dashboard HTML."""
    with open(LATEST_DASHBOARD_FILE, 'rb') as f:
        return f.read()


class GuildReportHandler(BaseHTTPRequestHandler):
    """Serve the guild report, refreshing history for report requests."""

    server_version = 'Poe2LoggerHTTP/1.0'

    def log_message(self, format, *args):
        """Keep default access logging but route it through print-friendly formatting."""
        print(f'{self.address_string()} - {format % args}')

    def send_text(self, status, text, content_type='text/plain; charset=utf-8'):
        """Send a plain text/html response."""
        payload = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_dashboard(self):
        """Fetch fresh history, regenerate the dashboard, and serve it."""
        with report_lock:
            generate_report(fetch_history=True)
            payload = read_latest_dashboard()

        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path

        if path == '/health':
            self.send_text(HTTPStatus.OK, 'ok\n')
            return

        if path in ('/', f'/{LATEST_DASHBOARD_FILE}'):
            try:
                self.send_dashboard()
            except Exception as e:
                traceback.print_exc()
                message = (
                    '<!doctype html><html><head><title>Guild Report Error</title></head>'
                    '<body><h1>Guild Report Error</h1>'
                    f'<pre>{html.escape(str(e))}</pre></body></html>'
                )
                self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, message, 'text/html; charset=utf-8')
            return

        if path == '/favicon.ico':
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        self.send_text(HTTPStatus.NOT_FOUND, 'not found\n')


def run_server(host=WEB_HOST, port=WEB_PORT):
    """Run the guild report HTTP server."""
    server = ThreadingHTTPServer((host, port), GuildReportHandler)
    print(f'Serving guild report on http://{host}:{port}/')
    try:
        server.serve_forever()
    finally:
        server.server_close()
