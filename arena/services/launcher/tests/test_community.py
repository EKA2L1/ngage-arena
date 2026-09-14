import asyncio
import xml.etree.ElementTree as ET



from arena.services.community.tests.support import community, CommunityCase, CommunityTransportCase

class CommunityTests(CommunityCase):
    def test_ngi_authentication_uses_status_array_and_clears_failed_sessions(self):
        uid = self.store.create_user('Launcher', 'native-test')
        _, session = self.server.community_session('')
        for password, expected, account in [('native-test', ['0', 'Launcher'], uid), ('wrong', ['1', None], None)]:
            response = ET.fromstring(self.server.soap_response(community(
                'authenticateUser', username='launcher', password=password), session, ngi=True))
            result = response.find('.//{urn:CommunityApp}authenticateUserReturn')
            self.assertEqual([item.text for item in result], expected)
            self.assertEqual(session.user, account)

class CommunityTransportTests(CommunityTransportCase):
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
