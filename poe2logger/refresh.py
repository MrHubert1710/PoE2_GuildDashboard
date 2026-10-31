"""Shared refresh coordination for web workers and command line reports.

All processes must use the same local report directory. OS locks are released
even if a worker dies; state and HTML are published with atomic replacements.
"""
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from datetime import datetime, timezone

from .config import OUTPUT_DIR, AUTO_REFRESH_LIMIT, AUTO_REFRESH_WINDOW_SECONDS


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
        # Windows readers briefly hold handles that deny replacement.
        for attempt in range(21):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 20:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class RefreshManager:
    def __init__(self, directory=OUTPUT_DIR):
        self.directory = Path(directory)
        self.state_path = self.directory / 'refresh_state.json'

    def _lock(self, blocking=False):
        self.directory.mkdir(parents=True, exist_ok=True)
        stream = open(self.directory / 'refresh.lock', 'a+b')
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b'\0')
                stream.flush()
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    return stream
                except OSError:
                    if not blocking:
                        stream.close()
                        return None
                    time.sleep(0.1)
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                return stream
            except BlockingIOError:
                stream.close()
                return None

    def _unlock(self, stream):
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            stream.close()

    def _read(self):
        try:
            return json.loads(self.state_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}

    def _save(self, state):
        atomic_write(self.state_path, json.dumps(state))

    def status(self):
        state = self._read()
        lock = self._lock()
        if lock is not None:
            try:
                state = self._read()
                # A process terminated before it could record its result.
                if state.get('running'):
                    state.update(running=False, failed=True)
                    self._save(state)
            finally:
                self._unlock(lock)
        return {key: state.get(key, default) for key, default in (
            ('running', False), ('failed', False), ('last_success', None),
        )}

    def run(self, callback, *, fetch_history=True, automatic=False, background=False):
        lock = self._lock(blocking=not background)
        if lock is None:
            return 'busy'
        try:
            state = self._read()
            now = time.time()
            attempts = [stamp for stamp in state.get('auto_attempts', [])
                        if stamp > now - AUTO_REFRESH_WINDOW_SECONDS]
            if automatic and len(attempts) >= AUTO_REFRESH_LIMIT:
                self._unlock(lock)
                return 'limited'
            if automatic:
                attempts.append(now)
            state.update(auto_attempts=attempts, running=True)
            self._save(state)
        except BaseException:
            self._unlock(lock)
            raise

        def execute():
            try:
                result = callback()
                state.update(running=False)
                if fetch_history:
                    state['failed'] = False
                    state['last_success'] = datetime.now(timezone.utc).isoformat()
                self._save(state)
                return result
            except BaseException:
                state.update(running=False, failed=True)
                self._save(state)
                if not background:
                    raise
                logging.exception('Report refresh failed')
            finally:
                self._unlock(lock)

        if background:
            try:
                threading.Thread(target=execute, name='report-refresh', daemon=True).start()
            except BaseException:
                state.update(running=False, failed=True)
                self._save(state)
                self._unlock(lock)
                raise
            return 'started'
        return execute()


manager = RefreshManager()
