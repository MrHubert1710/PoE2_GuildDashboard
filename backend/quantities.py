"""Versioned quantity projections; source records remain untouched."""
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import re

from .archive_import import canonical
from .timezones import normalize_timezone
from .browsing import revision
from .database import connect, require_schema, utc_now

ALGORITHM = 'quantities-v4'
MAX_QUANTITY = 10**9  # Bounded integer arithmetic, safely representable by browser clients.
DEFAULTS = {'target_stashes': None, 'stash_aliases': {}, 'timezone': 'UTC', 'hour_format': 'auto'}


def guild_source(connection, league_id):
    sources = [row[0] for row in connection.execute(
        'SELECT source_id FROM transactions WHERE league_id=? UNION SELECT source_id FROM archive_files WHERE league_id=? '
        'UNION SELECT i.source_id FROM revisions r JOIN import_runs i ON i.id=r.import_id WHERE r.league_id=?',
        (league_id, league_id, league_id))]
    return sources[0] if len(sources) == 1 else None


def guild_defaults(connection, league_id):
    source = guild_source(connection, league_id)
    row = connection.execute('SELECT settings_json FROM guild_quantity_defaults WHERE source_id=?', (source,)).fetchone() if source else None
    return source, dict(DEFAULTS, **json.loads(row[0])) if row else DEFAULTS.copy()


def effective_settings(league, connection=None):
    original = json.loads(league['settings_json'])
    if 'quantity_settings' in original:
        return dict(DEFAULTS, **original['quantity_settings'])
    return guild_defaults(connection, league['id'])[1] if connection is not None else DEFAULTS.copy()


def visible_stashes(connection, league_id, settings):
    """Raw names visible under the league's current canonical stash selection."""
    names = [row[0] for row in connection.execute(
        'SELECT DISTINCT stash FROM transactions WHERE league_id=? ORDER BY stash', (league_id,))]
    targets = settings['target_stashes']
    aliases = settings['stash_aliases']
    return names if targets is None else [name for name in names if aliases.get(name, name) in targets]


def settings_hash(settings):
    return hashlib.sha256(canonical(settings).encode()).hexdigest()


def validate_settings(value):
    if not isinstance(value, dict) or not (set(DEFAULTS) - {'hour_format'}) <= set(value) or set(value) - set(DEFAULTS):
        raise ValueError('invalid_settings')
    def name(text):
        return isinstance(text, str) and 0 < len(text) <= 200 and text == text.strip()
    targets, aliases, zone = value['target_stashes'], value['stash_aliases'], value['timezone']
    if targets is not None and (not isinstance(targets, list) or len(targets) > 100 or not all(name(n) for n in targets)):
        raise ValueError('invalid_settings')
    if not isinstance(aliases, dict) or len(aliases) > 100 or not all(name(k) and name(v) for k, v in aliases.items()):
        raise ValueError('invalid_settings')
    if any(target in aliases and aliases[target] != target for target in aliases.values()):
        raise ValueError('alias_chain')
    zone = normalize_timezone(zone)
    hour_format = value.get('hour_format', 'auto')
    if hour_format not in ('auto', '12', '24'):
        raise ValueError('invalid_hour_format')
    return {'target_stashes': sorted(set(targets)) if targets is not None else None,
            'stash_aliases': dict(sorted(aliases.items())), 'timezone': zone, 'hour_format': hour_format}


def parse_quantity(text):
    text = text.strip()
    # Preserve legacy separators, including the observed mojibake form, but never
    # strip an arbitrary leading number from an actual item name.
    match = re.fullmatch(r'(\d+)\s*(?:x|×|Ă—)\s*(.+)', text, re.IGNORECASE)
    if not match and re.match(r'[+-]?\d+(?:[.,]\d+)?\s*(?:x|×|Ă—)', text, re.IGNORECASE):
        raise ValueError('invalid_quantity')
    quantity, item = (int(match[1]), match[2].strip()) if match else (1, text)
    if not item or quantity < 0 or quantity > MAX_QUANTITY or re.fullmatch(r'\d+\s*[x×]', text, re.IGNORECASE):
        raise ValueError('invalid_quantity')
    return quantity, item


def event_order(event):
    value = event['external_id']
    # Numeric identifiers are the legacy chronological tie-breaker, not lexical order.
    return (event['occurred_at'], 0 if value.isascii() and value.isdigit() else 1,
            int(value) if value.isascii() and value.isdigit() else value, event['id'])


