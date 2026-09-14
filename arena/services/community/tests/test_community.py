import asyncio
import hashlib
from http.cookies import SimpleCookie
from pathlib import Path
import xml.etree.ElementTree as ET

from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer
from arena.runtime import default_games


from arena.services.community.tests.support import community, CommunityCase, CommunityTransportCase

class CommunityTests(CommunityCase):
    def test_native_registration_login_and_restart(self):
        response = self.server.soap_response(community('createUser', username='Ashen', password='native-test'))
        self.assertIn(b'createUserResponse', response)
        self.assertIn(b'Fault', self.server.soap_response(community('createUser', username='ashen', password='other')))
        self.store.close()
        self.store = AccountStore(self.directory.name)
        self.server = CommunityServer(self.store, default_games(self.store))
        uid = self.store.authenticate('ASHEN', 'native-test')
        self.assertIsNotNone(uid)
        self.assertEqual(self.store.authenticate_snap('ashen', hashlib.sha1(b'native-test').hexdigest()), uid)
        self.assertIsNone(self.store.authenticate_snap('ashen', 'native-test'))
        self.assertIsNone(self.store.authenticate('ashen', 'wrong'))
        self.assertNotIn(b'native-test', (Path(self.directory.name)/'community.sqlite3').read_bytes())
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

class CommunityTransportTests(CommunityTransportCase):
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
        self.assertEqual(len(self.server.messaging.connections), 0)
        await self.exchange(auth.format(digest), b'/>')
        self.writer.close()
        await self.writer.wait_closed()
        await self.server.close()
        self.assertIsNone(self.server.snap_credentials.lookup('Native', '127.0.0.1'))
        self.assertEqual(len(self.server.messaging.connections), 0)
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
