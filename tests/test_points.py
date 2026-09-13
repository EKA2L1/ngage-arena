from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

from arena.accounts import AccountStore
from arena.achievements import AchievementService
from arena.rankings import RankingsService, UnsupportedRanking
from arena.runtime import default_games


NATIVE_POINTS = (Path(__file__).parent/'fixtures/launcher-points.xml').read_bytes()


class PointBoardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
        self.owner = self.accounts.create_user('Angler', 'native-test')
        self.peer = self.accounts.create_user('Peer', 'native-test')
        self.games = default_games(self.accounts)
        self.games.games['123'] = SimpleNamespace(game_class='123',
            achievement_points={1: 40}, achievement_types={1: 1})
        self.rankings = RankingsService(self.accounts, self.games)
        self.achievements = AchievementService(self.accounts, self.games)

    def tearDown(self):
        self.accounts.close()
        self.directory.cleanup()

    def award(self, identifier, name='Angler', game='58600'):
        user = self.owner if name == 'Angler' else self.peer
        self.achievements.response((f'<player userName="{name}"><commands g="{game}">'
            f'<add id="{identifier}" ts="20260913:141429.3"/></commands></player>').encode(), user)

    def query(self, board='ngpsglobal', game='4444', **params):
        root = ET.fromstring(NATIVE_POINTS)
        root.find('request/gameinfo').set('gameclassid', game)
        for item in root.iter('item'):
            key = item.get('name')
            if key == 'board':
                item.set('value', board)
            elif key in params:
                item.set('value', params[key])
        return ET.tostring(root)

    def rows(self, body):
        text = ET.fromstring(self.rankings.response(body, None)).text.splitlines()
        self.assertEqual(text[:2], ['0', 'OK'])
        self.assertEqual(len(text[2].split('|')), 7)
        return [row.split('|') for row in text[3:]]

    def test_native_columns_separate_single_multiplayer_and_total_points(self):
        self.award(1)
        self.award(35)
        self.award(36)
        self.award(36)
        self.assertEqual(self.rows(NATIVE_POINTS), [['Angler', '1', '10', '30', '0', '40', '0']])
        self.assertEqual(self.rows(self.query('ngps', '58600')),
                         [['Angler', '1', '10', '30', '40', '0']])

    def test_global_points_share_accounts_but_game_points_remain_scoped(self):
        self.award(35)
        self.award(1, game='123')
        self.award(34, name='Peer')
        self.assertEqual(self.rows(self.query(above='1', below='1')),
                         [['Angler', '1', '40', '10', '0', '50', '0'],
                          ['Peer', '1', '50', '0', '0', '50', '0']])
        self.assertEqual(self.rows(self.query('ngps', '58600', above='1', below='1')),
                         [['Peer', '1', '50', '0', '50', '0'],
                          ['Angler', '2', '0', '10', '10', '0']])

    def test_public_zero_points_unknown_player_and_pagination(self):
        self.assertEqual(self.rows(self.query('ngps', '804')), [['Angler', '1', '0', '0', '0', '0']])
        self.assertEqual(self.rows(self.query(name='Missing')), [])
        self.accounts.register_identity('airplay', 'unlinked')
        root = ET.fromstring(NATIVE_POINTS)
        root.set('EventType', 'topn')
        request = root.find('request')
        request.set('type', 'topn')
        items = request.find('itemlist')
        for item in list(items):
            if item.get('name') in ('name', 'above', 'below'):
                items.remove(item)
        ET.SubElement(items, 'item', name='offset', value='1')
        ET.SubElement(items, 'item', name='limit', value='1')
        self.assertEqual(self.rows(ET.tostring(root)), [['Peer', '1', '0', '0', '0', '0', '0']])

    def test_unsupported_filters_and_invalid_ranges_are_rejected(self):
        for params in [dict(above='-1'), dict(below='101'), dict(name='a|b')]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.rows(self.query(**params))
        for params in [dict(userList='Peer'), dict(stat='TOTAL_XP'), dict(periodicity='daily')]:
            with self.subTest(params=params), self.assertRaises(UnsupportedRanking):
                self.rows(self.query(**params))

    def test_migration_preserves_earned_time_and_backfills_definition_types(self):
        self.accounts.db.execute('DROP TABLE achievements')
        self.accounts.db.execute('''CREATE TABLE achievements (
            game_class TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
            achievement_id INTEGER NOT NULL, points INTEGER NOT NULL,
            earned TEXT NOT NULL, received REAL NOT NULL,
            PRIMARY KEY(game_class,user_id,achievement_id))''')
        self.accounts.db.execute('INSERT INTO achievements VALUES(?,?,?,?,?,?)',
                                ('58600', self.owner, 35, 10, '20260913:141429.3', 1.0))
        self.accounts.db.commit()
        for _ in range(2):
            self.rankings = RankingsService(self.accounts, self.games)
        self.assertEqual(self.rows(NATIVE_POINTS), [['Angler', '1', '0', '10', '0', '10', '0']])
        row = self.accounts.db.execute('SELECT * FROM achievements').fetchone()
        self.assertEqual((row['earned'], row['received'], row['ngp_type']), ('20260913:141429.3', 1.0, 2))
