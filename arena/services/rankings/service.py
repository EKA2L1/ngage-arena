"""N-Gage 2.0 ranking requests, account authorization and report persistence."""
from dataclasses import dataclass, field
import json
import re
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


class UnsupportedRanking(ValueError):
    pass


PUBLIC_READS = {'topn', 'getplayer', 'proximitylist'}


@dataclass(frozen=True)
class RankingRequest:
    operation: str
    game_class: str
    query_id: str
    params: dict
    filters: dict = field(default_factory=dict)


class ReportStore:
    def __init__(self, db):
        self.db = db
        db.execute('''CREATE TABLE IF NOT EXISTS ranking_reports (
            id INTEGER PRIMARY KEY, game_class TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id), received REAL NOT NULL,
            payload TEXT NOT NULL)''')

    def append(self, game_class, user, values):
        with self.db:
            return self.db.execute('''INSERT INTO ranking_reports(game_class,user_id,received,payload)
                VALUES(?,?,?,?)''', (game_class, user, time.time(),
                                    json.dumps(values, sort_keys=True, separators=(',', ':')))).lastrowid

    def high_scores(self, game_class, stat, filters, offset, limit, *, around=None, above=0, below=0):
        conditions = ['game_class=?', 'json_type(payload,?)="integer"']
        arguments = [game_class, '$.'+stat]
        for key, value in filters.items():
            conditions.append('json_extract(payload,?)=?')
            arguments.extend(['$.'+key, value])
        query = '''WITH reports AS (
            SELECT user_id,json_extract(payload,?) AS score FROM ranking_reports WHERE '''
        query += ' AND '.join(conditions)
        query += '''), best AS (
            SELECT user_id,MAX(score) AS score FROM reports GROUP BY user_id), ranked AS (
            SELECT users.name,best.score,RANK() OVER (ORDER BY best.score DESC) AS rank,
                ROW_NUMBER() OVER (ORDER BY best.score DESC,users.name COLLATE NOCASE) AS position
            FROM best JOIN users ON users.id=best.user_id)
            SELECT name,score,rank FROM ranked'''
        if around is not None:
            query += ''' WHERE position BETWEEN
                (SELECT position FROM ranked WHERE name=? COLLATE NOCASE)-? AND
                (SELECT position FROM ranked WHERE name=? COLLATE NOCASE)+? ORDER BY position'''
            arguments.extend([around, above, around, below])
        else:
            query += ' ORDER BY position LIMIT ? OFFSET ?'
            arguments.extend([limit, offset])
        return list(self.db.execute(query, ['$.'+stat, *arguments]))


class RankingsService:
    def __init__(self, accounts, games):
        self.accounts = accounts
        self.games = games
        from arena.services.rankings.points import PointBoards
        self.points = PointBoards(accounts, games)

    def response(self, body, user):
        if b'<!' in body:
            raise ValueError('Unsupported XML declaration')
        root = ET.fromstring(body)
        if root.tag != 'rankings' or len(root) != 1 or root[0].tag != 'request':
            raise ValueError('Expected one ranking request')
        node = root[0]
        operation = node.get('type', '')
        if operation != root.get('EventType'):
            raise ValueError('Mismatched ranking operation')
        name = self.accounts.name(user) if user is not None else None
        if operation not in PUBLIC_READS:
            if name is None:
                raise PermissionError('Login required')
            if (root.get('name', '').casefold() != name.casefold()
                    or root.get('source', '').casefold() != ('jabber:'+name).casefold()):
                raise PermissionError('Account mismatch')
        children = {tag: node.findall(tag) for tag in ('gameinfo', 'itemlist', 'playerlist')}
        if (len(children['gameinfo']) != 1 or len(children['itemlist']) != 1
                or len(children['playerlist']) > 1 or sum(map(len, children.values())) != len(node)):
            raise ValueError('Invalid ranking request fields')
        game_class = children['gameinfo'][0].get('gameclassid', '')
        if not re.fullmatch(r'[0-9]{1,10}', game_class):
            raise ValueError('Invalid game class')
        params = {}
        filters = {}
        items = children['itemlist'][0]
        if not 1 <= len(items) <= 64:
            raise ValueError('Invalid ranking parameter count')
        for item in items:
            key, value = item.get('name'), item.get('value')
            if key == 'filters':
                if (operation == 'submit' or item.tag != 'item' or filters or len(item) != 1
                        or item[0].tag != 'itemlist' or not 1 <= len(item[0]) <= 16 or value is not None):
                    raise ValueError('Invalid ranking filters')
                for entry in item[0]:
                    filter_name, value = entry.get('name'), entry.get('value')
                    if (entry.tag != 'item' or len(entry) or not filter_name or len(filter_name) > 64
                            or value is None or len(value) > 1024 or filter_name in filters):
                        raise ValueError('Invalid ranking filter')
                    filters[filter_name] = value
                continue
            if (item.tag != 'item' or len(item) or not key or value is None
                    or key in params or len(key) > 64 or len(value) > 1024):
                raise ValueError('Invalid ranking parameter')
            params[key] = value
        if params.pop('$version', None) != '1':
            raise ValueError('Unsupported ranking version')
        query_id = params.pop('queryid', '')
        if not re.fullmatch(r'[0-9]{1,10}', query_id) or int(query_id) > 2147483647:
            raise ValueError('Invalid ranking query ID')
        if operation == 'submit':
            players = children['playerlist']
            if (len(players) != 1 or len(players[0]) != 1 or players[0][0].tag != 'player'
                    or players[0][0].get('name', '').casefold() != name.casefold()):
                raise PermissionError('Scores must belong to the authenticated account')
        request = RankingRequest(operation, game_class, query_id, params, filters)
        if request.params.get('board') in ('ngps', 'ngpsglobal'):
            payload = self.points.response(request)
        else:
            payload = self.games.rankings(user, request)
        return ('<data format="csv">'+escape(payload)+'</data>').encode()


def submit_confirmation(query_id):
    # NAFRanking_V3 requires six columns, with the numeric query ID in the second column.
    return f'0\nOK\n1|{query_id}|0|0|submit|0\n'
