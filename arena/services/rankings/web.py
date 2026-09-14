"""Public point rankings for the Launcher's embedded browser."""
from html import escape
import re
from urllib.parse import parse_qsl, urlencode, urlsplit


class RankingPages:
    path = '/rankings.html'

    def __init__(self, points, games):
        self.points = points
        self.games = games

    def render(self, url):
        if len(url) > 2048:
            raise ValueError('Ranking URL is too long')
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True, max_num_fields=16)
        params = dict(pairs)
        if len(params) != len(pairs):
            raise ValueError('Duplicate ranking parameters')
        game_class = params.get('GCID', '4444')
        offset = params.get('offset', '0')
        if not re.fullmatch(r'[0-9]{1,10}', game_class) or not re.fullmatch(r'[0-9]{1,7}', offset):
            raise ValueError('Invalid ranking scope or range')
        game_class = str(int(game_class))
        scope = None if game_class in ('0', '4444') else game_class
        offset = int(offset)
        rows = self.points.top(scope, offset=offset, limit=11)
        game = self.games.games.get(scope)
        title = 'N-Gage Points' if scope is None else getattr(game, 'title', 'Game Points')
        username = params.get('USERNAME', '').casefold()
        body = '<h1>Rankings</h1><h2>'+escape(title)+'</h2>'
        body += '<p>All time &middot; '+('All games' if scope is None else 'Game points')+'</p>'
        body += '<table><tr><th>#</th><th>Player</th><th>Points</th></tr>'
        for row in rows[:10]:
            css = ' class="self"' if row['name'].casefold() == username else ''
            body += ('<tr'+css+'><td>'+str(row['rank'])+'</td><td>'+escape(row['name'])
                     +'</td><td>'+str(row['total'])+'</td></tr>')
        body += '</table>'
        if not rows:
            body += '<p>No players on this page.</p>'
        links = []
        for label, start in [('Previous', offset-10), ('Next', offset+10)]:
            if (label == 'Previous' and start >= 0) or (label == 'Next' and len(rows) > 10):
                query = urlencode({**params, 'offset': str(start)})
                links.append('<a href="'+escape(self.path+'?'+query, quote=True)+'">'+label+'</a>')
        body += '<p>'+' | '.join(links)+'</p>'
        return ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
                '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />'
                '<title>Rankings</title><style type="text/css">'
                'body{margin:8px;background:#fff;color:#333;font:12px sans-serif}'
                'h1{font-size:18px;color:#c70;margin:0 0 6px}h2{font-size:14px;margin:0}'
                'table{width:100%;border-collapse:collapse}th{text-align:left}'
                'td,th{padding:5px 2px;border-bottom:1px solid #ddd}'
                '.self{background:#fff0ce}a{color:#950}'
                '</style></head><body>'+body+'</body></html>').encode()
