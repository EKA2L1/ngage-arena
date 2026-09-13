"""Shared N-Gage point boards derived from persisted achievement reports."""
import re

from arena.achievements import AchievementStore
from arena.rankings import UnsupportedRanking


class PointBoards:
    def __init__(self, accounts, games):
        self.db = AchievementStore(accounts.db, games).db

    def response(self, request):
        params = request.params
        required = {'board', '$matchmakingMode', 'format', 'stat', 'periodicity', 'ordering', 'userList'}
        if request.operation == 'proximitylist':
            required |= {'name', 'above', 'below'}
        elif request.operation == 'topn':
            required |= {'offset', 'limit'}
        else:
            raise UnsupportedRanking('Unsupported point board operation')
        if (params.keys() != required or params['board'] not in ('ngps', 'ngpsglobal')
                or params['$matchmakingMode'] != 'none' or params['format'] != 'csv'
                or params['stat'] or params['userList'] or request.filters
                or params['periodicity'] != 'alltime' or params['ordering'] != 'natural'):
            raise UnsupportedRanking('Unsupported point board query')
        offset = 0
        if request.operation == 'proximitylist':
            if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,20}', params['name'])
                    or any(not re.fullmatch(r'[0-9]{1,3}', params[key]) or int(params[key]) > 100
                           for key in ('above', 'below'))):
                raise ValueError('Invalid nearby point query')
            selection = '''WHERE position BETWEEN
                (SELECT position FROM ranked WHERE name=? COLLATE NOCASE)-? AND
                (SELECT position FROM ranked WHERE name=? COLLATE NOCASE)+? ORDER BY position'''
            values = [params['name'], int(params['above']), params['name'], int(params['below'])]
        else:
            if (not re.fullmatch(r'[0-9]{1,7}', params['offset'])
                    or not re.fullmatch(r'[0-9]{1,3}', params['limit'])
                    or not 1 <= int(params['limit']) <= 100):
                raise ValueError('Invalid point board range')
            offset = int(params['offset'])
            selection = 'ORDER BY position LIMIT ? OFFSET ?'
            values = [int(params['limit']), offset]
        global_board = params['board'] == 'ngpsglobal'
        condition = '' if global_board else ' AND achievements.game_class=?'
        if not global_board:
            values.insert(0, request.game_class)
        rows = list(self.db.execute('''WITH totals AS (
            SELECT users.name,
                COALESCE(SUM(CASE WHEN ngp_type=1 THEN points ELSE 0 END),0) AS single,
                COALESCE(SUM(CASE WHEN ngp_type=2 THEN points ELSE 0 END),0) AS multi
            FROM users LEFT JOIN achievements ON users.id=achievements.user_id'''+condition+'''
            WHERE users.name NOT LIKE '~%' GROUP BY users.id), ranked AS (
            SELECT *,single+multi AS total,
                RANK() OVER (ORDER BY single+multi DESC) AS rank,
                ROW_NUMBER() OVER (ORDER BY single+multi DESC,name COLLATE NOCASE) AS position
            FROM totals)
            SELECT * FROM ranked '''+selection, values))
        payload = f'0\nOK\n1|{request.query_id}|{request.operation}||{params["board"]}|{len(rows)}|{offset}\n'
        for row in rows:
            fields = [row['name'], row['rank'], row['single'], row['multi']]
            if global_board:
                fields.append(0)
            fields.extend([row['total'], 0])
            payload += '|'.join(map(str, fields))+'\n'
        return payload
