"""Account profiles shared by Launcher and games, with the N-Gage 2.0 SOAP adapter."""
from datetime import datetime, timezone
import json
import time
import xml.etree.ElementTree as ET

from arena.xmlutil import local

SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
NGP = 'http://www.nokia.com/ngp/'
STRINGS = ('firstName', 'lastName', 'email', 'phoneNum', 'city', 'state', 'country',
           'gender', 'quote', 'favoriteGame')
PRIVACY = ('displayMyFriendsList', 'displayMyCity', 'displayMyCountry')
POINT_TYPES = ('SINGLE_PLAYER_NGPS', 'MULTI_PLAYER_NGPS', 'COMMUNITY_NGPS')


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def parse_timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Expected a timestamp with a time zone')
    return parsed.timestamp()


def children(node):
    result = {}
    for child in node:
        name = local(child.tag)
        if name in result:
            raise ValueError('Duplicate profile field')
        result[name] = child
    return result


def string(node, limit=256):
    value = node.text or ''
    if len(node) or len(value) > limit:
        raise ValueError('Invalid profile string')
    return value


def boolean(node):
    value = string(node, 5)
    if value not in ('true', 'false', '0', '1'):
        raise ValueError('Invalid boolean')
    return value in ('true', '1')


def number(node, maximum=0x7fffffff):
    value = int(string(node, 20))
    if not 0 <= value <= maximum:
        raise ValueError('Integer out of range')
    return value


def element(parent, name, value=None):
    child = ET.SubElement(parent, name)
    if value is not None:
        child.text = ('true' if value else 'false') if isinstance(value, bool) else str(value)
    return child


