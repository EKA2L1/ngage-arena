import asyncio
import tempfile
import unittest

from arena.accounts import AccountStore
from arena.achievements import AchievementService
from arena.community import CommunityServer
from arena.rankings import UnsupportedRanking
from arena.runtime import default_games


NATIVE_REPORT = (b'<player userName="Angler"><commands g="58600">'
                 b'<add id="35" ts="20260913:141429.3"/></commands></player>')


class AchievementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
        self.owner = self.accounts.create_user('Angler', 'native-test')
        self.peer = self.accounts.create_user('Peer', 'native-test')
        self.service = AchievementService(self.accounts, default_games(self.accounts))

    def tearDown(self):
        self.accounts.close()
        self.directory.cleanup()

    def test_native_report_is_durable_idempotent_and_shared_account_scoped(self):
        self.assertEqual(self.service.response(NATIVE_REPORT, self.owner), b'OK')
        self.service.response(NATIVE_REPORT, self.owner)
        self.service.response(NATIVE_REPORT.replace(b'Angler', b'Peer'), self.peer)
        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        rows = list(self.accounts.db.execute('SELECT * FROM achievements ORDER BY user_id'))
        self.assertEqual([row['user_id'] for row in rows], [self.owner, self.peer])
        self.assertEqual([(r['achievement_id'], r['points'], r['earned']) for r in rows],
                         [(35, 10, '20260913:141429.3')]*2)

    def test_invalid_batch_and_mismatched_accounts_do_not_write(self):
        for user in (None, self.peer):
            with self.assertRaises(PermissionError):
                self.service.response(NATIVE_REPORT, user)
        for body in (
                NATIVE_REPORT.replace(b'id="35"', b'id="38"'),
                NATIVE_REPORT.replace(b'20260913', b'20260230'),
                NATIVE_REPORT.replace(b'<add ', b'<remove '),
                NATIVE_REPORT.replace(b'</commands>', b'<add id="999" ts="20260913:141429.3"/></commands>'),
                NATIVE_REPORT.replace(b'</commands>', b'<add id="35" ts="20260913:141429.3"/></commands>'),
                b'<!DOCTYPE player>'+NATIVE_REPORT):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.service.response(body, self.owner)
        with self.assertRaises(UnsupportedRanking):
            self.service.response(NATIVE_REPORT.replace(b'58600', b'4110'), self.owner)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM achievements').fetchone()[0], 0)


class AchievementHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_only_acknowledges_authenticated_persisted_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            accounts = AccountStore(directory)
            owner = accounts.create_user('Angler', 'native-test')
            server = CommunityServer(accounts, default_games(accounts), local_native_http=True)
            token, session = server.community_session('')
            session.user = owner
            listener = await asyncio.start_server(server.http, '127.0.0.1', 0)
            try:
                for cookie, expected in [('', b'403 Forbidden'),
                                         ('JSESSIONID='+token, b'200 OK')]:
                    reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
                    writer.write((f'POST /ngi/servlets/xmlachievements HTTP/1.1\r\n'
                                  f'Host: localhost\r\nCookie: {cookie}\r\n'
                                  f'Content-Length: {len(NATIVE_REPORT)}\r\n\r\n').encode()+NATIVE_REPORT)
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 2)
                    writer.close()
                    await writer.wait_closed()
                    self.assertTrue(response.startswith(b'HTTP/1.0 '+expected+b'\r\n'))
                    if expected == b'200 OK':
                        self.assertEqual(response.split(b'\r\n\r\n', 1)[1], b'OK')
                self.assertEqual(server.http_sessions, {token: session})
                self.assertEqual(accounts.db.execute('SELECT count(*) FROM achievements').fetchone()[0], 1)
            finally:
                listener.close()
                await listener.wait_closed()
                await server.close()
                accounts.close()
