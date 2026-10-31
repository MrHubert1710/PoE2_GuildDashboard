import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service


class ServiceTests(unittest.TestCase):
    def test_unit_uses_real_project_and_virtualenv_python(self):
        unit = service.render_unit('/srv/Poe2Logger', '/srv/Poe2Logger/.venv/bin/python', 'deploy', '127.0.0.1:8000')
        self.assertNotIn('\nUser=', unit)
        self.assertIn('WantedBy=default.target', unit)
        self.assertIn('EnvironmentFile=-%h/.config/poe2logger/environment', unit)
        self.assertNotIn('network-online.target', unit)
        self.assertIn('WorkingDirectory=/srv/Poe2Logger\n', unit)
        self.assertIn('ExecStart="/srv/Poe2Logger/.venv/bin/python" "-m" "gunicorn"', unit)
        self.assertIn('"--bind" "127.0.0.1:8000"', unit)
        self.assertIn('Restart=on-failure', unit)

    def test_root_unit_keeps_system_service_settings(self):
        unit = service.render_unit('/srv/app', '/srv/app/venv/bin/python', 'deploy', '127.0.0.1:8000', root=True)
        self.assertIn('User=deploy\n', unit)
        self.assertIn('WantedBy=multi-user.target', unit)
        self.assertIn('EnvironmentFile=-/etc/poe2logger.env', unit)

    def test_user_install_writes_to_xdg_config_without_sudo(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            python = project / '.venv' / 'bin' / 'python'
            python.parent.mkdir(parents=True)
            python.touch()
            config = Path(directory) / 'custom config'
            args = argparse.Namespace(root=False, user=None, venv=None, bind='127.0.0.1:8000', dry_run=False)
            with patch.object(service, 'PROJECT', project), \
                 patch.dict(service.os.environ, {'XDG_CONFIG_HOME': str(config)}), \
                 patch.object(service.shutil, 'which', return_value=None), \
                 patch.object(service.subprocess, 'run') as run, \
                 patch.object(service, 'run_privileged') as privileged:
                self.assertEqual(service.install(args), 0)
                privileged.assert_not_called()
                unit = (config / 'systemd' / 'user' / service.SERVICE).read_text()
                self.assertIn('WantedBy=default.target', unit)
                self.assertNotIn('\nUser=', unit)
                self.assertIn(service.unit_literal(config / 'poe2logger' / 'environment'), unit)
                self.assertEqual([call.args[0] for call in run.call_args_list][1:], [
                    ['systemctl', '--user', 'daemon-reload'],
                    ['systemctl', '--user', 'enable', service.SERVICE],
                ])

    def test_systemd_quoting(self):
        self.assertEqual(service.unit_quote('/srv/Project 100%/$name', command=True),
                         '"/srv/Project 100%%/$$name"')
        with self.assertRaises(ValueError):
            service.unit_quote('path\nExecStart=unexpected')
        self.assertEqual(service.unit_literal('/srv/Project 100%/$name'), '/srv/Project 100%%/$name')

    def test_control_commands_default_to_user_and_propagate_status(self):
        for action in ('start', 'stop', 'restart', 'status', 'logs'):
            with self.subTest(action=action), \
                 patch.object(service.sys, 'platform', 'linux'), \
                 patch.object(service.shutil, 'which', return_value='/usr/bin/systemctl'), \
                 patch.object(service.os, 'geteuid', return_value=1000, create=True), \
                 patch.object(service.subprocess, 'run') as run:
                run.return_value.returncode = 3
                self.assertEqual(service.main([action]), 3)
                command = run.call_args.args[0]
                self.assertNotIn('sudo', command)
                self.assertEqual(command[1], '--user')
                self.assertIn('poe2logger.service', command)
                self.assertEqual(command[0], 'journalctl' if action == 'logs' else 'systemctl')
                if action != 'logs':
                    self.assertEqual(command[2], action)

    def test_root_flag_before_or_after_command(self):
        for action in ('start', 'stop', 'restart', 'status', 'logs'):
            for argv in ([action, '--root'], ['--root', action]):
                with self.subTest(argv=argv), \
                     patch.object(service.sys, 'platform', 'linux'), \
                     patch.object(service.shutil, 'which', return_value='/usr/bin/systemctl'), \
                     patch.object(service.os, 'geteuid', return_value=1000, create=True), \
                     patch.object(service.subprocess, 'run') as run:
                    run.return_value.returncode = 0
                    self.assertEqual(service.main(argv), 0)
                    command = run.call_args.args[0]
                    self.assertEqual(command[0], 'sudo')
                    self.assertNotIn('--user', command)
                    self.assertIn(service.SERVICE, command)

    def test_root_install_flags_reach_installer(self):
        for argv in (['install', '--root', '--user', 'deploy'],
                     ['--root', 'install', '--user', 'deploy']):
            with patch.object(service.sys, 'platform', 'linux'), \
                 patch.object(service.shutil, 'which', return_value='/usr/bin/systemctl'), \
                 patch.object(service.os, 'geteuid', return_value=1000, create=True), \
                 patch.object(service, 'install', return_value=0) as install:
                self.assertEqual(service.main(argv), 0)
                self.assertTrue(install.call_args.args[0].root)
                self.assertEqual(install.call_args.args[0].user, 'deploy')

    def test_root_does_not_use_sudo(self):
        with patch.object(service.os, 'geteuid', return_value=0, create=True), \
             patch.object(service.subprocess, 'run') as run:
            service.run_privileged(['systemctl', 'start', service.SERVICE])
            run.assert_called_once_with(['systemctl', 'start', service.SERVICE], check=True)


if __name__ == '__main__':
    unittest.main()
