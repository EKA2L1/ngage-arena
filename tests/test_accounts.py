"""Cross-title identity ownership and lossless legacy migration."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.accounts import AccountStore
from arena.community import CommunityServer
from arena.games import GameRegistry
from arena.runtime import default_games
from arena.store import Store
from test_ashen import community, leaderboard


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.accounts = AccountStore(self.directory.name)
        self.addCleanup(self.accounts.close)

    def test_same_account_across_game_adapters_and_passwordless_binding(self):
        user = self.accounts.create_user('Player', 'shared-secret')
        games = default_games(self.accounts)
        games.games['42318'].scores.submit_scores(user, {'game_total': 900})
        self.assertEqual(games.games['36280'].store.profile('player')['id'], user)
        tomb = Store(self.directory.name, accounts=self.accounts)
        self.addCleanup(tomb.close)
        status, local = tomb.login('Player', 'test-device-one')
        self.assertEqual(status, 0)
        self.assertNotEqual(tomb.account_id(local), user)
        other = self.accounts.create_user('Other', 'another-secret')
        _, peer = tomb.login('Other', 'test-device-two')
        content = tomb.add_content(1301, 2, 'Existing clip', b'clip', owner=local)
        subject = tomb.db.execute('SELECT identity FROM users WHERE id=?', (local,)).fetchone()[0]
        with self.assertRaises(ValueError):
            self.accounts.link_identity('tomb-raider', subject, 'Player', 'wrong')
        self.accounts.link_identity('tomb-raider', subject, 'player', 'shared-secret')
        self.assertEqual(tomb.account_id(local), user)
        self.assertNotEqual(tomb.account_id(peer), user)
        with self.assertRaises(ValueError):
            self.accounts.link_identity('tomb-raider', subject, 'Other', 'another-secret')
        self.assertEqual(tomb.login('New alias', 'test-device-one'), (0, local))
        self.assertEqual(tomb.account_id(local), user)
        self.assertEqual(tomb.db.execute('SELECT owner FROM objects WHERE id=?', (content,)).fetchone()[0], local)
        self.assertEqual(games.games['42318'].scores.rankings('game_total', 7)[0]['name'], 'Player')

    def test_game_registration_does_not_change_common_authentication(self):
        class NewGame:
            game_class = 'new-game'
            app_uid = 123
            def retrieve(self, user, node):
                return str(user)
        games = GameRegistry([NewGame()])
        self.assertEqual(games.for_uid(123).game_class, 'new-game')
        self.assertIsNone(games.for_uid(456))
        with self.assertRaises(ValueError):
            GameRegistry([NewGame(), NewGame()])
        class OtherGame(NewGame):
            game_class = 'other-game'
        with self.assertRaises(ValueError):
            GameRegistry([NewGame(), OtherGame()])
        server = CommunityServer(self.accounts, games)
        server.soap_response(community('createUser', username='Shared', password='secret'))
        user = self.accounts.authenticate('shared', 'secret')
        self.assertEqual(user, self.accounts.authenticate_snap('Shared', hashlib.sha1(b'secret').hexdigest()))
        request = ET.Element('message', game_class_id='new-game')
        self.assertEqual(ET.fromstring(server.snap_response(user, request)).findtext('retrieve/response'), str(user))
        self.assertIn('Login required', server.snap_response(None, request))
        self.assertIn('Unknown game', server.snap_response(user, leaderboard()))

    def test_registered_game_points_reach_profiles_with_only_native_application_uid(self):
        server = CommunityServer(self.accounts, default_games(self.accounts))
        user = self.accounts.create_user('Angler', 'shared-secret')
        server.achievements.response(b'<player userName="Angler"><commands g="58600"><add id="35" ts="20260913:141429.3"/></commands></player>', user)
        server.profiles.store.update(user, {}, games=[{'uid': 0x2000AFBC}])
        self.assertEqual(server.profiles.store.points(user), [0, 10, 0])
        game = server.profiles.store.games(user)[0]
        self.assertEqual((game['singlePlayerNGPs'], game['multiPlayerNGPs']), (0, 10))

    def test_legacy_database_migration_preserves_ids_credentials_and_game_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            legacy = sqlite3.connect(path/'ashen.sqlite3')
            salt = b'legacy-test-salt!'
            digest = hashlib.scrypt(hashlib.sha1(b'old-secret').hexdigest().encode(), salt=salt, n=16384, r=8, p=1)
            legacy.executescript('''
                CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL,
                    salt BLOB NOT NULL,password BLOB NOT NULL,created REAL NOT NULL);
                CREATE TABLE scores(user_id INTEGER REFERENCES users(id),stat TEXT,score INTEGER,updated REAL,
                    PRIMARY KEY(user_id,stat));
                CREATE TABLE hs_matches(id INTEGER PRIMARY KEY,started REAL NOT NULL,ended REAL,
                    settings BLOB NOT NULL,reason TEXT,winner_team INTEGER);
                CREATE TABLE hs_players(match_id INTEGER REFERENCES hs_matches(id),user_id INTEGER REFERENCES users(id),
                    slot INTEGER,name TEXT,team INTEGER,outcome TEXT,PRIMARY KEY(match_id,slot));
            ''')
            with legacy:
                legacy.execute('INSERT INTO users VALUES(42,?,?,?,1)', ('Existing', salt, digest))
                legacy.execute("INSERT INTO scores VALUES(42,'game_total',12345,1)")
                legacy.execute("INSERT INTO hs_matches VALUES(7,1,2,X'01','surrender',1)")
                legacy.execute("INSERT INTO hs_players VALUES(7,42,1,'Existing',1,'win')")
            legacy.close()
            original = (path/'ashen.sqlite3').read_bytes()
            for _ in range(2):
                accounts = AccountStore(path)
                try:
                    self.assertEqual(accounts.authenticate('existing', 'old-secret'), 42)
                    self.assertEqual(accounts.db.execute('SELECT user_id,score FROM scores').fetchone()[:], (42,12345))
                    self.assertEqual(accounts.db.execute('SELECT user_id,outcome FROM hs_players').fetchone()[:], (42,'win'))
                    self.assertEqual(accounts.db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    self.assertEqual(accounts.db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
                finally:
                    accounts.close()
            self.assertEqual((path/'ashen.sqlite3').read_bytes(), original)
