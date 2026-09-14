"""Ashen's nine personal-best leaderboards."""
import logging
import re
import time
import xml.etree.ElementTree as ET
from arena.xmlutil import local

LOG = logging.getLogger(__name__)
STATS = {'game_total', *(f'level_{i}' for i in range(1, 9))}


class ScoreStore:
    def __init__(self, db):
        self.db = db
        db.execute('''CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER NOT NULL REFERENCES users(id), stat TEXT NOT NULL,
            score INTEGER NOT NULL, updated REAL NOT NULL, PRIMARY KEY(user_id,stat))''')

    def submit_scores(self, user, scores):
        if not scores or not scores.keys() <= STATS or any(
                not isinstance(score, int) or not 0 <= score <= 2147483647 for score in scores.values()):
            raise ValueError('Invalid high scores')
        with self.db:
            for stat, score in scores.items():
                self.db.execute('''INSERT INTO scores VALUES(?,?,?,?)
                    ON CONFLICT(user_id,stat) DO UPDATE SET score=excluded.score,updated=excluded.updated
                    WHERE excluded.score>scores.score''', (user, stat, score, time.time()))

    def rankings(self, stat, limit):
        if stat not in STATS or not 1 <= limit <= 10:
            raise ValueError('Invalid leaderboard request')
        return list(self.db.execute('''SELECT users.name,scores.score FROM scores
            JOIN users ON users.id=scores.user_id WHERE stat=?
            ORDER BY score DESC,updated,user_id LIMIT ?''', (stat, limit)))


class AshenGame:
    game_class = '42318'

    def __init__(self, accounts):
        self.scores = ScoreStore(accounts.db)

    def retrieve(self, user, node):
        if node.get('id') == 'segachat_retrieve_req' and node.get('to') == 'retrieval@ngage-auth':
            request = next((element.text or '' for element in node.iter()
                            if local(element.tag) == 'request'), '')
            if '<!' in request:
                raise ValueError('Invalid leaderboard request')
            query = ET.fromstring(request)
            params = {item.get('name'): item.get('value') for item in query}
            if (node.get('event_type') != 'topn' or params.get('board') != 'HIGHSCORES'
                    or params.get('offset') != '0' or params.get('periodicity') != 'alltime'
                    or params.get('ordering') != 'natural' or params.get('format') != 'csv'):
                raise ValueError('Unsupported leaderboard query')
            stat = params.get('stat')
            rows = self.scores.rankings(stat, int(params.get('limit', '0')))
            query_id = params.get('queryid', '')
            if not re.fullmatch(r'[A-Za-z0-9]{1,32}', query_id):
                raise ValueError('Invalid query ID')
            payload = f'0\nOK\n{query_id}|HIGHSCORES|{stat}|{len(rows)}|0|{len(rows)}|alltime\n'
            payload += ''.join(f'{row["name"]}|{i}|{row["score"]}|0\n' for i, row in enumerate(rows, 1))
            LOG.info('SNAP leaderboard %s returned %d records', stat, len(rows))
        elif node.get('id') == 'segachat_send_event' and node.get('to') == 'reporter@ngage-auth' and node.get('event_type') == 'submit':
            scores = {item.get('name'): int(next(iter(item)).text) for item in node}
            self.scores.submit_scores(user, scores)
            payload = '0\nOK\n'
            LOG.info('SNAP saved %d high scores for account %d', len(scores), user)
        else:
            raise ValueError('Unknown SNAP operation')
        return payload
