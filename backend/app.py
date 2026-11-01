"""HTTP shell for the rework. Domain code will be added independently of Vue."""
from pathlib import Path

from flask import Flask, jsonify, send_from_directory


ROOT = Path(__file__).resolve().parents[1]


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(FRONTEND_DIST=ROOT / 'frontend' / 'dist')
    if config:
        app.config.update(config)

    @app.get('/health')
    def health():
        return 'ok\n', 200, {'Content-Type': 'text/plain; charset=utf-8'}

    @app.get('/api/health')
    def api_health():
        return jsonify(service='poe2guild', status='ok', message='Hello World')

    @app.get('/')
    def index():
        directory = Path(app.config['FRONTEND_DIST'])
        if not (directory / 'index.html').is_file():
            return jsonify(error='Frontend is not built. Run ./poe2guild build.'), 503
        response = send_from_directory(directory, 'index.html')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/assets/<path:filename>')
    def assets(filename):
        response = send_from_directory(Path(app.config['FRONTEND_DIST']) / 'assets', filename)
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error='Not found'), 404

    return app
