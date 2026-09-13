"""Native N-Gage achievement reports, keyed by the common Arena account."""
from datetime import datetime
import re
import time
import xml.etree.ElementTree as ET

from arena.rankings import UnsupportedRanking


class AchievementStore:
    def __init__(self, db, games):
        self.db = db
        self.db.execute('''CREATE TABLE IF NOT EXISTS achievements (
            game_class TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
            achievement_id INTEGER NOT NULL, points INTEGER NOT NULL,
            earned TEXT NOT NULL, received REAL NOT NULL, ngp_type INTEGER NOT NULL,
            PRIMARY KEY(game_class,user_id,achievement_id))''')
        if 'ngp_type' not in {row[1] for row in db.execute('PRAGMA table_info(achievements)')}:
            with db:
                db.execute('ALTER TABLE achievements ADD COLUMN ngp_type INTEGER NOT NULL DEFAULT 0')
                for game in games.games.values():
                    for identifier, category in getattr(game, 'achievement_types', {}).items():
                        db.execute('''UPDATE achievements SET ngp_type=?
                            WHERE game_class=? AND achievement_id=?''',
                                   (category, game.game_class, identifier))


class AchievementService:
    def __init__(self, accounts, games):
        self.accounts = accounts
        self.games = games
        self.db = AchievementStore(accounts.db, games).db

    def response(self, body, user):
        name = self.accounts.name(user) if user is not None else None
        if name is None:
            raise PermissionError('Login required')
        if b'<!' in body:
            raise ValueError('Unsupported XML declaration')
        root = ET.fromstring(body)
        if root.tag != 'player' or len(root) != 1 or root[0].tag != 'commands':
            raise ValueError('Expected one achievement command list')
        if root.get('userName', '').casefold() != name.casefold():
            raise PermissionError('Account mismatch')
        commands = root[0]
        game_class = commands.get('g', '')
        game = self.games.games.get(game_class)
        definitions = getattr(game, 'achievement_points', None)
        categories = getattr(game, 'achievement_types', None)
        if definitions is None or categories is None:
            raise UnsupportedRanking('Unsupported achievement game')
        if not 1 <= len(commands) <= 34:
            raise ValueError('Invalid achievement count')
        reports = []
        seen = set()
        for command in commands:
            identifier, earned = command.get('id', ''), command.get('ts', '')
            if (command.tag != 'add' or len(command) or not re.fullmatch(r'[0-9]{1,10}', identifier)
                    or not re.fullmatch(r'[0-9]{8}:[0-9]{6}\.[0-9]{1,6}', earned)):
                raise ValueError('Invalid achievement command')
            identifier = int(identifier)
            if identifier not in definitions or identifier in seen:
                raise ValueError('Unknown or repeated achievement')
            datetime.strptime(earned, '%Y%m%d:%H%M%S.%f')
            seen.add(identifier)
            reports.append((game_class, user, identifier, definitions[identifier], earned,
                            time.time(), categories[identifier]))
        with self.db:
            self.db.executemany('''INSERT INTO achievements
                (game_class,user_id,achievement_id,points,earned,received,ngp_type) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(game_class,user_id,achievement_id) DO NOTHING''', reports)
        # NAFAchievement at 0x85ba requires HTTP 200 and a body beginning with "OK".
        return b'OK'
