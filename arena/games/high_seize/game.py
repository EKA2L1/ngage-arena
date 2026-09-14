"""High Seize's native profiles and battle service."""
import re
import xml.etree.ElementTree as ET
from arena.games.high_seize.server import HighSeizeArena, HighSeizeStore
from arena.xmlutil import local


class HighSeizeGame:
    game_class = '36280'

    def __init__(self, accounts):
        self.store = HighSeizeStore(accounts.db)

    def application(self):
        self.store.recover()
        return HighSeizeArena(self.store)

    def retrieve(self, user, node):
        if node.get('id') != 'segachat_retrieve_req' or node.get('to') != 'retrieval36280@ngage-auth':
            raise ValueError('Unknown High Seize retrieval')
        request = next((e.text or '' for e in node.iter() if local(e.tag) == 'request'), '')
        if '<!' in request:
            raise ValueError('Invalid High Seize query')
        params = {item.get('name'): item.get('value') for item in ET.fromstring(request)}
        if (node.get('event_type') != 'getplayer' or params.get('board') != 'player_skills'
                or params.get('skilltype') != 'arena' or params.get('format') != 'csv'):
            raise ValueError('Unsupported High Seize query')
        query = params.get('queryid', '')
        if not re.fullmatch(r'[A-Za-z0-9]{1,32}', query):
            raise ValueError('Invalid query ID')
        player = self.store.profile(params.get('name', ''))
        if player is None:
            raise ValueError('Unknown player')
        return f'0\nOK\n1|{query}|0|0|playerskills|1|0\n0|1|0|0|100|{player["name"]}\n'
