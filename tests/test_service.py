import unittest
from unittest.mock import patch

import service


class ServiceTests(unittest.TestCase):
    def test_unit_uses_real_project_and_virtualenv_python(self):
        unit = service.render_unit('/srv/Poe2Logger', '/srv/Poe2Logger/.venv/bin/python', 'deploy', '127.0.0.1:8000')
        self.assertIn('User=deploy\n', unit)
        self.assertIn('WorkingDirectory=/srv/Poe2Logger\n', unit)
        self.assertIn('ExecStart="/srv/Poe2Logger/.venv/bin/python" "-m" "gunicorn"', unit)
        self.assertIn('"--bind" "127.0.0.1:8000"', unit)
        self.assertIn('Restart=on-failure', unit)

    def test_systemd_quoting(self):
        self.assertEqual(service.unit_quote('/srv/Project 100%/$name', command=True),
                         '"/srv/Project 100%%/$$name"')
        with self.assertRaises(ValueError):
            service.unit_quote('path\nExecStart=unexpected')
        self.assertEqual(service.unit_literal('/srv/Project 100%/$name'), '/srv/Project 100%%/$name')

    def test_control_commands_use_sudo_and_propagate_status(self):
        for action in ('start', 'stop', 'restart', 'status', 'logs'):
            with self.subTest(action=action), \
                 patch.object(service.sys, 'platform', 'linux'), \
                 patch.object(service.shutil, 'which', return_value='/usr/bin/systemctl'), \
                 patch.object(service.os, 'geteuid', return_value=1000, create=True), \
                 patch.object(service.subprocess, 'run') as run:
                run.return_value.returncode = 3
                self.assertEqual(service.main([action]), 3)
                command = run.call_args.args[0]
                self.assertEqual(command[0], 'sudo')
                self.assertIn('poe2logger.service', command)
                self.assertEqual(command[1], 'journalctl' if action == 'logs' else 'systemctl')
                if action != 'logs':
                    self.assertEqual(command[2], action)

    def test_root_does_not_use_sudo(self):
        with patch.object(service.os, 'geteuid', return_value=0, create=True), \
             patch.object(service.subprocess, 'run') as run:
            service.run_privileged(['systemctl', 'start', service.SERVICE])
            run.assert_called_once_with(['systemctl', 'start', service.SERVICE], check=True)


if __name__ == '__main__':
    unittest.main()
