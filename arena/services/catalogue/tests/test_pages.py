import asyncio
import tempfile
import struct
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer
from arena.runtime import default_games


NATIVE_PATH = ('/sh/output/frontpage_mcc-_mnc-_device-Nokia%205320d-1_lg-1_shid-0_ngi-1.40.1557'
               '_fw-04.13_hw-RM-409_cmcc-_cmnc-.xhtml')


class CatalogueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AccountStore(self.directory.name)
        self.games = default_games(self.store)
        self.server = CommunityServer(self.store, self.games)
        self.listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)

    async def asyncTearDown(self):
        self.listener.close()
        await self.listener.wait_closed()
        await self.server.close()
        self.store.close()
        self.directory.cleanup()

    async def request(self, path=NATIVE_PATH, method='GET', host='showroom.n-gage.com'):
        reader, writer = await asyncio.open_connection(*self.listener.sockets[0].getsockname())
        try:
            writer.write((f'{method} {path} HTTP/1.0\r\nHost: {host}\r\n\r\n').encode())
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 2)
            head, body = raw.split(b'\r\n\r\n', 1)
            lines = head.decode().split('\r\n')
            return lines[0], dict(line.split(': ', 1) for line in lines[1:]), body
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_native_frontpage_lists_registered_ngage_two_games(self):
        self.games.games['123'] = SimpleNamespace(app_uid=123, game_class='123', title='One & Two')
        status, headers, body = await self.request()
        self.assertEqual(status, 'HTTP/1.0 200 OK')
        self.assertEqual(int(headers['Content-Length']), len(body))
        root = ET.fromstring(body)
        ns = {'h': 'http://www.w3.org/1999/xhtml'}
        titles = [item.text for item in root.findall('.//h:h2', ns)]
        self.assertEqual(titles, ['Hooked On: Creatures of the Deep', 'One & Two'])
        links = [item.get('href') for item in root.findall('.//h:a', ns)]
        self.assertEqual(links, ['http://showroom.n-gage.com/rankings.html?GCID=58600',
                                 'http://showroom.n-gage.com/rankings.html?GCID=123'])
        for link in links:
            parsed = urlsplit(link)
            self.assertEqual((await self.request(parsed.path+'?'+parsed.query))[0], 'HTTP/1.0 200 OK')
        self.assertEqual(self.server.http_sessions, {})
        self.assertNotIn('Set-Cookie', headers)

    async def test_cached_page_links_preserve_the_origin_and_reject_bad_hosts(self):
        _, _, body = await self.request(host='showroom.n-gage.com:8192')
        self.assertIn(b'http://showroom.n-gage.com:8192/rankings.html?GCID=58600', body)
        for host in ('user@server', 'server/elsewhere', 'server:0', 'server:65536', 'server"onclick="x'):
            self.assertEqual((await self.request(host=host))[0], 'HTTP/1.0 400 Bad Request')

    async def test_head_matches_get_without_body(self):
        _, get_headers, body = await self.request()
        status, head_headers, empty = await self.request(method='HEAD')
        self.assertEqual(status, 'HTTP/1.0 200 OK')
        self.assertEqual(head_headers, get_headers)
        self.assertEqual(empty, b'')
        self.assertGreater(len(body), 0)

    async def test_native_companion_movie_is_an_original_complete_swf(self):
        path = NATIVE_PATH.replace('.xhtml', '.swf')
        status, headers, body = await self.request(path)
        self.assertEqual(status, 'HTTP/1.0 200 OK')
        self.assertEqual(headers['Content-Type'], 'application/x-shockwave-flash')
        self.assertEqual(body[:4], b'FWS\x06')
        self.assertEqual(struct.unpack_from('<I', body, 4)[0], len(body))
        self.assertTrue(body.endswith(b'\x40\x00\x00\x00'))
        _, head_headers, empty = await self.request(path, 'HEAD')
        self.assertEqual(head_headers, headers)
        self.assertEqual(empty, b'')

    async def test_featured_game_metadata_matches_the_downloaded_icon(self):
        prefix = NATIVE_PATH.replace('frontpage_', 'featuredGame_').removesuffix('.xhtml')
        status, headers, body = await self.request(prefix+'.txt')
        self.assertEqual(status, 'HTTP/1.0 200 OK')
        self.assertEqual(headers['Content-Type'], 'text/plain; charset=utf-16')
        fields = body.decode('utf-16').splitlines()
        self.assertEqual(len(fields), 4)
        self.assertEqual(fields[0], 'Hooked On: Creatures of the Deep')
        self.assertRegex(fields[2], r'^\d{2}/\d{2}/\d{4}$')
        self.assertEqual(fields[3], '58600')
        status, headers, body = await self.request(prefix+'.png')
        self.assertEqual(status, 'HTTP/1.0 200 OK')
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(body[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', body[16:24]), (56, 56))

    async def test_unknown_paths_and_write_methods_do_not_return_a_fake_catalogue(self):
        for path in ('/sh/output/unknown.swf', '/sh/output/../config.yml',
                     '/sh/output/frontpage_%3Cscript%3E.xhtml', '/sh/output/frontpage_'+('x'*2100)+'.xhtml'):
            with self.subTest(path=path):
                status, _, body = await self.request(path)
                self.assertEqual(status, 'HTTP/1.0 400 Bad Request')
                self.assertNotIn(b'<h1>', body)
        status, headers, _ = await self.request(method='POST')
        self.assertEqual(status, 'HTTP/1.0 405 Method Not Allowed')
        self.assertEqual(headers['Allow'], 'GET, HEAD')
