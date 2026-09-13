import asyncio
import hashlib
from http.cookies import SimpleCookie
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.ashen import AshenServer, AshenStore, SOAP


def community(method, **params):
    root = ET.Element('{'+SOAP+'}Envelope')
    operation = ET.SubElement(ET.SubElement(root, '{'+SOAP+'}Body'), '{urn:CommunityApp}'+method)
    for key, value in params.items():
        ET.SubElement(operation, key).text = value
    return ET.tostring(root)


def leaderboard(stat='game_total'):
    # Native Ashen's request asks for a seven-row, all-time leaderboard.
    node = ET.fromstring('<message to="retrieval@ngage-auth" id="segachat_retrieve_req" event_type="topn" game_class_id="42318" snap_name="forged"/>')
    request = ET.Element('itemlist')
    for key, value in dict(queryid='3dabc', board='HIGHSCORES', stat=stat, offset='0', limit='7',
                           periodicity='alltime', ordering='natural', format='csv').items():
        ET.SubElement(request, 'item', name=key, value=value)
    ET.SubElement(ET.SubElement(node, 'retrieve'), 'request').text = ET.tostring(request, encoding='unicode')
    return node


class AshenTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AshenStore(self.directory.name)
        self.server = AshenServer(self.store)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_native_registration_login_and_restart(self):
        response = self.server.soap_response(community('createUser', username='Ashen', password='native-test'))
        self.assertIn(b'createUserResponse', response)
        self.assertIn(b'Fault', self.server.soap_response(community('createUser', username='ashen', password='other')))
        self.store.close()
        self.store = AshenStore(self.directory.name)
        self.server = AshenServer(self.store)
        uid = self.store.authenticate('ASHEN', 'native-test')
        self.assertIsNotNone(uid)
        self.assertEqual(self.store.authenticate_snap('ashen', hashlib.sha1(b'native-test').hexdigest()), uid)
        self.assertIsNone(self.store.authenticate_snap('ashen', 'native-test'))
        self.assertIsNone(self.store.authenticate('ashen', 'wrong'))
        self.assertNotIn(b'native-test', (Path(self.directory.name)/'community.sqlite3').read_bytes())

    def test_native_score_submission_rankings_and_identity(self):
        uid = self.store.create_user('PlayerOne', 'one')
        second = self.store.create_user('PlayerTwo', 'two')
        self.assertIn('3dabc|HIGHSCORES|game_total|0|', self.server.snap_response(uid, leaderboard()))
        submit = ET.fromstring('<message to="reporter@ngage-auth" id="segachat_send_event" event_type="submit" game_class_id="42318" snap_name="PlayerTwo"><item name="game_total"><value>1200</value></item><item name="level_1"><value>1200</value></item></message>')
        self.assertIn('0\nOK', self.server.snap_response(uid, submit))
        self.store.submit_scores(uid, {'game_total': 1000})
        self.store.submit_scores(second, {'game_total': 1300})
        response = ET.fromstring(self.server.snap_response(uid, leaderboard()))
        self.assertEqual(response.findtext('retrieve/response').splitlines(), [
            '0', 'OK', '3dabc|HIGHSCORES|game_total|2|0|2|alltime',
            'PlayerTwo|1|1300|0', 'PlayerOne|2|1200|0'])
        self.assertIn('Login required', self.server.snap_response(None, submit))
        self.assertIn('Invalid leaderboard', self.server.snap_response(uid, leaderboard('level_9')))
        with self.assertRaises(ValueError):
            self.store.submit_scores(uid, {'level_1': -1})

    def test_high_seize_authentication_returns_typed_snap_username(self):
        self.store.create_user('HighSeize', 'native-test')
        for password, expected in [('native-test', ['true', 'HighSeize']), ('wrong', ['false', None])]:
            response = ET.fromstring(self.server.soap_response(community(
                'authenticateUser2', username='highseize', password=password)))
            result = response.find('.//{urn:CommunityApp}authenticateUser2Return')
            self.assertEqual([item.text for item in result], expected)
            self.assertEqual([item.get('{http://www.w3.org/2001/XMLSchema-instance}type') for item in result],
                             ['xsd:boolean', 'xsd:string'])

    def test_ngi_authentication_uses_status_array_and_clears_failed_sessions(self):
        uid = self.store.create_user('Launcher', 'native-test')
        _, session = self.server.community_session('')
        for password, expected, account in [('native-test', ['0', 'Launcher'], uid), ('wrong', ['1', None], None)]:
            response = ET.fromstring(self.server.soap_response(community(
                'authenticateUser', username='launcher', password=password), session, ngi=True))
            result = response.find('.//{urn:CommunityApp}authenticateUserReturn')
            self.assertEqual([item.text for item in result], expected)
            self.assertEqual(session.user, account)

    def test_high_seize_native_profile_returns_the_requested_account(self):
        user = self.store.create_user('Host', 'one')
        self.store.create_user('Peer', 'two')
        node = ET.fromstring('<message to="retrieval36280@ngage-auth" id="segachat_retrieve_req" event_type="getplayer" game_class_id="36280"/>')
        query = ET.Element('itemlist')
        for key, value in dict(board='player_skills', skilltype='arena', format='csv', queryid='1', name='peer').items():
            ET.SubElement(query, 'item', name=key, value=value)
        request = ET.SubElement(ET.SubElement(node, 'retrieve'), 'request')
        request.text = ET.tostring(query, encoding='unicode')
        response = ET.fromstring(self.server.snap_response(user, node)).findtext('retrieve/response')
        self.assertEqual(response, '0\nOK\n1|1|0|0|playerskills|1|0\n0|1|0|0|100|Peer\n')
        self.assertIn('Login required', self.server.snap_response(None, node))

    def test_community_cookie_expiry_and_failed_reauthentication(self):
        now = 10
        self.server.clock = lambda: now
        uid = self.store.create_user('Native', 'native-test')
        token, session = self.server.community_session('JSESSIONID=untrusted-client-value')
        self.assertNotEqual(token, 'untrusted-client-value')
        self.server.soap_response(community('authenticateUser2', username='Native', password='native-test'), session)
        self.assertEqual(session.user, uid)
        self.assertEqual(self.server.community_session('JSESSIONID='+token), (token, session))
        self.server.soap_response(community('authenticateUser2', username='Native', password='wrong'), session)
        self.assertIsNone(session.user)
        now += 3601
        replacement, fresh = self.server.community_session('JSESSIONID='+token)
        self.assertNotEqual(replacement, token)
        self.assertIsNone(fresh.user)
        self.assertNotIn(token, self.server.http_sessions)

    def test_community_sessions_have_a_fixed_capacity(self):
        for _ in range(520):
            self.server.community_session('')
        self.assertEqual(len(self.server.http_sessions), 512)


class AshenTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AshenStore(self.directory.name)
        self.server = AshenServer(self.store)
        self.listener = await asyncio.start_server(self.server.xmpp, '127.0.0.1', 0)
        self.reader, self.writer = await asyncio.open_connection(*self.listener.sockets[0].getsockname())

    async def asyncTearDown(self):
        self.writer.close()
        await self.writer.wait_closed()
        self.listener.close()
        await self.listener.wait_closed()
        await self.server.close()
        self.store.close()
        self.directory.cleanup()

    async def exchange(self, request, end=b'</iq>'):
        self.writer.write(request.encode())
        await self.writer.drain()
        return await asyncio.wait_for(self.reader.readuntil(end), 2)

    async def test_legacy_auth_roster_and_fragmented_leaderboard(self):
        self.store.create_user('Native', 'test')
        await self.exchange("<?xml version='1.0'?><stream:stream xmlns:stream='http://etherx.jabber.org/streams' xmlns='jabber:client' to='ngage-arena'>", b"from='ngage-arena'>")
        reply = await self.exchange('<iq type="get" id="segachat_query_username"><query xmlns="jabber:iq:auth"><username>Native</username></query></iq>')
        self.assertIn(b'<password/>', reply)
        digest = hashlib.sha1(b'test').hexdigest()
        reply = await self.exchange(f'<iq type="set" id="segachat_auth"><query xmlns="jabber:iq:auth"><username>Native</username><password>{digest}</password><resource>segachat</resource></query></iq>', b'/>')
        self.assertIn(b'type="result"', reply)
        reply = await self.exchange('<iq type="get" id="segachat_get_roster"><query xmlns="jabber:iq:roster"/></iq>')
        self.assertIn(b'<query xmlns="jabber:iq:roster"/>', reply)
        request = ET.tostring(leaderboard(), encoding='unicode')
        self.writer.write(request[:31].encode())
        await self.writer.drain()
        reply = await self.exchange(request[31:], b'</message>')
        self.assertIn(b'segachat_retrieve_resp', reply)
        self.assertIn(b'3dabc|HIGHSCORES|game_total|0|', reply)

    async def test_split_xml_declaration_and_shutdown(self):
        self.writer.write(b'<')
        await self.writer.drain()
        await asyncio.sleep(0.02)
        self.writer.write(b'!DOCTYPE stream [<!ENTITY secret "no">]>')
        await self.writer.drain()
        self.assertEqual(await asyncio.wait_for(self.reader.read(), 2), b'')

    async def test_udp_grant_is_revoked_on_failed_reauthentication_and_close(self):
        uid = self.store.create_user('Native', 'test')
        await self.exchange("<stream:stream xmlns:stream='http://etherx.jabber.org/streams' xmlns='jabber:client'>",
                            b"from='ngage-arena'>")
        digest = hashlib.sha1(b'test').hexdigest()
        auth = '<iq type="set" id="auth"><query xmlns="jabber:iq:auth"><username>Native</username><password>{}</password></query></iq>'
        await self.exchange(auth.format(digest), b'/>')
        self.assertEqual(self.server.snap_credentials.lookup('native', '127.0.0.1').user, uid)
        await self.exchange(auth.format('0'*40))
        self.assertIsNone(self.server.snap_credentials.lookup('Native', '127.0.0.1'))
        await self.exchange(auth.format(digest), b'/>')
        self.writer.close()
        await self.writer.wait_closed()
        await self.server.close()
        self.assertIsNone(self.server.snap_credentials.lookup('Native', '127.0.0.1'))

    async def test_http_registration_over_the_native_endpoint(self):
        listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        try:
            reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
            body = community('createUser', username='HTTPPlayer', password='http-test')
            writer.write(b'POST /n-gage/axis/services/Community HTTP/1.0\r\nHost: localhost\r\nContent-Length: '
                         +str(len(body)).encode()+b'\r\n\r\n'+body)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 2)
            writer.close()
            await writer.wait_closed()
            self.assertIn(b'200 OK', response)
            headers, payload = response.split(b'\r\n\r\n', 1)
            self.assertIn(b'Content-Length: '+str(len(payload)).encode(), headers)
            self.assertIn(b'createUserResponse', payload)
            self.assertIsNotNone(self.store.authenticate('HTTPPlayer', 'http-test'))
        finally:
            listener.close()
            await listener.wait_closed()

    async def test_ngage2_and_legacy_endpoints_share_the_same_account(self):
        listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        try:
            user = self.store.create_user('SharedNAF', 'native-test')
            for endpoint in ('/n-gage/axis/services/Community', '/ngi/axis/services/NGICommunity'):
                reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
                body = community('authenticateUser', username='sharednaf', password='native-test')
                writer.write(f'POST {endpoint} HTTP/1.0\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n'.encode()+body)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 2)
                writer.close()
                await writer.wait_closed()
                payload = ET.fromstring(response.split(b'\r\n\r\n', 1)[1])
                result = payload.find('.//{urn:CommunityApp}authenticateUserReturn')
                if endpoint.startswith('/ngi/'):
                    self.assertEqual([item.text for item in result], ['0', 'SharedNAF'])
                else:
                    self.assertEqual(result.text, str(user))
        finally:
            listener.close()
            await listener.wait_closed()

    async def test_url_session_cookie_and_unsupported_endpoint_completion(self):
        listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        try:
            uid = self.store.create_user('SessionOwner', 'native-test')
            token, session = self.server.community_session('')
            session.user = uid
            for endpoint, expected in [('/ngi/axis/services/NGICommunity;jsessionid='+token, b'200 OK'),
                                       ('/ngi/axis/services/unimplemented;jsessionid='+token, b'501 Not Implemented')]:
                reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
                body = community('HeartBeat')
                writer.write(f'POST {endpoint} HTTP/1.0\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n'.encode()+body)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 2)
                writer.close()
                await writer.wait_closed()
                self.assertIn(expected, response.split(b'\r\n', 1)[0])
                self.assertEqual(len(self.server.http_sessions), 1)
                self.assertEqual(session.user, uid)
                if expected == b'200 OK':
                    self.assertIn(('JSESSIONID='+token).encode(), response)
        finally:
            listener.close()
            await listener.wait_closed()

    async def test_http_continue_before_receiving_the_body(self):
        listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        try:
            reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
            body = community('createUser', username='ContinuePlayer', password='http-test')
            writer.write(b'POST /n-gage/axis/services/Community HTTP/1.1\r\nHost: localhost\r\n'
                         b'Expect: 100-continue\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2),
                             b'HTTP/1.1 100 Continue\r\n\r\n')
            writer.write(body)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 2)
            writer.close()
            await writer.wait_closed()
            self.assertIn(b'createUserResponse', response)
            self.assertIsNotNone(self.store.authenticate('ContinuePlayer', 'http-test'))
        finally:
            listener.close()
            await listener.wait_closed()

    async def test_native_ngi_heartbeat_is_a_stateless_availability_probe(self):
        now = 10
        self.server.clock = lambda: now
        listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)

        async def get(cookie=''):
            reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
            try:
                headers = 'Host: localhost\r\nUser-Agent: native-heartbeat\r\n'
                if cookie:
                    headers += 'Cookie: '+cookie+'\r\n'
                writer.write(('GET /ngi/axis/services/NGICommunity HTTP/1.1\r\n'+headers+'\r\n').encode())
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 2)
                self.assertTrue(response.startswith(b'HTTP/1.0 200 OK\r\n'))
                self.assertNotIn(b'Set-Cookie:', response)
                self.assertEqual(response.split(b'\r\n\r\n', 1)[1], b'')
            finally:
                writer.close()
                await writer.wait_closed()

        try:
            await get()
            await get('JSESSIONID=unknown')
            self.assertEqual(self.server.http_sessions, {})
            uid = self.store.create_user('Heartbeat', 'native-test')
            token, session = self.server.community_session('')
            self.server.soap_response(community('authenticateUser', username='Heartbeat', password='native-test'), session, ngi=True)
            original_expiry = session.expires
            for elapsed in (600, 3601):
                now += elapsed
                for cookie in ('', 'JSESSIONID=unknown', 'JSESSIONID='+token):
                    await get(cookie)
                    self.assertEqual(self.server.http_sessions, {token: session})
                    self.assertEqual(session.user, uid)
                    self.assertEqual(session.expires, original_expiry)
            replacement, anonymous = self.server.community_session('JSESSIONID='+token)
            self.assertNotEqual(replacement, token)
            self.assertIsNone(anonymous.user)
        finally:
            listener.close()
            await listener.wait_closed()

    async def test_native_cookie_survives_separate_http_connections(self):
        listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        try:
            token = None
            for _ in range(2):
                reader, writer = await asyncio.open_connection(*listener.sockets[0].getsockname())
                body = community('HeartBeat')
                request = b'POST /n-gage/axis/services/Community HTTP/1.1\r\nHost: localhost\r\n'
                if token:
                    request += ('Cookie: unrelated=CaseSensitive; JSESSIONID='+token+'\r\n').encode()
                writer.write(request + b'Content-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 2)
                writer.close()
                await writer.wait_closed()
                headers, payload = response.split(b'\r\n\r\n', 1)
                cookie = SimpleCookie(next(line.decode().split(':', 1)[1]
                                           for line in headers.split(b'\r\n') if line.startswith(b'Set-Cookie:')))
                self.assertEqual(cookie['JSESSIONID']['path'], '/')
                if token:
                    self.assertEqual(cookie['JSESSIONID'].value, token)
                token = cookie['JSESSIONID'].value
                self.assertIn(b'HeartBeatReturn>true', payload)
        finally:
            listener.close()
            await listener.wait_closed()


if __name__ == '__main__':
    unittest.main()
