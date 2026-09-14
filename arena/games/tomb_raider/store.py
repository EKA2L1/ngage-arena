import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from arena.services.accounts.store import AccountStore
from arena.games.tomb_raider.codec import Object
from arena.games.tomb_raider.replay import read_ghost

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL,
 identity TEXT UNIQUE NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS objects (
 id INTEGER PRIMARY KEY, parent INTEGER NOT NULL, kind INTEGER NOT NULL,
 name TEXT NOT NULL, name2 TEXT NOT NULL DEFAULT '',
 value1 INTEGER NOT NULL DEFAULT 0, value2 INTEGER NOT NULL DEFAULT 0,
 value3 INTEGER NOT NULL DEFAULT 0, value4 INTEGER NOT NULL DEFAULT 0,
 owner INTEGER REFERENCES users(id), content BLOB, created REAL NOT NULL,
 metadata TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY, body TEXT NOT NULL, sender TEXT NOT NULL,
 recipient INTEGER REFERENCES users(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS race_results (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 race_id INTEGER NOT NULL, milliseconds INTEGER NOT NULL,
 object_id INTEGER NOT NULL REFERENCES objects(id), created REAL NOT NULL, eligible INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS objects_parent ON objects(parent);
CREATE INDEX IF NOT EXISTS race_best ON race_results(race_id,milliseconds);
CREATE TABLE IF NOT EXISTS courses (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, level INTEGER NOT NULL,
 description BLOB NOT NULL, reference_object INTEGER NOT NULL REFERENCES objects(id));
CREATE TABLE IF NOT EXISTS challenges (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 opponent INTEGER REFERENCES users(id), race_id INTEGER NOT NULL,
 object_id INTEGER NOT NULL REFERENCES objects(id), target_ms INTEGER NOT NULL,
 created REAL NOT NULL, result_id INTEGER REFERENCES race_results(id), competitive INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS league_events (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 challenge_id INTEGER UNIQUE REFERENCES challenges(id), points INTEGER NOT NULL,
 month TEXT NOT NULL, created REAL NOT NULL);
'''

class Store:
    def __init__(self, directory, accounts=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        key_path = directory / 'identity.key'
        try:
            self.key = key_path.read_bytes()
        except FileNotFoundError:
            self.key = secrets.token_bytes(32)
            with key_path.open('xb') as stream:
                stream.write(self.key)
            key_path.chmod(0o600)
        self.db = sqlite3.connect(directory / 'arena.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(SCHEMA)
        for table,column in (('race_results','eligible'),('challenges','competitive')):
            if column not in {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}:
                with self.db:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 1')
                    if column == 'eligible':
                        self.db.execute('UPDATE race_results SET eligible=0 WHERE id IN (SELECT result_id FROM challenges WHERE race_results.milliseconds>=target_ms)')
        self.accounts = accounts or AccountStore(directory)
        self.owns_accounts = accounts is None
        for row in self.db.execute('SELECT identity FROM users'):
            self.accounts.register_identity('tomb-raider', row['identity'])
        self.seed()

    def seed(self):
        rows = [(900,1,0,'Fastest Finish'), (1401,1,0,'Strategy Guide'),
                (1301,1,0,'Player Clips'), (501,1,0,'Messages'), (912,1,0,'League'),
                (1202,1201,0,'Player clips'), (12002,1202,2,'Share clip'),
                (1203,1201,0,'Strategy guide'),
                (2001,1,0,'Monthly Trophies')]
        levels = ("Lara's Home",'Caves','City of Vilcabamba','Lost Valley','Tomb of Qualopec',
                  "St. Francis Folly",'Colosseum','Palace Midas','The Cistern','Tomb of Tihocan',
                  'City of Khamoon','Obelisk of Khamoon','Sanctuary of Scion',"Natla's Mines",'Atlantis','The Great Pyramid')
        rows.extend((1402+level,1401,0,name) for level,name in enumerate(levels))
        rows.extend((3000+level,1203,2,name) for level,name in enumerate(levels))
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO messages(id,body,sender,created) VALUES(1,?,?,?)',
                ('Welcome to Local Arena. Download a Caves practice race, share your own clips, or read the local strategy guides. League rules: win +10, loss -5.','Arena',time.time()))
            for oid, parent, kind, name in rows:
                self.db.execute('INSERT OR IGNORE INTO objects(id,parent,kind,name,created) VALUES(?,?,?,?,?)',
                                (oid,parent,kind,name,time.time()))

    def login(self, name, identity):
        name = name.strip()
        if not name or len(name) > 12 or any(ord(c) < 32 for c in name):
            return 1, None
        digest = hmac.new(self.key, identity.encode('latin-1'), hashlib.sha256).hexdigest()
        user = self.db.execute('SELECT * FROM users WHERE identity=?', (digest,)).fetchone()
        owner = self.db.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
        if owner and (not user or user['id'] != owner['id']):
            return 3, None
        with self.db:
            if user:
                self.db.execute('UPDATE users SET name=? WHERE id=?', (name,user['id']))
                uid = user['id']
            else:
                uid = self.db.execute('INSERT INTO users(name,identity,created) VALUES(?,?,?)',
                                      (name,digest,time.time())).lastrowid
        self.accounts.register_identity('tomb-raider', digest)
        return 0, uid

    def account_id(self, user):
        row = self.db.execute('SELECT identity FROM users WHERE id=?', (user,)).fetchone()
        return self.accounts.identity_account('tomb-raider', row['identity']) if row else None

    def close(self):
        self.db.close()
        if self.owns_accounts:
            self.accounts.close()

    def objects(self, parent):
        rows = self.db.execute('SELECT * FROM objects WHERE parent=? ORDER BY id', (parent,)).fetchall()
        return [Object(row['id'],row['kind'],row['name'],row['name2'],
                       value1=row['value1'],value2=row['value2'],value3=row['value3'],value4=row['value4']) for row in rows]

    def content(self, oid):
        row = self.db.execute('SELECT content FROM objects WHERE id=?', (oid,)).fetchone()
        return bytes(row[0]) if row and row[0] is not None else None

    def add_content(self, parent, kind, name, data, owner=None, metadata=None, oid=None):
        with self.db:
            return self._insert_content(parent,kind,name,data,owner,metadata,oid)

    def _insert_content(self, parent, kind, name, data, owner=None, metadata=None, oid=None):
        if oid is None:
            oid = self.db.execute('SELECT MAX(10000,COALESCE(MAX(id),0))+1 FROM objects').fetchone()[0]
        self.db.execute('INSERT INTO objects(id,parent,kind,name,owner,content,created,metadata) VALUES(?,?,?,?,?,?,?,?)',
                        (oid,parent,kind,name[:20],owner,data,time.time(),json.dumps(metadata or {})))
        return oid

    def messages(self, user):
        return self.db.execute('SELECT * FROM messages WHERE recipient IS NULL OR recipient=? ORDER BY id DESC LIMIT 100', (user,)).fetchall()

    def import_course(self, name, data):
        ghost = read_ghost(data)
        existing = self.db.execute('SELECT * FROM courses WHERE id=?', (ghost.race_id,)).fetchone()
        if existing:
            if bytes(existing['description']) != ghost.course:
                raise ValueError('Race ID already belongs to another course')
            return existing['reference_object']
        with self.db:
            oid = self._insert_content(0,1001,name,data,metadata={'reference':True})
            self.db.execute('INSERT INTO courses VALUES(?,?,?,?,?)',
                            (ghost.race_id, name[:20], ghost.level, ghost.course, oid))
            self._insert_content(900,0,name,None,metadata={'course_id':ghost.race_id})
        return oid

    def courses(self):
        return self.db.execute('SELECT * FROM courses ORDER BY id').fetchall()

    def leaders(self, race_id):
        return self.db.execute('''
            SELECT r.*, u.name, COALESCE((SELECT SUM(points) FROM league_events e
                WHERE e.user_id=r.user_id AND e.month=?),0) AS score
            FROM race_results r JOIN users u ON u.id=r.user_id
            WHERE r.race_id=? AND r.eligible=1 AND r.id=(SELECT r2.id FROM race_results r2
                WHERE r2.race_id=r.race_id AND r2.user_id=r.user_id AND r2.eligible=1
                ORDER BY r2.milliseconds,r2.id LIMIT 1)
            ORDER BY r.milliseconds,r.id LIMIT 100
            ''', (self.month(),race_id)).fetchall()

    @staticmethod
    def month(timestamp=None):
        return datetime.fromtimestamp(time.time() if timestamp is None else timestamp,timezone.utc).strftime('%Y-%m')

    def start_challenge(self, user, object_id, competitive=True):
        row = self.db.execute('SELECT * FROM objects WHERE id=?', (object_id,)).fetchone()
        if not row or row['kind'] != 1001 or row['content'] is None:
            raise ValueError('Object is not a race recording')
        ghost = read_ghost(bytes(row['content']))
        with self.db:
            challenge = self.db.execute('''INSERT INTO challenges
                (user_id,opponent,race_id,object_id,target_ms,created,competitive) VALUES(?,?,?,?,?,?,?)''',
                (user,row['owner'],ghost.race_id,object_id,ghost.milliseconds,time.time(),int(competitive))).lastrowid
        return challenge

    def finish_race(self, user, data, caption):
        ghost = read_ghost(data)
        course = self.db.execute('SELECT * FROM courses WHERE id=?', (ghost.race_id,)).fetchone()
        if not course or bytes(course['description']) != ghost.course:
            raise ValueError('Race description does not match a published course')
        challenge = self.db.execute('''SELECT * FROM challenges WHERE user_id=? AND race_id=?
            ORDER BY id DESC LIMIT 1''', (user,ghost.race_id)).fetchone()
        if challenge and challenge['result_id'] is not None:
            previous = self.db.execute('SELECT object_id FROM race_results WHERE id=?',(challenge['result_id'],)).fetchone()[0]
            if self.content(previous) == data:
                return previous
            raise ValueError('Download a new challenge before submitting another result')
        won = challenge is None or ghost.milliseconds < challenge['target_ms']
        now = time.time()
        with self.db:
            oid = self._insert_content(0,1001,caption or 'Race recording',data,user,
                                       {'race_id':ghost.race_id,'milliseconds':ghost.milliseconds})
            result = self.db.execute('''INSERT INTO race_results
                (user_id,race_id,milliseconds,object_id,created,eligible) VALUES(?,?,?,?,?,?)''',
                (user,ghost.race_id,ghost.milliseconds,oid,now,int(won))).lastrowid
            if challenge:
                # Local league rules: one scored submission per downloaded challenge.
                points = (10 if won else -5) if challenge['competitive'] and challenge['opponent'] is not None and challenge['opponent'] != user else 0
                self.db.execute('UPDATE challenges SET result_id=? WHERE id=?', (result,challenge['id']))
                self.db.execute('INSERT INTO league_events(user_id,challenge_id,points,month,created) VALUES(?,?,?,?,?)',
                                (user,challenge['id'],points,self.month(now),now))
                if won and challenge['competitive'] and caption.strip() and challenge['opponent'] is not None and challenge['opponent'] != user:
                    sender = self.db.execute('SELECT name FROM users WHERE id=?',(user,)).fetchone()[0]
                    self.db.execute('INSERT INTO messages(body,sender,recipient,created) VALUES(?,?,?,?)',
                        (caption[:200],sender,challenge['opponent'],now))
        return oid

    def trophies(self):
        return self.db.execute('''WITH standings AS (
            SELECT month,user_id,SUM(points) AS points FROM league_events
            WHERE month < ? GROUP BY month,user_id), ranked AS (
            SELECT *,ROW_NUMBER() OVER(PARTITION BY month ORDER BY points DESC,user_id) AS place
            FROM standings WHERE points > 0)
            SELECT ranked.*,users.name FROM ranked JOIN users ON users.id=ranked.user_id
            WHERE place <= 3 ORDER BY month DESC,place LIMIT 36''', (self.month(),)).fetchall()
