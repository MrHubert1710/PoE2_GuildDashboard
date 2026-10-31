"""Install and manage the Poe2Logger systemd service on Ubuntu."""
import argparse
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


SERVICE = 'poe2logger.service'
PROJECT = Path(__file__).resolve().parent


def unit_quote(value, *, command=False):
    """Quote systemd values, including specifiers and ExecStart expansion."""
    value = str(value)
    if any(character in value for character in '\n\r\0'):
        raise ValueError('Paths and arguments must not contain line breaks or NUL.')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if command:
        value = value.replace('$', '$$')
    return f'"{value}"'


def unit_literal(value):
    """User/WorkingDirectory take a literal value, not an ExecStart token."""
    value = str(value)
    if any(character in value for character in '\n\r\0') or value.endswith('\\') or value != value.strip():
        raise ValueError('Invalid literal systemd setting.')
    return value.replace('%', '%%')


def render_unit(project, python, user, bind):
    arguments = [python, '-m', 'gunicorn', '--workers', '2', '--worker-class',
                 'gthread', '--threads', '4', '--bind', bind,
                 '--graceful-timeout', '30', '--access-logfile', '-',
                 '--error-logfile', '-', 'app:app']
    command = ' '.join(unit_quote(value, command=True) for value in arguments)
    return f'''[Unit]
Description=Poe2Logger guild dashboard
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={unit_literal(user)}
WorkingDirectory={unit_literal(project)}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/etc/poe2logger.env
ExecStart={command}
Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=45
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
'''


def run_privileged(arguments, *, check=True):
    prefix = [] if os.geteuid() == 0 else ['sudo']
    return subprocess.run(prefix + arguments, check=check).returncode


def install(args):
    import pwd

    user = args.user or os.environ.get('SUDO_USER') or getpass.getuser()
    if user == 'root' and not args.user:
        raise ValueError('Specify the service account with --user USER when installing as root.')
    try:
        pwd.getpwnam(user)
    except KeyError:
        raise ValueError(f'Unknown service account: {user}') from None

    if args.venv:
        environment = Path(args.venv).resolve()
    else:
        environment = next((PROJECT / name for name in ('.venv', 'venv')
                            if (PROJECT / name / 'bin' / 'python').is_file()), PROJECT / '.venv')
    # Keep the venv path: resolving its Python symlink would bypass the venv.
    python = environment / 'bin' / 'python'
    if not python.is_file():
        raise ValueError(f'Missing {python}. Create a venv and install required.txt first.')
    subprocess.run([str(python), '-c', 'import flask, gunicorn'], check=True)
    unit = render_unit(PROJECT, python, user, args.bind)
    if args.dry_run:
        print(unit, end='')
        return 0

    with tempfile.TemporaryDirectory(prefix='poe2logger-service-') as directory:
        source = Path(directory) / SERVICE
        source.write_text(unit, encoding='utf-8')
        if shutil.which('systemd-analyze'):
            subprocess.run(['systemd-analyze', 'verify', str(source)], check=True)
        run_privileged(['install', '-m', '644', str(source), f'/etc/systemd/system/{SERVICE}'])
    run_privileged(['systemctl', 'daemon-reload'])
    run_privileged(['systemctl', 'enable', SERVICE])
    print(f'Installed {SERVICE} for {user} in {PROJECT}.')
    print('Run: python3 service.py start (or restart if already running).')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    installer = commands.add_parser('install', help='Install/update and enable the systemd unit; does not start it.')
    installer.add_argument('--user', help='Existing Linux account to run the application (default: invoking user).')
    installer.add_argument('--venv', help='Virtualenv directory (default: .venv or venv in the project).')
    installer.add_argument('--bind', default='127.0.0.1:8000', help='Gunicorn listen address (default: 127.0.0.1:8000).')
    installer.add_argument('--dry-run', action='store_true', help='Print the unit without installing it.')
    for action in ('start', 'stop', 'restart', 'status', 'logs'):
        commands.add_parser(action)
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux') or not shutil.which('systemctl'):
        parser.error('This command requires Linux with systemd (for example Ubuntu Server).')
    try:
        if args.action == 'install':
            return install(args)
        if args.action == 'logs':
            return run_privileged(['journalctl', '-u', SERVICE, '-n', '100', '-f'], check=False)
        arguments = ['systemctl', args.action, SERVICE]
        if args.action == 'status':
            arguments.extend(['--no-pager', '--full'])
        return run_privileged(arguments, check=False)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
