"""Hooked On's native Arena statistics reports."""
import logging
import re
from arena.rankings import ReportStore, UnsupportedRanking, submit_confirmation

LOG = logging.getLogger(__name__)
STATS = {'TOTAL_XP', 'TOTAL_MASS', 'TOTAL_ITEMS', 'TOURNAMENT_SCORE', 'FISH_WEIGHT',
         'LOCATION_ID', 'TOURNAMENT_ID', 'FISH_ID'}
FILTERS = {'LOCATION_ID', 'TOURNAMENT_ID', 'FISH_ID'}


class HookedGame:
    game_class = '58600'
    achievement_points = dict(enumerate(
        [10]*8 + [15]*4 + [20]*4 + [25]*4 + [30] + [40]*4 + [45]*4
        + [50]*5 + [10, 20, 30], start=1))
    achievement_types = {identifier: 1 if identifier <= 34 else 2
                         for identifier in achievement_points}

    def __init__(self, accounts):
        self.reports = ReportStore(accounts.db)

    def rankings(self, user, request):
        if request.operation in ('topn', 'proximitylist'):
            return self.leaderboard(request)
        if request.operation != 'submit':
            raise UnsupportedRanking('Unsupported Hooked On ranking operation')
        if not request.params or not request.params.keys() <= STATS or any(
                not re.fullmatch(r'[0-9]{1,10}', value) or int(value) > 4294967295
                for value in request.params.values()):
            raise ValueError('Invalid Hooked On statistics')
        values = {key: int(value) for key, value in request.params.items()}
        self.reports.append(self.game_class, user, values)
        LOG.info('Hooked On statistics saved for account %d', user)
        return submit_confirmation(request.query_id)

    def leaderboard(self, request):
        params = request.params
        required = {'board', '$matchmakingMode', 'format', 'stat', 'periodicity', 'ordering'}
        required |= {'offset', 'limit'} if request.operation == 'topn' else {'name', 'above', 'below'}
        if (params.keys() != required or params['board'] not in ('hsfilter', 'highscores')
                or params['$matchmakingMode'] != 'none' or params['format'] != 'csv'
                or params['periodicity'] != 'alltime' or params['ordering'] != 'natural'
                or params['stat'] not in STATS - FILTERS):
            raise UnsupportedRanking('Unsupported Hooked On leaderboard')
        if (not request.filters.keys() <= FILTERS
                or (params['board'] == 'highscores' and request.filters)
                or any(not re.fullmatch(r'[0-9]{1,10}', value) or int(value) > 4294967295
                       for value in request.filters.values())):
            raise ValueError('Invalid leaderboard range or filters')
        nearby = {}
        offset, limit = 0, 0
        if request.operation == 'topn':
            if (not re.fullmatch(r'[0-9]{1,7}', params['offset'])
                    or not re.fullmatch(r'[0-9]{1,3}', params['limit'])
                    or not 1 <= int(params['limit']) <= 100):
                raise ValueError('Invalid leaderboard range')
            offset, limit = int(params['offset']), int(params['limit'])
        else:
            if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,20}', params['name'])
                    or any(not re.fullmatch(r'[0-9]{1,3}', params[key]) or int(params[key]) > 100
                           for key in ('above', 'below'))):
                raise ValueError('Invalid nearby ranking query')
            nearby = dict(around=params['name'], above=int(params['above']), below=int(params['below']))
        rows = self.reports.high_scores(self.game_class, params['stat'],
                                       {key: int(value) for key, value in request.filters.items()},
                                       offset, limit, **nearby)
        # The filtered TopN callback derives its row width from the header width minus four.
        header = ['1', request.query_id, request.operation, params['stat'], params['board'],
                  str(len(rows)), str(offset), 'alltime']
        if params['board'] == 'highscores':
            header.pop()
        payload = '0\nOK\n'+'|'.join(header)+'\n'
        payload += ''.join(f'{row["name"]}|{row["rank"]}|{row["score"]}|0\n' for row in rows)
        return payload