class ProfileStore:
    def __init__(self, accounts, clock=time.time, point_totals=None):
        self.accounts = accounts
        self.db = accounts.db
        self.clock = clock
        self.point_totals = point_totals
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY REFERENCES users(id),
                data TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS friendships (
                sender INTEGER NOT NULL REFERENCES users(id),
                recipient INTEGER NOT NULL REFERENCES users(id),
                accepted INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL,
                PRIMARY KEY(sender,recipient), CHECK(sender != recipient));
            CREATE TABLE IF NOT EXISTS profile_games (
                user_id INTEGER NOT NULL REFERENCES users(id), uid INTEGER NOT NULL,
                data TEXT NOT NULL, PRIMARY KEY(user_id,uid));
        ''')

    def require_user(self, user):
        row = self.db.execute('SELECT id,name,created FROM users WHERE id=?', (user,)).fetchone()
        if row is None:
            raise PermissionError('Login required')
        return row

    def get(self, user):
        account = self.require_user(user)
        row = self.db.execute('SELECT data,updated FROM profiles WHERE user_id=?', (user,)).fetchone()
        result = {name: '' for name in STRINGS}
        result.update(privacySetting={name: False for name in PRIVACY},
                      alertSubscription=[], ignoreUsersList=[], newsLetterSubscription=False,
                      userIcon={'id': '', 'type': ''}, dateOfBirth=None, iconUrl='', level=0, reputation=0.0)
        if row:
            result.update(json.loads(row['data']))
        result['username'] = account['name']
        result['updated'] = row['updated'] if row else account['created']
        return result

    def named(self, name):
        row = self.db.execute('SELECT id FROM users WHERE name=?', (name,)).fetchone()
        if row is None or row['id'] is None:
            raise LookupError('Unknown player')
        return row['id']

    def update(self, user, changes, games=None):
        current = self.get(user)
        version = max(self.clock(), current['updated'] + 0.000001)
        current.update(changes)
        current.pop('username')
        current.pop('updated')
        with self.db:
            self.db.execute('INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated=excluded.updated',
                            (user, json.dumps(current, ensure_ascii=False), version))
            if games is not None:
                for game in games:
                    previous = self.db.execute('SELECT data FROM profile_games WHERE user_id=? AND uid=?', (user, game['uid'])).fetchone()
                    merged = json.loads(previous['data']) if previous else {}
                    merged.update(game)
                    self.db.execute('INSERT INTO profile_games VALUES(?,?,?) ON CONFLICT(user_id,uid) DO UPDATE SET data=excluded.data',
                                    (user, game['uid'], json.dumps(merged)))
        return version

    def games(self, user):
        result = [json.loads(row['data']) for row in self.db.execute('SELECT data FROM profile_games WHERE user_id=? ORDER BY uid', (user,))]
        for game in result:
            points = self.points(user, game_uid=game['uid'])
            game.update(singlePlayerNGPs=points[0], multiPlayerNGPs=points[1])
        return result

    def points(self, user, game_class=None, *, game_uid=None):
        return self.point_totals(user, game_class, game_uid=game_uid) if self.point_totals else [0, 0, 0]

    def request_friend(self, sender, recipient):
        self.require_user(sender)
        self.require_user(recipient)
        if sender == recipient:
            raise ValueError('Cannot add yourself')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO friendships VALUES(?,?,0,?)', (sender, recipient, self.clock()))

    def accept_friend(self, recipient, sender):
        with self.db:
            changed = self.db.execute('UPDATE friendships SET accepted=1,updated=? WHERE sender=? AND recipient=?',
                                      (self.clock(), sender, recipient))
            if not changed.rowcount:
                raise ValueError('No pending friend request')

    def remove_friend(self, user, other):
        with self.db:
            self.db.execute('DELETE FROM friendships WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)',
                            (user, other, other, user))

    def friends(self, user):
        return [row[0] for row in self.db.execute('''
            SELECT recipient FROM friendships WHERE sender=? AND accepted=1
            UNION SELECT sender FROM friendships WHERE recipient=? AND accepted=1 ORDER BY 1''', (user, user))]


class ProfileService:
    METHODS = {
        'getMiniProfile': 'getminiprofile', 'getProfile': 'getprofile',
        'getFriendsMiniProfiles': 'getfriendsminiprofiles',
        'getFriendsExtendedProfile': 'getFriendsExtendedProfile',
        'updateProfile': 'updateprofile', 'setUserEmailAddress': 'userprofile/',
        'sendPasswordToUser': 'userprofile/',
    }

    def __init__(self, store):
        self.store = store

    def _games(self, parent, user):
        result = element(parent, 'games')
        for data in self.store.games(user):
            game = element(result, 'game')
            for name in ('name', 'uid', 'classId', 'url', 'lastPlayedDate', 'singlePlayerNGPs', 'multiPlayerNGPs'):
                if name in data:
                    element(game, name, data[name])

    def _mini(self, parent, user):
        profile = self.store.get(user)
        result = element(parent, 'miniProfile')
        element(result, 'username', profile['username'])
        element(result, 'iconUrl', profile['iconUrl'])
        ngps = element(result, 'ngps')
        for name, points in zip(POINT_TYPES, self.store.points(user)):
            item = element(ngps, 'ngp')
            element(item, 'type', name)
            element(item, 'score', points)
        self._games(result, user)

    def _profile(self, parent, user):
        profile = self.store.get(user)
        result = element(parent, 'user')
        for name in STRINGS:
            element(result, name, profile[name])
        alerts = element(result, 'alertSubscription')
        for alert in profile['alertSubscription']:
            ET.SubElement(alerts, 'alert', {'name': alert['name'], 'subscribed': 'true' if alert['subscribed'] else 'false'})
        privacy = element(result, 'privacySetting')
        for name in PRIVACY:
            element(privacy, name, profile['privacySetting'][name])
        ignored = element(result, 'ignoreUsersList')
        for name in profile['ignoreUsersList']:
            element(ignored, 'username', name)
        element(result, 'newsLetterSubscription', profile['newsLetterSubscription'])
        element(result, 'username', profile['username'])
        element(result, 'dateOfBirth', profile['dateOfBirth'] or '0001-01-01')
        element(result, 'lastProfileEditDate', timestamp(profile['updated']))
        element(result, 'iconUrl', profile['iconUrl'])
        element(result, 'level', profile['level'])
        element(result, 'reputation', profile['reputation'])

    def _update(self, user, node):
        data = children(node)
        allowed = set(STRINGS) | {'alertSubscription', 'privacySetting', 'ignoreUsersList', 'newsLetterSubscription', 'games', 'userIcon'}
        if set(data) - allowed:
            raise ValueError('Unknown or read-only profile field')
        changes = {name: string(data[name], 1024 if name == 'quote' else 256) for name in STRINGS if name in data}
        if 'privacySetting' in data:
            flags = children(data['privacySetting'])
            if set(flags) != set(PRIVACY):
                raise ValueError('Invalid privacy settings')
            changes['privacySetting'] = {name: boolean(flags[name]) for name in PRIVACY}
        if 'newsLetterSubscription' in data:
            changes['newsLetterSubscription'] = boolean(data['newsLetterSubscription'])
        if 'alertSubscription' in data:
            alerts = []
            for alert in data['alertSubscription']:
                if local(alert.tag) != 'alert' or set(alert.attrib) != {'name', 'subscribed'} or len(alert):
                    raise ValueError('Invalid alert subscription')
                flag = ET.Element('boolean')
                flag.text = alert.get('subscribed')
                kind = alert.get('name')
                if len(kind) > 64 or len(alerts) >= 32:
                    raise ValueError('Invalid alert type')
                alerts.append({'name': kind, 'subscribed': boolean(flag)})
            changes['alertSubscription'] = alerts
        if 'ignoreUsersList' in data:
            ignored = data['ignoreUsersList']
            if len(ignored) > 256 or any(local(item.tag) != 'username' for item in ignored):
                raise ValueError('Invalid ignored users')
            changes['ignoreUsersList'] = list(dict.fromkeys(string(item, 20) for item in ignored))
        if 'userIcon' in data:
            icon = children(data['userIcon'])
            if set(icon) != {'id', 'type'}:
                raise ValueError('Invalid icon')
            changes['userIcon'] = {name: string(icon[name], 128) for name in icon}
        games = None
        if 'games' in data:
            games = []
            for game in data['games']:
                if local(game.tag) != 'game' or len(games) >= 128:
                    raise ValueError('Invalid game list')
                values = children(game)
                if 'uid' not in values or set(values) - {'uid', 'classId', 'name', 'url', 'lastPlayedDate', 'singlePlayerNGPs', 'multiPlayerNGPs'}:
                    raise ValueError('Invalid game record')
                value = {'uid': number(values['uid'], 0xffffffff)}
                for name in ('classId', 'singlePlayerNGPs', 'multiPlayerNGPs'):
                    if name in values:
                        value[name] = number(values[name])
                for name in ('name', 'url'):
                    if name in values:
                        value[name] = string(values[name], 1024)
                if 'lastPlayedDate' in values:
                    value['lastPlayedDate'] = timestamp(parse_timestamp(string(values['lastPlayedDate'], 40)))
                games.append(value)
        return self.store.update(user, changes, games)

    def response(self, body, user):
        if b'<!' in body:
            raise ValueError('Unsupported XML declaration')
        envelope = ET.fromstring(body)
        incoming = envelope.find('{'+SOAP+'}Body')
        if incoming is None or len(incoming) != 1:
            raise ValueError('Expected one SOAP operation')
        operation = incoming[0]
        method = local(operation.tag)
        namespace = NGP + self.METHODS.get(method, 'userprofile/')
        if method not in self.METHODS or operation.tag != '{'+namespace+'}'+method:
            raise ValueError('Unknown profile operation')
        result = ET.Element('{'+namespace+'}'+method+'Response')
        try:
            self.store.require_user(user)
            params = children(operation)
            if method == 'getMiniProfile':
                target = self.store.named(string(params['username'], 20))
                self._mini(result, target)
            elif method == 'getProfile':
                since = parse_timestamp(string(params['lastSynchDate'], 40))
                # Clients can only return the microsecond precision sent on the wire.
                updated = parse_timestamp(timestamp(self.store.get(user)['updated']))
                if updated > since:
                    self._profile(result, user)
            elif method == 'getFriendsMiniProfiles':
                parse_timestamp(string(params['lastSyncDate'], 40))
                friends = element(result, 'friendsMiniProfiles')
                for target in self.store.friends(user):
                    self._mini(friends, target)
                element(friends, 'timestamp', timestamp(self.store.clock()))
            elif method == 'getFriendsExtendedProfile':
                target = self.store.named(string(params['username'], 20))
                if target != user and target not in self.store.friends(user):
                    raise PermissionError('Friendship required')
                profile = self.store.get(target)
                friend = element(result, 'friendProfile')
                for name in ('reputation', 'level'):
                    element(friend, name, profile[name])
                element(friend, 'numberOfFriends', len(self.store.friends(target)) if profile['privacySetting']['displayMyFriendsList'] else 0)
                element(friend, 'quote', profile['quote'])
                element(friend, 'lastLoginDate', '0001-01-01')
                self._games(friend, target)
            elif method == 'updateProfile':
                version = self._update(user, params['user'])
                element(result, 'timeStamp', timestamp(version))
            elif method == 'setUserEmailAddress':
                self.store.update(user, {'email': string(params['emailAddress'])})
            else:
                raise ValueError('Password recovery requires local account administration')
        except (PermissionError, LookupError, ValueError, KeyError, OverflowError) as error:
            result.clear()
            name = 'ngpException' if method == 'getProfile' else 'ngpexception'
            failure = element(result, name)
            element(failure, 'errorCode', 401 if isinstance(error, PermissionError) else 400)
            element(failure, 'errorMsg', str(error))
        reply = ET.Element('{'+SOAP+'}Envelope')
        ET.SubElement(reply, '{'+SOAP+'}Body').append(result)
        return ET.tostring(reply, encoding='utf-8', xml_declaration=True)
