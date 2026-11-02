"""Nonblocking refresh requests. Public responses contain codes, never credentials."""
import sqlite3
from flask import Blueprint, current_app, jsonify, request
from .database import DatabaseError
from .jobs import Queue, JobRejected
from .auth import is_admin

refresh = Blueprint('refresh', __name__)


def queue():
    return Queue(current_app.config['DATABASE_FILE'],
                 history_scope=current_app.config['HISTORY_SCOPE'],
                 history_available=current_app.config['HISTORY_AVAILABLE'],
                 prices_available=current_app.config['PRICE_FETCH_AVAILABLE'])


@refresh.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@refresh.errorhandler(JobRejected)
def rejected(error):
    return jsonify(error=error.code), 404 if error.code == 'league_not_found' else 400


@refresh.errorhandler(DatabaseError)
@refresh.errorhandler(sqlite3.Error)
def unavailable(_error):
    return jsonify(error='database_unavailable'), 503


@refresh.get('/api/leagues/<league_id>/refresh')
def status(league_id):
    result = queue().status(league_id)
    if not is_admin():
        # Public polling needs revision and availability, never verification details.
        result['worker'] = 'unavailable'
        result['local_verify'] = dict(available=False, reason='admin_required', last_success_at=None,
                                      cooldown_until=None, automatic_retry_at=None, job=None, last_result=None)
        result['history']['last_result'] = None
    return jsonify(result)


@refresh.post('/api/leagues/<league_id>/refresh')
def enqueue(league_id):
    # JSON + same-origin checks prevent cross-site form submissions creating work.
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
        return jsonify(error='origin_rejected'), 403
    if not request.is_json:
        return jsonify(error='json_required'), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {'kind', 'trigger'}:
        return jsonify(error='invalid_refresh_request'), 400
    kind, trigger = payload.get('kind', 'history'), payload.get('trigger', 'automatic')
    if not isinstance(kind, str) or not isinstance(trigger, str):
        return jsonify(error='invalid_refresh_request'), 400
    result = queue().enqueue(league_id, kind, trigger)
    return jsonify(result), 202 if result['outcome'] in {'queued', 'coalesced'} else 200
