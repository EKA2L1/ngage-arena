import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.accounts import AccountStore
from arena.community import CommunityServer
from arena.rankings import RankingsService, UnsupportedRanking
from arena.runtime import default_games


NATIVE_SUBMIT = (Path(__file__).parent/'fixtures/hooked-submit.xml').read_bytes()
NATIVE_TOPN = (Path(__file__).parent/'fixtures/hooked-topn.xml').read_bytes()
NATIVE_PROXIMITY = (Path(__file__).parent/'fixtures/hooked-proximity.xml').read_bytes()


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
        self.owner = self.accounts.create_user('Angler', 'native-test')
        self.peer = self.accounts.create_user('Peer', 'native-test')
        self.service = RankingsService(self.accounts, default_games(self.accounts))

    def tearDown(self):
        self.accounts.close()
        self.directory.cleanup()

    def test_native_report_persists_under_the_shared_account(self):
        payload = ET.fromstring(self.service.response(NATIVE_SUBMIT, self.owner))
        self.assertEqual(payload.get('format'), 'csv')
        self.assertEqual(payload.text.splitlines()[:2], ['0', 'OK'])
        fields = payload.text.splitlines()[2].split('|')
        self.assertEqual(len(fields), 6)
        self.assertEqual(fields[1], '5')
        self.assertIn('submit', payload.text)
        self.service.response(NATIVE_SUBMIT.replace(b'Angler', b'Peer'), self.peer)
        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        rows = list(self.accounts.db.execute('SELECT * FROM ranking_reports ORDER BY id'))
        self.assertEqual([row['user_id'] for row in rows], [self.owner, self.peer])
        self.assertEqual([row['game_class'] for row in rows], ['58600', '58600'])
        self.assertEqual(json.loads(rows[0]['payload']), {
            'TOTAL_XP': 0, 'TOURNAMENT_SCORE': 0, 'FISH_WEIGHT': 0,
            'LOCATION_ID': 378939982, 'TOURNAMENT_ID': 0, 'FISH_ID': 0})
        self.assertEqual(self.accounts.authenticate('ANGLER', 'native-test'), self.owner)

    def test_cannot_submit_for_another_or_missing_account(self):
        for user, body in (
                (None, NATIVE_SUBMIT), (self.peer, NATIVE_SUBMIT),
                (self.owner, NATIVE_SUBMIT.replace(b'<player name="Angler"', b'<player name="Peer"')),
                (self.owner, NATIVE_SUBMIT.replace(b'source="jabber:Angler"', b'source="jabber:Peer"'))):
            with self.subTest(user=user, body=body):
                with self.assertRaises(PermissionError):
                    self.service.response(body, user)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_native_segmented_total_weight_and_item_reports(self):
        for stat, query in [('TOTAL_MASS', '7'), ('TOTAL_ITEMS', '9')]:
            root = ET.fromstring(NATIVE_SUBMIT)
            items = root.find('request/itemlist')
            items.clear()
            for key, value in [(stat, '0'), ('$version', '1'), ('queryid', query)]:
                ET.SubElement(items, 'item', name=key, value=value)
            response = ET.fromstring(self.service.response(ET.tostring(root), self.owner))
            self.assertEqual(response.text.splitlines()[2].split('|')[1], query)
        rows = list(self.accounts.db.execute('SELECT payload FROM ranking_reports ORDER BY id'))
        self.assertEqual([json.loads(row[0]) for row in rows], [{'TOTAL_MASS': 0}, {'TOTAL_ITEMS': 0}])

    def test_malformed_report_never_partially_writes(self):
        invalid = [
            NATIVE_SUBMIT.replace(b'TOTAL_XP" value="0"', b'TOTAL_XP" value="-1"'),
            NATIVE_SUBMIT.replace(b'FISH_WEIGHT" value="0"', b'FISH_WEIGHT" value="4294967296"'),
            NATIVE_SUBMIT.replace(b'TOTAL_XP', b'UNRECOGNIZED_STAT'),
            NATIVE_SUBMIT.replace(b'queryid" value="5"', b'queryid" value="5|forged"'),
            NATIVE_SUBMIT.replace(b'</itemlist>', b'<item name="TOTAL_XP" value="1"/></itemlist>'),
            NATIVE_SUBMIT.replace(b'</rankings>', b'<request type="submit"/></rankings>'),
            NATIVE_SUBMIT.replace(b'<request type="submit"', b'<request type="topn"'),
            b'<!DOCTYPE rankings>'+NATIVE_SUBMIT,
        ]
        for body in invalid:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    self.service.response(body, self.owner)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_unknown_game_is_not_accepted_by_another_adapter(self):
        with self.assertRaises(UnsupportedRanking):
            self.service.response(NATIVE_SUBMIT.replace(b'58600', b'42318'), self.owner)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_filtered_leaderboard_uses_each_accounts_best_matching_report(self):
        for user, name, score, location in [
                (self.owner, 'Angler', 100, 378939982),
                (self.owner, 'Angler', 80, 378939982),
                (self.owner, 'Angler', 900, 123),
                (self.peer, 'Peer', 100, 378939982)]:
            report = NATIVE_SUBMIT.replace(b'Angler', name.encode())
            report = report.replace(b'TOTAL_XP" value="0"', f'TOTAL_XP" value="{score}"'.encode())
            report = report.replace(b'378939982', str(location).encode())
            self.service.response(report, user)
        adapter = self.service.games.games['58600']
        rows = adapter.reports.high_scores('58600', 'TOTAL_XP',
                                          {'LOCATION_ID': 378939982, 'TOURNAMENT_ID': 0, 'FISH_ID': 0}, 0, 8)
        self.assertEqual([dict(row) for row in rows], [
            {'name': 'Angler', 'score': 100, 'rank': 1}, {'name': 'Peer', 'score': 100, 'rank': 1}])
        reply = ET.fromstring(self.service.response(NATIVE_TOPN, self.owner)).text.splitlines()
        self.assertEqual(reply[:2], ['0', 'OK'])
        self.assertEqual(len(reply[2].split('|')), 8)
        self.assertEqual(reply[2].split('|')[1], '6')
        self.assertEqual(len(reply[3:]), 2)
        self.assertNotIn('900', '|'.join(reply))
        paged = NATIVE_TOPN.replace(b'offset" value="0"', b'offset" value="1"')
        paged = paged.replace(b'limit" value="8"', b'limit" value="1"')
        page = ET.fromstring(self.service.response(paged, self.owner)).text.splitlines()[3:]
        self.assertEqual(len(page), 1)
        self.assertIn('Peer', page[0])

    def test_empty_and_invalid_filtered_queries_do_not_mutate_scores(self):
        reply = ET.fromstring(self.service.response(NATIVE_TOPN, self.owner)).text.splitlines()
        self.assertEqual(len(reply), 3)
        for body in [
                NATIVE_TOPN.replace(b'LOCATION_ID', b'UNKNOWN_FILTER'),
                NATIVE_TOPN.replace(b'378939982', b'-1'),
                NATIVE_TOPN.replace(b'limit" value="8"', b'limit" value="0"'),
                NATIVE_TOPN.replace(b'limit" value="8"', b'limit" value="101"'),
                NATIVE_TOPN.replace(b'LOCATION_ID" value="378939982"', b'FISH_ID" value="0"'),
                NATIVE_TOPN.replace(b'alltime', b'arbitrary'),
                NATIVE_TOPN.replace(b'<item  name="FISH_ID" value="0"/>',
                                    b'<item name="FISH_ID"><itemlist/></item>')]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.service.response(body, self.owner)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_public_topn_does_not_depend_on_a_readers_identity(self):
        self.service.response(NATIVE_SUBMIT, self.owner)
        expected = self.service.response(NATIVE_TOPN, self.owner)
        self.assertEqual(self.service.response(NATIVE_TOPN, None), expected)
        query = NATIVE_TOPN.replace(b'Angler', b'Visitor')
        self.assertEqual(self.service.response(query, None), expected)
        self.assertEqual(self.service.response(query, self.peer), expected)
        with self.assertRaises(PermissionError):
            self.service.response(NATIVE_SUBMIT, None)

    def test_public_nearby_ranks_center_on_the_requested_player(self):
        third = self.accounts.create_user('Third', 'native-test')
        for user, name, score in [(self.owner, 'Angler', 100), (self.peer, 'Peer', 80), (third, 'Third', 60)]:
            report = NATIVE_SUBMIT.replace(b'Angler', name.encode())
            report = report.replace(b'TOTAL_XP" value="0"', f'TOTAL_XP" value="{score}"'.encode())
            self.service.response(report, user)
        query = NATIVE_PROXIMITY.replace(b'name" value="Angler"', b'name" value="Peer"')
        rows = ET.fromstring(self.service.response(query, None)).text.splitlines()[3:]
        self.assertEqual([row.split('|')[0] for row in rows], ['Angler', 'Peer', 'Third'])
        self.assertEqual([row.split('|')[1] for row in rows], ['1', '2', '3'])
        missing = query.replace(b'name" value="Peer"', b'name" value="Missing"')
        self.assertEqual(len(ET.fromstring(self.service.response(missing, None)).text.splitlines()), 3)
        first = ET.fromstring(self.service.response(NATIVE_PROXIMITY, None)).text.splitlines()[3:]
        self.assertEqual(len(first), 2)
        with self.assertRaises(ValueError):
            self.service.response(query.replace(b'above" value="1"', b'above" value="101"'), None)


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
