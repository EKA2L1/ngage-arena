"""Shared Arena accounts and explicit bindings for passwordless legacy clients."""
import argparse
import getpass
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time


class AccountStore:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        database = directory / 'community.sqlite3'
        self.db = sqlite3.connect(database)
        database.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL,
            salt BLOB NOT NULL, password BLOB NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS identities (
            provider TEXT NOT NULL, subject TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY(provider,subject));
        ''')

    def create_user(self, name, password):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,20}', name) or not 1 <= len(password) <= 128:
            raise ValueError('Invalid username or password')
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(hashlib.sha1(password.encode()).hexdigest().encode(),
                                salt=salt, n=16384, r=8, p=1)
        try:
            with self.db:
                return self.db.execute('INSERT INTO users(name,salt,password,created) VALUES(?,?,?,?)',
                                       (name, salt, digest, time.time())).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('Username is already registered') from None

    def authenticate(self, name, password):
        if not 1 <= len(password) <= 128:
            return None
        return self.authenticate_snap(name, hashlib.sha1(password.encode()).hexdigest())

    def authenticate_snap(self, name, credential):
        # The SNAP SDK sends lowercase SHA-1 in the legacy XMPP password field.
        if not re.fullmatch(r'[0-9a-f]{40}', credential):
            return None
        user = self.db.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
        if not user:
            return None
        digest = hashlib.scrypt(credential.encode(), salt=user['salt'], n=16384, r=8, p=1)
        return user['id'] if hmac.compare_digest(digest, user['password']) else None

    def close(self):
        self.db.close()

    def name(self, user):
        row = self.db.execute('SELECT name FROM users WHERE id=?', (user,)).fetchone()
        return row['name'] if row else None

    def identity_account(self, provider, subject):
        row = self.db.execute('SELECT user_id FROM identities WHERE provider=? AND subject=?',
                              (provider, subject)).fetchone()
        return row['user_id'] if row else None

    def register_identity(self, provider, subject):
        with self.db:
            # A reserved name cannot be selected through password registration.
            self.db.execute('INSERT OR IGNORE INTO users(name,salt,password,created) VALUES(?,?,?,?)',
                            ('~'+provider+':'+subject, secrets.token_bytes(16), secrets.token_bytes(64), time.time()))
            user = self.db.execute('SELECT id FROM users WHERE name=?', ('~'+provider+':'+subject,)).fetchone()[0]
            self.db.execute('INSERT OR IGNORE INTO identities VALUES(?,?,?)', (provider, subject, user))
        return self.identity_account(provider, subject)

    def link_identity(self, provider, subject, name, password):
        user = self.authenticate(name, password)
        if user is None:
            raise ValueError('Invalid username or password')
        with self.db:
            previous = self.identity_account(provider, subject)
            if previous is None:
                raise ValueError('Unknown device identity')
            if previous != user and not self.name(previous).startswith('~'+provider+':'):
                raise ValueError('Device is already linked to another account')
            self.db.execute('UPDATE identities SET user_id=? WHERE provider=? AND subject=?',
                            (user, provider, subject))
        return user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('data'))
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create', help='Create an account shared by all games')
    create.add_argument('name')
    link = commands.add_parser('link-tomb', help='Bind a local Tomb Raider player to a password account')
    link.add_argument('player')
    link.add_argument('--account', required=True)
    args = parser.parse_args()
    accounts = AccountStore(args.data)
    try:
        password = getpass.getpass('Account password: ')
        if args.command == 'create':
            print('Account', accounts.create_user(args.name, password), 'created.')
        else:
            from arena.games.tomb_raider.store import Store
            store = Store(args.data, accounts=accounts)
            try:
                row = store.db.execute('SELECT identity FROM users WHERE name=?', (args.player,)).fetchone()
                if row is None:
                    raise ValueError('Unknown Tomb Raider player')
                user = accounts.link_identity('tomb-raider', row['identity'], args.account, password)
                print('Player linked to account', user)
            finally:
                store.close()
    finally:
        accounts.close()


if __name__ == '__main__':
    main()
