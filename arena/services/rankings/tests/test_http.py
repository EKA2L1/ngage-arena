import asyncio
import hashlib
import tempfile
import unittest

from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer
from arena.runtime import default_games


from arena.games.hooked.tests.fixtures import NATIVE_SUBMIT, NATIVE_TOPN

class RankingHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_anonymous_http_reads_neither_create_sessions_nor_authorize_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            accounts = AccountStore(directory)
            owner = accounts.create_user('Angler', 'native-test')
            server = CommunityServer(accounts, default_games(accounts))
            server.rankings.response(NATIVE_SUBMIT, owner)
            listener = await asyncio.start_server(server.http, '127.0.0.1', 0)
            try:
                for route, body, expected in [
                        ('rankings', NATIVE_TOPN, b'200 OK'),
                        ('rankings', NATIVE_SUBMIT, b'403 Forbidden'),
                        ('xmlachievements', b'<player userName="Angler"><commands g="58600">'
                         b'<add id="35" ts="20260913:141429.3"/></commands></player>', b'403 Forbidden')]:
                    reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
                    writer.write((f'POST /ngi/servlets/{route} HTTP/1.1\r\nHost: localhost\r\n'
                                  f'Content-Length: {len(body)}\r\n\r\n').encode()+body)
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 2)
                    writer.close()
                    await writer.wait_closed()
                    self.assertTrue(response.startswith(b'HTTP/1.0 '+expected+b'\r\n'))
                    self.assertNotIn(b'Set-Cookie:', response)
                    if expected == b'200 OK':
                        self.assertIn(b'Angler', response)
                self.assertEqual(server.http_sessions, {})
                self.assertEqual(accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 1)
                self.assertEqual(accounts.db.execute('SELECT count(*) FROM achievements').fetchone()[0], 0)
            finally:
                listener.close()
                await listener.wait_closed()
                await server.close()
                accounts.close()

    async def test_local_native_http_requires_a_live_matching_snap_login(self):
        with tempfile.TemporaryDirectory() as directory:
            accounts = AccountStore(directory)
            owner = accounts.create_user('Angler', 'native-test')
            server = CommunityServer(accounts, default_games(accounts), local_native_http=True)
            listener = await asyncio.start_server(server.xmpp, '127.0.0.1', 0)
            http = await asyncio.start_server(server.http, '127.0.0.1', 0)
            client_writer = None
            try:
                self.assertIsNone(server.local_game_user(NATIVE_SUBMIT, '127.0.0.1'))
                reader, client_writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
                proof = hashlib.sha1(b'native-test').hexdigest()
                client_writer.write((
                    '<stream:stream xmlns="jabber:client" xmlns:stream="http://etherx.jabber.org/streams">'
                    '<iq type="set" id="login"><query xmlns="jabber:iq:auth"><username>Angler</username>'
                    f'<password>{proof}</password><resource>game</resource></query></iq>').encode())
                await client_writer.drain()
                response = await asyncio.wait_for(reader.readuntil(b'/>'), 2)
                self.assertIn(b'type="result"', response)
                self.assertEqual(server.local_game_user(NATIVE_SUBMIT, '127.0.0.1'), owner)
                achievement = b'<player userName="Angler"><commands g="58600"/></player>'
                self.assertEqual(server.local_game_user(achievement, '127.0.0.1'), owner)
                for route, body in [
                        ('rankings', NATIVE_SUBMIT), ('rankings', NATIVE_SUBMIT),
                        ('xmlachievements', achievement.replace(
                            b'<commands g="58600"/>',
                            b'<commands g="58600"><add id="35" ts="20260913:141429.3"/></commands>'))]:
                    http_reader, http_writer = await asyncio.open_connection(*http.sockets[0].getsockname())
                    http_writer.write((f'POST /ngi/servlets/{route} HTTP/1.1\r\nHost: localhost\r\n'
                                       f'Content-Length: {len(body)}\r\n\r\n').encode()+body)
                    await http_writer.drain()
                    reply = await asyncio.wait_for(http_reader.read(), 2)
                    http_writer.close()
                    await http_writer.wait_closed()
                    self.assertTrue(reply.startswith(b'HTTP/1.0 200 OK\r\n'))
                    self.assertNotIn(b'Set-Cookie:', reply)
                self.assertEqual(server.http_sessions, {})
                self.assertEqual(accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 2)
                self.assertEqual(accounts.db.execute('SELECT points FROM achievements').fetchone()[0], 10)
                self.assertIsNone(server.local_game_user(NATIVE_SUBMIT.replace(b'Angler', b'Peer'), '127.0.0.1'))
                self.assertIsNone(server.local_game_user(NATIVE_SUBMIT, '192.0.2.1'))
                server.local_native_http = False
                self.assertIsNone(server.local_game_user(NATIVE_SUBMIT, '127.0.0.1'))
                self.assertIsNone(server.local_game_user(achievement, '127.0.0.1'))
                server.local_native_http = True
                handlers = tuple(server.tasks)
                client_writer.close()
                await client_writer.wait_closed()
                client_writer = None
                await asyncio.wait_for(asyncio.gather(*handlers), 2)
                self.assertIsNone(server.local_game_user(NATIVE_SUBMIT, '127.0.0.1'))
            finally:
                if client_writer:
                    client_writer.close()
                    await client_writer.wait_closed()
                listener.close()
                await listener.wait_closed()
                http.close()
                await http.wait_closed()
                await server.close()
                accounts.close()

    async def test_native_cookie_and_matrix_transport_require_authenticated_session(self):
        with tempfile.TemporaryDirectory() as directory:
            accounts = AccountStore(directory)
            owner = accounts.create_user('Angler', 'native-test')
            server = CommunityServer(accounts, default_games(accounts))
            token, session = server.community_session('')
            session.user = owner
            listener = await asyncio.start_server(server.http, '127.0.0.1', 0)
            try:
                for cookie, matrix, expected in (
                        ('', '', b'403 Forbidden'),
                        ('JSESSIONID=unknown', '', b'403 Forbidden'),
                        ('JSESSIONID='+token, '', b'200 OK'),
                        ('', ';jsessionid='+token, b'200 OK')):
                    reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
                    request = (f'POST /ngi/servlets/rankings{matrix} HTTP/1.1\r\n'
                               f'Host: localhost\r\nCookie: {cookie}\r\n'
                               f'Content-Length: {len(NATIVE_SUBMIT)}\r\n\r\n').encode()+NATIVE_SUBMIT
                    writer.write(request)
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 2)
                    writer.close()
                    await writer.wait_closed()
                    self.assertTrue(response.startswith(b'HTTP/1.0 '+expected+b'\r\n'))
                    if expected == b'200 OK':
                        self.assertIn(b'<data format="csv">', response)
                self.assertEqual(server.http_sessions, {token: session})
                rows = list(accounts.db.execute('SELECT user_id FROM ranking_reports'))
                self.assertEqual([row[0] for row in rows], [owner, owner])
            finally:
                listener.close()
                await listener.wait_closed()
                await server.close()
                accounts.close()
