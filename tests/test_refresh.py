import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import app as web
from poe2logger import fetcher
from poe2logger.refresh import RefreshManager, atomic_write


def check_process_lock(directory, queue):
    queue.put(RefreshManager(directory).run(lambda: None, background=True))


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = RefreshManager(self.temp.name)

    def test_rolling_limit_manual_bypass_and_restart(self):
        for _ in range(2):
            self.manager.run(lambda: None, automatic=True)
        self.assertEqual(RefreshManager(self.temp.name).run(lambda: None, automatic=True), 'limited')
        self.assertIsNone(self.manager.run(lambda: None))
        with patch('poe2logger.refresh.time.time', return_value=10**12):
            self.assertIsNone(self.manager.run(lambda: None, automatic=True))

    def test_failure_keeps_success_and_consumes_auto_attempt(self):
        self.manager.run(lambda: None)
        stamp = self.manager.status()['last_success']
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.manager.run(lambda: (_ for _ in ()).throw(ValueError('secret')), automatic=True)
        self.assertTrue(self.manager.status()['failed'])
        self.assertEqual(self.manager.status()['last_success'], stamp)
        self.manager.run(lambda: None, fetch_history=False)
        self.assertTrue(self.manager.status()['failed'])
        self.assertEqual(self.manager.status()['last_success'], stamp)
        self.assertEqual(self.manager.run(lambda: None, automatic=True), 'limited')
        self.manager.run(lambda: None)
        self.assertFalse(self.manager.status()['failed'])

    def test_background_coalescing_and_cross_process_lock(self):
        entered, release = threading.Event(), threading.Event()
        def work():
            entered.set()
            release.wait(10)
        self.assertEqual(self.manager.run(work, background=True), 'started')
        self.assertTrue(entered.wait(2))
        try:
            self.assertTrue(self.manager.status()['running'])
            self.assertEqual(self.manager.run(lambda: None, background=True), 'busy')
            context = multiprocessing.get_context('spawn')
            queue = context.Queue()
            process = context.Process(target=check_process_lock, args=(self.temp.name, queue))
            process.start()
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(queue.get(timeout=2), 'busy')
        finally:
            release.set()
            # Waiting for an exclusive synchronous run also joins the prior job.
            self.manager.run(lambda: None, fetch_history=False)

    def test_interrupted_worker_is_reported_as_failed(self):
        self.manager._save({'running': True, 'last_success': 'previous'})
        self.assertEqual(self.manager.status(), {
            'running': False, 'failed': True, 'last_success': 'previous'})


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = RefreshManager(self.temp.name)
        self.report = Path(self.temp.name) / 'report.html'
        atomic_write(self.report, '<html><body><p>Last good data</p></body></html>')
        for patcher in (patch.object(web, 'manager', self.manager),
                        patch.object(web, 'LATEST_DASHBOARD_FILE', str(self.report))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = web.app.test_client()

    def test_get_returns_saved_report_while_refresh_is_blocked(self):
        entered, release = threading.Event(), threading.Event()
        def work(**kwargs):
            entered.set()
            release.wait(10)
        with patch.object(web, '_generate_report', side_effect=work):
            try:
                response = self.client.get('/')
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'Last good data', response.data)
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.client.get('/api/refresh-status').json['running'])
                self.assertEqual(self.client.post('/api/refresh', headers={
                    'X-Requested-With': 'Poe2Logger'}).json['outcome'], 'busy')
            finally:
                release.set()
                self.manager.run(lambda: None, fetch_history=False)

    def test_failed_fetch_preserves_html_without_leaking_reason(self):
        with patch.object(web, '_generate_report', side_effect=ValueError('SECRET SESSION')):
            self.client.post('/api/refresh', headers={'X-Requested-With': 'Poe2Logger'})
            lock = self.manager._lock(blocking=True)
            self.manager._unlock(lock)
        status = self.client.get('/api/refresh-status')
        self.assertTrue(status.json['failed'])
        self.assertNotIn(b'SECRET', status.data)
        response = self.client.get('/?__snapshot=1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Last good data', response.data)
        self.assertIn(b'"failed": true', response.data)
        self.assertNotIn(b'SECRET', response.data)

    def test_all_clients_observe_cli_publication(self):
        revision = self.client.get('/api/refresh-status').json['revision']
        self.manager.run(lambda: atomic_write(self.report, '<html><body>New data</body></html>'))
        for client in (self.client, web.app.test_client()):
            status = client.get('/api/refresh-status').json
            self.assertNotEqual(status['revision'], revision)
            self.assertIsNotNone(status['last_success'])
            with patch.object(web, 'start_refresh') as start:
                self.assertIn(b'New data', client.get('/?__snapshot=1').data)
                start.assert_not_called()

    def test_no_saved_report_and_manual_post_protection(self):
        self.report.unlink()
        self.assertEqual(self.client.get('/?__snapshot=1').status_code, 200)
        self.assertEqual(self.client.post('/api/refresh').status_code, 400)
        self.assertEqual(self.client.get('/health').data, b'ok\n')

    def test_links_work_below_nginx_prefix(self):
        import re
        from urllib.parse import urljoin
        response = self.client.get('/?__snapshot=1')
        text = response.get_data(as_text=True)
        bootstrap = json.loads(re.search(
            r'<script id="refresh-bootstrap" type="application/json">(.*?)</script>', text
        ).group(1))
        for base in ('https://example.test/poe2-guild/',
                     'https://example.test/poe2-guild/GuildReport_Latest.html'):
            self.assertEqual(urljoin(base, bootstrap['status_url']),
                             'https://example.test/poe2-guild/api/refresh-status')
            self.assertEqual(urljoin(base, bootstrap['refresh_url']),
                             'https://example.test/poe2-guild/api/refresh')
        self.assertIn('src="static/refresh.js"', text)


class ApiLimitTests(unittest.TestCase):
    def test_error_payload_is_not_mistaken_for_empty_history(self):
        self.assertTrue(fetcher.has_history_entry_list({'entries': []}))
        self.assertTrue(fetcher.has_history_entry_list({'result': {'entries': []}}))
        self.assertFalse(fetcher.has_history_entry_list({'error': {'message': 'expired'}}))
        self.assertFalse(fetcher.has_history_entry_list({'unexpected': []}))

    def test_cooldown_survives_separate_fetches(self):
        with tempfile.TemporaryDirectory() as directory:
            response = unittest.mock.MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = b'{"entries": []}'
            response.headers = {'Retry-After': '60'}
            with patch.object(fetcher, 'API_COOLDOWN_FILE', str(Path(directory) / 'api_cooldown.json')), \
                 patch.object(fetcher.urllib.request, 'urlopen', return_value=response), \
                 patch.object(fetcher.time, 'time', return_value=100), \
                 patch.object(fetcher.time, 'sleep') as sleep:
                fetcher.request_guild_history_page('guild', 'session', 1, 0)
                sleep.assert_not_called()
                self.assertEqual(json.loads((Path(directory) / 'api_cooldown.json').read_text()), 161)
                fetcher.request_guild_history_page('guild', 'session', 1, 0)
                sleep.assert_called_once_with(61)


if __name__ == '__main__':
    unittest.main()
