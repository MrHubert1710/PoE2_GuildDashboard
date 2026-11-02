#!/usr/bin/env python3
"""Create/reset a local administrator; passwords never use argv or stdout."""
import getpass
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.auth import AuthStore


def configure(store, installation=False):
    if installation and not store.default_password_active():
        print('Administrator password is already configured; keeping it unchanged.')
        return
    username = 'admin' if installation else input('Administrator username [admin]: ').strip() or 'admin'
    prompt = 'New admin password (Enter to skip — not recommended): ' if installation else 'New password (at least 12 characters): '
    password = getpass.getpass(prompt)
    if installation and not password:
        print('Keeping the default admin password (not recommended).')
        return
    if password != getpass.getpass('Repeat password: '):
        raise ValueError('Passwords do not match.')
    store.set_password(username, password)
    print('Administrator saved. Previous sessions for this account have been revoked.')


if __name__ == '__main__':
    try:
        configure(AuthStore(Path(__file__).resolve().parents[1] / 'data/auth/admin.sqlite'),
                  installation=sys.argv[1:] == ['--install'])
    except ValueError as error:
        raise SystemExit(str(error))
