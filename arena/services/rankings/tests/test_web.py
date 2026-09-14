import asyncio
from html import unescape
import re
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer
from arena.runtime import default_games


NATIVE_URL = '/rankings.html?CC=000&NETID=000&GCID=58600&USERNAME=Angler&LANG=1&CMP=MOB-ranking01'


class RankingWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AccountStore(self.directory.name)
        self.games = default_games(self.store)
        self.games.games['123'] = SimpleNamespace(game_class='123', app_uid=123,
            achievement_points={1: 40}, achievement_types={1: 1})
        self.server = CommunityServer(self.store, self.games)
        self.listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        self.owner = self.store.create_user('Angler', 'native-test')
        self.peer = self.store.create_user('Peer', 'native-test')

    async def asyncTearDown(self):
        self.listener.close()
        await self.listener.wait_closed()
        await self.server.close()
        self.store.close()
        self.directory.cleanup()

    def award(self, user, identifier, game='58600'):
        name = self.store.name(user)
        self.server.achievements.response((f'<player userName="{name}"><commands g="{game}">'
            f'<add id="{identifier}" ts="20260913:141429.3"/></commands></player>').encode(), user)

    async def request(self, url=NATIVE_URL, method='GET', cookie=''):
        reader, writer = await asyncio.open_connection(*self.listener.sockets[0].getsockname())
        try:
            writer.write((f'{method} {url} HTTP/1.1\r\nHost: playapps.ngage.mobi\r\n'
                          f'Cookie: {cookie}\r\nContent-Length: 0\r\n\r\n').encode())
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 2)
            header, body = raw.split(b'\r\n\r\n', 1)
            lines = header.decode().split('\r\n')
            return lines[0], dict(line.split(': ', 1) for line in lines[1:]), body
        finally:
            writer.close()
            await writer.wait_closed()

    def rows(self, body):
        root = ET.fromstring(body.replace(b'&middot;', b'&#183;'))
        ns = {'h': 'http://www.w3.org/1999/xhtml'}
        return [[cell.text for cell in row.findall('h:td', ns)]
                for row in root.findall('.//h:tr', ns)][1:]

    async def test_public_game_and_global_pages_use_the_shared_earned_ledger(self):
        self.award(self.owner, 35)
        self.award(self.owner, 1, '123')
        self.award(self.peer, 36)
        status, headers, body = await self.request()
        self.assertEqual(status, 'HTTP/1.0 200 OK')
        self.assertEqual(int(headers['Content-Length']), len(body))
        self.assertIn(b'Hooked On: Creatures of the Deep', body)
        self.assertEqual(self.rows(body), [['1', 'Peer', '20'], ['2', 'Angler', '10']])
        _, _, global_body = await self.request(NATIVE_URL.replace('GCID=58600', 'GCID=4444'))
        self.assertEqual(self.rows(global_body), [['1', 'Angler', '50'], ['2', 'Peer', '20']])
        self.assertIn(b'class="self"', body)
        self.assertEqual(self.server.http_sessions, {})
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM ranking_reports').fetchone()[0], 0)

    async def test_head_and_cookies_do_not_create_or_extend_sessions(self):
        token, session = self.server.community_session('')
        expires = session.expires
        self.server.clock = lambda: expires+1
        for cookie in ('', 'JSESSIONID=unknown', 'JSESSIONID='+token):
            _, get_headers, body = await self.request(cookie=cookie)
            status, head_headers, empty = await self.request(method='HEAD', cookie=cookie)
            self.assertEqual(status, 'HTTP/1.0 200 OK')
            self.assertEqual(get_headers, head_headers)
            self.assertEqual(int(head_headers['Content-Length']), len(body))
            self.assertEqual(empty, b'')
            self.assertNotIn('Set-Cookie', get_headers)
            self.assertEqual(self.server.http_sessions, {token: session})
            self.assertEqual(session.expires, expires)

    async def test_pagination_preserves_scope_and_competition_ties(self):
        for index in range(10):
            self.store.create_user(f'Player{index}', 'native-test')
        self.store.register_identity('airplay', 'unlinked')
        _, _, body = await self.request()
        first = self.rows(body)
        self.assertEqual(len(first), 10)
        self.assertTrue(all(row[0] == '1' for row in first))
        link = unescape(re.search(rb'href="([^"]+)">Next', body)[1].decode())
        self.assertIn('GCID=58600', link)
        _, _, body = await self.request(link)
        second = self.rows(body)
        self.assertEqual(len(second), 2)
        self.assertTrue(all(row[0] == '1' for row in second))
        self.assertEqual(len({row[1] for row in first+second}), 12)
        self.assertIn(b'>Previous</a>', body)
        self.assertNotIn(b'>Next</a>', body)

    async def test_bad_queries_and_write_methods_are_rejected_without_reflection(self):
        for url in ('/rankings.html?GCID=one', '/rankings.html?GCID=1&GCID=2',
                    '/rankings.html?offset=-1', '/rankings.html?offset=10000000',
                    '/rankings.html?'+('x=1&'*20), '/rankings.html?x='+('a'*2048)):
            with self.subTest(url=url):
                status, _, _ = await self.request(url)
                self.assertEqual(status, 'HTTP/1.0 400 Bad Request')
        status, headers, _ = await self.request(method='POST')
        self.assertEqual(status, 'HTTP/1.0 405 Method Not Allowed')
        self.assertEqual(headers['Allow'], 'GET, HEAD')
        _, _, body = await self.request(NATIVE_URL.replace('USERNAME=Angler', 'USERNAME=%3Cscript%3E'))
        self.assertNotIn(b'<script>', body)
        self.assertEqual(self.server.http_sessions, {})