def replay(events, settings, stop=None):
    """Pure full-history replay, isolated by source + canonical stash + coordinate.

    Added is a signed movement; Removed empties the slot. Modified describes the resulting stack.
    Every unseen coordinate starts at zero, independently for each league.
    """
    ordered = sorted(events, key=event_order)
    aliases, targets = settings['stash_aliases'], settings['target_stashes']
    groups = defaultdict(list)
    for event in ordered:
        stash = aliases.get(event['stash'], event['stash'])
        groups[(event['source_id'], stash, event['x'], event['y'], event['occurred_at'])].append(event)
    ambiguous = set()
    for group in groups.values():
        ids = [e['external_id'] for e in group]
        if len(group) > 1 and (not all(i.isascii() and i.isdigit() for i in ids) or len(set(map(int, ids))) != len(ids)):
            ambiguous.update(e['id'] for e in group)
    states, annotations, movements, corrections = {}, [], [], []

    def record_changes(event, key, previous, changes):
        # Reconcile every transition, including unknown-state anchors, not only Removed.
        # Unknown quantities contribute zero to the *known* reconstructed inventory.
        expected = defaultdict(int)
        for sign, state in [(-1, previous), (1, states.get(key))]:
            if state and state['item_name'] and state['quantity'] is not None:
                expected[state['item_name']] += sign * state['quantity']
        for sequence, (name, delta, confidence) in enumerate(changes):
            movements.append({'transaction_id': event['id'], 'sequence': sequence, 'item_name': name,
                              'quantity_delta': delta, 'confidence': confidence})
            expected[name] -= delta
        entries = [(name, delta) for name, delta in sorted(expected.items()) if delta]
        for sequence, (name, delta) in enumerate(entries):
            corrections.append({'transaction_id': event['id'], 'sequence': sequence, 'item_name': name,
                                'quantity_delta': delta, 'confidence': 'inferred'})
        return bool(entries)
    for event in ordered:
        if stop and stop.is_set():
            raise InterruptedError()
        stash = aliases.get(event['stash'], event['stash'])
        key = (event['source_id'], stash, event['x'], event['y'])
        current = states.get(key)
        before_item = (current['item_name'] or None) if current else None
        before = current['quantity'] if current else 0
        row = {'transaction_id': event['id'], 'item_name': event['item'], 'stash': stash,
               'before_item': before_item, 'quantity_before': before, 'quantity_after': None,
               'quantity_delta': None, 'effective_action': 'unknown', 'confidence': 'unknown', 'resolution_reason': 'unknown_before'}
        changes = []
        if targets is not None and stash not in targets:
            row.update(effective_action='excluded', confidence='excluded', resolution_reason='stash_excluded')
            annotations.append(row)
            continue
        try:
            quantity, item = parse_quantity(event['item'])
            row['item_name'] = item
        except ValueError:
            row['resolution_reason'] = 'invalid_quantity'
            if event['action'] == 'removed' and event['id'] not in ambiguous:
                row.update(quantity_after=0, effective_action='removed', confidence='inferred')
                if before_item and before is not None and before > 0:
                    changes = [(before_item, -before, 'inferred')]
                elif before == 0:
                    row.update(quantity_delta=0, effective_action='unchanged')
                states[key] = {'item_name': '', 'quantity': 0, 'transaction_id': event['id']}
            else:
                states[key] = {'item_name': event['item'], 'quantity': None, 'transaction_id': event['id']}
            if record_changes(event, key, current, changes):
                row['confidence'] = 'inferred'
            annotations.append(row)
            continue
        after = None
        action = event['action']
        if event['id'] in ambiguous:
            row['resolution_reason'] = 'ambiguous_order'
        elif action == 'modified':
            after = quantity
            if before is not None and (before_item == item or before == 0):
                delta = quantity - before
                row.update(quantity_delta=delta, effective_action='added' if delta > 0 else 'removed' if delta < 0 else 'unchanged',
                           confidence='derived', resolution_reason='stack_difference')
                if delta:
                    changes.append((item, delta, 'derived'))
            elif before_item and before_item != item and before is not None and before > 0:
                row.update(effective_action='mixed', confidence='inferred', resolution_reason='replacement')
                changes = [(before_item, -before, 'inferred')]
                if quantity:
                    changes.append((item, quantity, 'inferred'))
            # Unknown before: anchor the observed resulting stack, but do not infer a delta.
        elif action == 'added':
            if quantity == 0:
                row.update(quantity_delta=0, effective_action='unchanged', confidence='source', resolution_reason='explicit_zero')
                after = before
            else:
                row.update(quantity_delta=quantity, effective_action='added', confidence='source', resolution_reason='explicit_added')
                changes = [(item, quantity, 'source')]
                if before_item == item and before is not None:
                    after = before + quantity
                elif before == 0:
                    after = quantity
                elif before_item and before_item != item and before is not None:
                    # Preserve the legacy replacement interpretation, explicitly inferred.
                    row.update(quantity_delta=None, effective_action='mixed', confidence='inferred', resolution_reason='replacement')
                    changes = [(before_item, -before, 'inferred'), (item, quantity, 'inferred')]
                    after = quantity
        elif action == 'removed':
            after = 0
            if before == 0:
                # Temporary policy: an empty slot cannot produce another withdrawal.
                row.update(quantity_delta=0, effective_action='unchanged', confidence='inferred',
                           resolution_reason='removed_empty_ignored' if quantity else 'explicit_zero')
            elif before_item == item and before is not None:
                # One item type: clear its entire tracked stack once, not twice.
                exact = before == quantity
                row.update(quantity_delta=-before, effective_action='removed',
                           confidence='source' if exact else 'inferred',
                           resolution_reason='explicit_removed' if exact else 'removed_state_conflict')
                changes = [(item, -before, 'source' if exact else 'inferred')]
            elif before_item and before is not None:
                # Both positions belong to this transaction, hence to its actor.
                row.update(quantity_delta=None, effective_action='mixed', confidence='inferred',
                           resolution_reason='removed_state_conflict')
                changes = [(before_item, -before, 'inferred')]
                if quantity:
                    changes.append((item, -quantity, 'source'))
            else:
                # Unknown is not empty: retain the parseable source withdrawal.
                row.update(quantity_delta=-quantity, effective_action='removed' if quantity else 'unchanged',
                           confidence='inferred', resolution_reason='removed_unknown_before')
                if quantity:
                    changes = [(item, -quantity, 'source')]
        else:
            row['resolution_reason'] = 'unknown_action'
        if after is not None and after > MAX_QUANTITY:
            after = None
            row['resolution_reason'] = 'state_conflict'
        row['quantity_after'] = after
        state_item = item
        if action == 'removed' and after == 0:
            state_item = ''
        elif action == 'added' and quantity == 0 and before_item:
            state_item = before_item
        states[key] = {'item_name': state_item, 'quantity': after, 'transaction_id': event['id']}
        if record_changes(event, key, current, changes):
            row['confidence'] = 'inferred'
        annotations.append(row)
    return {'events': annotations, 'movements': movements,
            'corrections': corrections,
            'states': [dict(source_id=key[0], stash=key[1], x=key[2], y=key[3], **value) for key, value in states.items()]}


