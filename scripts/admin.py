#!/usr/bin/env python3
"""Create/reset a local administrator; passwords never use argv or stdout."""
import getpass
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.auth import AuthStore

if __name__ == '__main__':
    username = input('Administrator username [admin]: ').strip() or 'admin'
    password = getpass.getpass('New password (at least 12 characters): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match.')
    try:
        AuthStore(Path(__file__).resolve().parents[1] / 'data/auth/admin.sqlite').set_password(username, password)
    except ValueError as error:
        raise SystemExit(str(error))
    print('Administrator saved. Previous sessions for this account have been revoked.')
