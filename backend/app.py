"""HTTP shell for the rework. Domain code will be added independently of Vue."""
from pathlib import Path
import json
import sqlite3
from datetime import datetime

from flask import Flask, jsonify, send_from_directory
from .reference import public_reference
from .repositories import database_status
from .database import DatabaseError


ROOT = Path(__file__).resolve().parents[1]


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(FRONTEND_DIST=ROOT / 'frontend' / 'dist',
                            REFERENCE_FILE=ROOT / 'data/reference/phase0.json',
                            DATABASE_FILE=ROOT / 'data/poe2guild.sqlite')
    if config:
        app.config.update(config)

    @app.get('/health')
    def health():
        return 'ok\n', 200, {'Content-Type': 'text/plain; charset=utf-8'}

    @app.get('/api/health')
    def api_health():
        return jsonify(service='poe2guild', status='ok', message='Hello World')

    @app.get('/api/rework-readiness')
    def rework_readiness():
        try:
            snapshot = json.loads(Path(app.config['REFERENCE_FILE']).read_text(encoding='utf-8'))
            response = jsonify(public_reference(snapshot))
        except (OSError, ValueError, KeyError, TypeError):
            response = jsonify(error='Reference snapshot unavailable. Run scripts/build-reference.py.')
            response.status_code = 503
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/database-status')
    def database_readiness():
        try:
            result = database_status(app.config['DATABASE_FILE'])
        except (OSError, sqlite3.Error, DatabaseError):
            response = jsonify(state='unavailable', error='Database unavailable or requires migration.')
            response.status_code = 503
        else:
            baseline = {}
            try:
                reference = json.loads(Path(app.config['REFERENCE_FILE']).read_text(encoding='utf-8'))
                baseline = {league['name']: league for league in reference['leagues']}
            except (OSError, ValueError, KeyError, TypeError):
                pass
            for league in result['leagues']:
                expected = baseline.get(league['name'])
                league['baseline_match'] = None
                if expected:
                    try:
                        league['baseline_match'] = (
                            league['transactions'] == expected['transactions']
                            and league['history_sha256'] == expected['history_sha256']
                            and all(datetime.fromisoformat(league[key].replace('Z', '+00:00')) ==
                                    datetime.fromisoformat(expected[key].replace('Z', '+00:00'))
                                    for key in ('oldest_at', 'newest_at')))
                    except (ValueError, TypeError, KeyError, AttributeError):
                        league['baseline_match'] = False
            response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response

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