def projection_hash(league, connection):
    configured = effective_settings(league, connection)
    return settings_hash({'settings': {key: configured[key] for key in ('target_stashes', 'stash_aliases', 'timezone')}, 'initial_empty': True})


def current_run(connection, league, input_revision=None):
    expected = input_revision or revision(connection, league['id'])
    return connection.execute('SELECT * FROM quantity_runs WHERE league_id=? AND input_revision=? AND settings_hash=? AND algorithm_version=?',
                              (league['id'], expected, projection_hash(league, connection), ALGORITHM)).fetchone()


class QuantityAdapter:
    def stage(self, queue, job, stop):
        from .worker import AdapterFailure
        with connect(queue.path, readonly=True) as c:
            require_schema(c)
            c.execute('BEGIN')
            league = queue.league(c, job['league_id'])
            expected, settings = revision(c, league['id']), effective_settings(league, c)
            digest = projection_hash(league, c)
            events = [dict(row) for row in c.execute('SELECT id,source_id,external_id,occurred_at,account,action,stash,item,x,y '
                                                   'FROM transactions WHERE league_id=?', (league['id'],))]
        try:
            data = replay(events, settings, stop)
        except InterruptedError:
            raise AdapterFailure('interrupted') from None
        identity = hashlib.sha256(canonical([league['id'], expected, digest, ALGORITHM]).encode()).hexdigest()
        def publish(c):
            latest = queue.league(c, league['id'])
            if revision(c, league['id']) != expected or projection_hash(latest, c) != digest:
                raise AdapterFailure('data_changed')
            if not c.execute('SELECT id FROM quantity_runs WHERE id=?', (identity,)).fetchone():
                unknown = sum(e['effective_action'] == 'unknown' for e in data['events'])
                inferred = sum(e['confidence'] == 'inferred' for e in data['events'])
                excluded = sum(e['effective_action'] == 'excluded' for e in data['events'])
                c.execute('INSERT INTO quantity_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                          (identity, league['id'], expected, digest, canonical(dict(settings, initial_empty=True)), ALGORITHM, utc_now(), len(events), unknown, inferred, excluded))
                for table, rows in [('event_quantities', data['events']), ('quantity_movements', data['movements']), ('quantity_state', data['states']), ('quantity_reconciliations', data['corrections'])]:
                    if rows:
                        if table in {'event_quantities', 'quantity_state'}:
                            rows = [dict(league_id=league['id'], **row) for row in rows]
                        keys = list(rows[0])
                        c.executemany(f"INSERT INTO {table}(run_id,{','.join(keys)}) VALUES ({','.join('?' for _ in range(len(keys)+1))})",
                                      [(identity, *(row[key] for key in keys)) for row in rows])
            return {'revision': expected, 'projection_id': identity, 'algorithm_version': ALGORITHM, 'events': len(events)}
        return publish
