import asyncio
from http.cookies import SimpleCookie
import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.runtime import default_games
from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer
from arena.services.community.tests.support import community
from arena.services.profiles.tests.test_profiles import request as profile_request


class LauncherSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AccountStore(self.directory.name)
        self.now = 10
        self.server = CommunityServer(self.store, default_games(self.store), clock=lambda: self.now)
        self.listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        self.user = self.store.create_user('Launcher', 'native-test')
        self.peer = self.store.create_user('Peer', 'native-test')
        self.server.profiles.store.update(self.user, {'quote': 'Keep this profile'})
        self.server.profiles.store.request_friend(self.user, self.peer)
        self.server.profiles.store.accept_friend(self.peer, self.user)

    async def asyncTearDown(self):
        self.listener.close()
        await self.listener.wait_closed()
        await self.server.close()
        self.store.close()
        self.directory.cleanup()

    async def exchange(self, path, body=None, cookie=''):
        reader, writer = await asyncio.open_connection(*self.listener.sockets[0].getsockname())
        try:
            method = 'GET' if body is None else 'POST'
            body = body or b''
            writer.write((f'{method} {path} HTTP/1.0\r\nHost: localhost\r\nCookie: {cookie}\r\n'
                          f'Content-Length: {len(body)}\r\n\r\n').encode()+body)
            await writer.drain()
            head, payload = (await asyncio.wait_for(reader.read(), 2)).split(b'\r\n\r\n', 1)
            lines = head.decode().split('\r\n')
            self.assertEqual(lines[0], 'HTTP/1.0 200 OK')
            headers = dict(line.split(': ', 1) for line in lines[1:])
            return headers, payload
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_expired_native_cookie_can_reauthenticate_without_losing_shared_data(self):
        endpoint = '/ngi/axis/services/NGICommunity'
        login = community('authenticateUser', username='launcher', password='native-test')
        headers, _ = await self.exchange(endpoint, login)
        token = SimpleCookie(headers['Set-Cookie'])['JSESSIONID'].value
        cookie = 'JSESSIONID='+token
        query = profile_request('getProfile', '<lastSynchDate>2000-01-01T00:00:00Z</lastSynchDate>')
        self.now += 3599
        _, body = await self.exchange('/ngi/axis/services/userprofile', query, cookie)
        self.assertEqual(ET.fromstring(body).findtext('.//user/username'), 'Launcher')
        self.assertEqual(self.server.http_sessions[token].expires, self.now+3600)
        self.now += 3601
        await self.exchange(endpoint, cookie=cookie)
        headers, public = await self.exchange('/rankings.html?GCID=4444', cookie=cookie)
        self.assertNotIn('Set-Cookie', headers)
        self.assertIn(b'Rankings', public)
        _, denied = await self.exchange('/ngi/axis/services/userprofile', query, cookie)
        self.assertEqual(ET.fromstring(denied).findtext('.//ngpException/errorCode'), '401')
        self.assertNotIn(token, self.server.http_sessions)
        self.assertIsNone(ET.fromstring(denied).find('.//user'))
        headers, result = await self.exchange(endpoint, login, cookie)
        items = ET.fromstring(result).find('.//{urn:CommunityApp}authenticateUserReturn')
        self.assertEqual([item.text for item in items], ['0', 'Launcher'])
        fresh = SimpleCookie(headers['Set-Cookie'])['JSESSIONID'].value
        self.assertNotEqual(fresh, token)
        _, body = await self.exchange('/ngi/axis/services/userprofile', query, 'JSESSIONID='+fresh)
        self.assertEqual(ET.fromstring(body).findtext('.//user/quote'), 'Keep this profile')
        self.assertEqual(self.store.authenticate('Launcher', 'native-test'), self.user)
        self.assertEqual(self.server.profiles.store.friends(self.user), [self.peer])
