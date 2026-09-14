"""Original XHTML content for the Launcher's showroom downloader."""
from html import escape
from datetime import date
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


class CataloguePages:
    prefix = '/sh/output/'

    def __init__(self, games):
        self.games = games

    def content_type(self, url):
        return {'.swf': 'application/x-shockwave-flash', '.png': 'image/png',
                '.txt': 'text/plain; charset=utf-16'}.get(
                    Path(urlsplit(url).path).suffix, 'text/html; charset=utf-8')

    def render(self, url, authority='showroom.n-gage.com', secure=False):
        host = urlsplit('//'+authority)
        if (not host.hostname or host.username is not None or host.password is not None
                or host.path or host.query or host.fragment
                or not re.fullmatch(r'[A-Za-z0-9.\-:\[\]]+', authority)
                or (host.port is not None and not 1 <= host.port <= 65535)):
            raise ValueError('Invalid catalogue authority')
        origin = ('https://' if secure else 'http://')+authority
        path = unquote(urlsplit(url).path)
        match = re.fullmatch(r'/sh/output/(frontpage|featuredGame)'
                             r'(?:_[A-Za-z0-9 ._-]{1,512})?\.(xhtml|swf|png|txt)', path)
        if len(url) > 2048 or not match or (match[1], match[2]) not in {
                ('frontpage', 'xhtml'), ('frontpage', 'swf'),
                ('featuredGame', 'png'), ('featuredGame', 'txt')}:
            raise ValueError('Unknown catalogue page')
        assets = Path(__file__).with_name('assets')
        if path.endswith('.swf'):
            return (assets/'frontpage.swf').read_bytes()
        if path.endswith('.png'):
            return (assets/'arena.png').read_bytes()
        games = [game for game in self.games.games.values()
                 if getattr(game, 'app_uid', None) and getattr(game, 'title', None)]
        if path.endswith('.txt'):
            game = games[0] if games else None
            fields = [game.title if game else 'Arena games',
                      getattr(game, 'summary', 'Launch installed games from My Games.'),
                      date.today().strftime('%d/%m/%Y'), game.game_class if game else '0']
            return ('\n'.join(fields)+'\n').encode('utf-16')
        entries = []
        for game in games:
            # The Launcher renders its downloaded XHTML from a local file.
            entries.append('<h2>'+escape(game.title)+'</h2><p><a href="'+origin+'/rankings.html?GCID='
                           +escape(game.game_class, quote=True)+'">View Arena rankings</a></p>')
        return ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
                '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />'
                '<title>N-Gage Arena games</title><style type="text/css">'
                'body{margin:8px;background:#fff;color:#333;font:12px sans-serif}'
                'h1{font-size:18px;color:#c70}h2{font-size:14px}a{color:#950}'
                '</style></head><body><h1>Arena games</h1><p>Play together on this server.</p>'
                +(''.join(entries) or '<p>No games are listed yet.</p>')
                +'<p>Launch installed games from My Games.</p></body></html>').encode()
