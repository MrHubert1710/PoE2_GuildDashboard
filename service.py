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


def render_unit(project, python, user, bind, *, root=False, config_home=None):
    arguments = [python, '-m', 'gunicorn', '--workers', '2', '--worker-class',
                 'gthread', '--threads', '4', '--bind', bind,
                 '--graceful-timeout', '30', '--access-logfile', '-',
                 '--error-logfile', '-', 'app:app']
    command = ' '.join(unit_quote(value, command=True) for value in arguments)
    network = 'Wants=network-online.target\nAfter=network-online.target\n' if root else ''
    account = f'User={unit_literal(user)}\n' if root else ''
    environment_file = (unit_literal('/etc/poe2logger.env') if root else
                        unit_literal(Path(config_home) / 'poe2logger' / 'environment') if config_home else
                        '%h/.config/poe2logger/environment')
    target = 'multi-user.target' if root else 'default.target'
    return f'''[Unit]
Description=Poe2Logger guild dashboard
{network}

[Service]
Type=simple
{account}WorkingDirectory={unit_literal(project)}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-{environment_file}
ExecStart={command}
Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=45
StandardOutput=journal
StandardError=journal

[Install]
WantedBy={target}
'''


def run_privileged(arguments, *, check=True):
    prefix = [] if os.geteuid() == 0 else ['sudo']
    return subprocess.run(prefix + arguments, check=check).returncode


def install(args):
    user = getpass.getuser()
    if args.root:
        import pwd
        user = args.user or os.environ.get('SUDO_USER') or user
        if user == 'root' and not args.user:
            raise ValueError('Specify the service account with --user USER when installing as root.')
        try:
            pwd.getpwnam(user)
        except KeyError:
            raise ValueError(f'Unknown service account: {user}') from None

    config_home = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    if not args.root and not config_home.is_absolute():
        raise ValueError('XDG_CONFIG_HOME must be an absolute path.')

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
    unit = render_unit(PROJECT, python, user, args.bind, root=args.root, config_home=config_home)
    if args.dry_run:
        print(unit, end='')
        return 0

    with tempfile.TemporaryDirectory(prefix='poe2logger-service-') as directory:
        source = Path(directory) / SERVICE
        source.write_text(unit, encoding='utf-8')
        if shutil.which('systemd-analyze'):
            subprocess.run(['systemd-analyze'] + ([] if args.root else ['--user']) +
                           ['verify', str(source)], check=True)
        if args.root:
            run_privileged(['install', '-m', '644', str(source), f'/etc/systemd/system/{SERVICE}'])
        else:
            destination = config_home / 'systemd' / 'user' / SERVICE
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Stage on the same filesystem so replacement is atomic.
            fd, staged = tempfile.mkstemp(dir=destination.parent, prefix=SERVICE + '.')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(unit)
                os.chmod(staged, 0o644)
                os.replace(staged, destination)
            finally:
                if os.path.exists(staged):
                    os.unlink(staged)
    control = ['systemctl'] + ([] if args.root else ['--user'])
    execute = run_privileged if args.root else subprocess.run
    execute(control + ['daemon-reload'], check=True)
    execute(control + ['enable', SERVICE], check=True)
    print(f'Installed {SERVICE} for {user} in {PROJECT}.')
    suffix = ' --root' if args.root else ''
    print(f'Run: python3 service.py start{suffix} (or restart if already running).')
    if not args.root:
        print(f'For startup at boot and after SSH logout, enable linger for {user}:')
        print(f'  loginctl enable-linger {user} (administrator authorization may be required).')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', action='store_true', help='Manage the system-wide service (uses sudo if needed).')
    commands = parser.add_subparsers(dest='action', required=True)
    installer = commands.add_parser('install', help='Install/update and enable the systemd unit; does not start it.')
    installer.add_argument('--user', help='Service account for install --root only (default: invoking user).')
    installer.add_argument('--venv', help='Virtualenv directory (default: .venv or venv in the project).')
    installer.add_argument('--bind', default='127.0.0.1:8000', help='Gunicorn listen address (default: 127.0.0.1:8000).')
    installer.add_argument('--dry-run', action='store_true', help='Print the unit without installing it.')
    for action in ('start', 'stop', 'restart', 'status', 'logs'):
        commands.add_parser(action)
    # Accept --root both before and after the subcommand.
    for command_parser in commands.choices.values():
        command_parser.add_argument('--root', action='store_true', default=argparse.SUPPRESS,
                                    help='Manage the system-wide service.')
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux') or not shutil.which('systemctl'):
        parser.error('This command requires Linux with systemd (for example Ubuntu Server).')
    if os.geteuid() == 0 and not args.root:
        parser.error('Run user-service commands without sudo; use --root for the system-wide service.')
    if args.action == 'install' and args.user and not args.root:
        parser.error('--user requires --root. User services run as the current account.')
    try:
        if args.action == 'install':
            return install(args)
        if args.action == 'logs':
            arguments = ['journalctl'] + ([] if args.root else ['--user']) + ['-u', SERVICE, '-n', '100', '-f']
        else:
            arguments = ['systemctl'] + ([] if args.root else ['--user']) + [args.action, SERVICE]
            if args.action == 'status':
                arguments.extend(['--no-pager', '--full'])
        if args.root:
            return run_privileged(arguments, check=False)
        return subprocess.run(arguments, check=False).returncode
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
