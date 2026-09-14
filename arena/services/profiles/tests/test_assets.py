import asyncio
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.runtime import default_games
from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer
from arena.services.profiles.assets import DEFAULT_ICON_PATH, default_icon_url
from arena.services.profiles.tests.test_profiles import request


class ProfileAssetTests(unittest.TestCase):
    def test_asset_url_uses_the_request_host_port_and_transport(self):
        for host in ('new.arena.n-gage.com:8194', 'arena.example:8443', '[::1]:8194'):
            for secure, scheme in ((False, 'http'), (True, 'https')):
                self.assertEqual(default_icon_url(host, secure), scheme+'://'+host+DEFAULT_ICON_PATH)
        for host in ('user@arena.example', 'arena.example/path', 'arena.example?token=x',
                     'arena.example#fragment', 'arena.example:65536', 'arena.example:0'):
            with self.assertRaises(ValueError):
                default_icon_url(host)


class ProfileAssetHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
        self.owner = self.accounts.create_user('Owner', 'native-test')
        self.peer = self.accounts.create_user('Peer', 'native-test')
        self.server = CommunityServer(self.accounts, default_games(self.accounts))
        self.listener = await asyncio.start_server(self.server.http, '127.0.0.1', 0)
        self.host, self.port = self.listener.sockets[0].getsockname()

    async def asyncTearDown(self):
        self.listener.close()
        await self.listener.wait_closed()
        await self.server.close()
        self.accounts.close()
        self.directory.cleanup()

    async def exchange(self, method, path, body=b'', cookie=''):
        reader, writer = await asyncio.open_connection(self.host, self.port)
        writer.write((f'{method} {path} HTTP/1.1\r\nHost: arena.example:{self.port}\r\n'
                      f'Cookie: {cookie}\r\nContent-Length: {len(body)}\r\n\r\n').encode()+body)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 2)
        writer.close()
        await writer.wait_closed()
        return response.split(b'\r\n\r\n', 1)

    async def test_native_head_then_get_provides_a_public_png_without_a_session(self):
        head, empty = await self.exchange('HEAD', DEFAULT_ICON_PATH)
        headers, image = await self.exchange('GET', DEFAULT_ICON_PATH)
        self.assertTrue(head.startswith(b'HTTP/1.0 200 OK\r\n'))
        self.assertEqual(head, headers)
        self.assertEqual(empty, b'')
        self.assertIn(b'Content-Type: image/png', headers)
        self.assertIn(b'Content-Length: '+str(len(image)).encode(), headers)
        self.assertTrue(image.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack('>II', image[16:24]), (64, 64))
        self.assertNotIn(b'Set-Cookie:', headers)
        self.assertEqual(self.server.http_sessions, {})

    async def test_all_profile_shapes_return_a_downloadable_default_for_the_target(self):
        token, session = self.server.community_session('')
        session.user = self.owner
        profiles = self.server.profiles.store
        profiles.request_friend(self.owner, self.peer)
        profiles.accept_friend(self.peer, self.owner)
        for method, content, field in (
                ('getMiniProfile', '<username>Peer</username>', 'miniProfile'),
                ('getProfile', '<lastSynchDate>0001-01-01T00:00:00Z</lastSynchDate>', 'user'),
                ('getFriendsMiniProfiles', '<lastSyncDate>0001-01-01T00:00:00Z</lastSyncDate>', 'friendsMiniProfiles/miniProfile')):
            headers, body = await self.exchange('POST', '/ngi/axis/services/userprofile',
                                                request(method, content), 'JSESSIONID='+token)
            self.assertTrue(headers.startswith(b'HTTP/1.0 200 OK\r\n'))
            profile = ET.fromstring(body).find('.//'+field)
            self.assertEqual(profile.findtext('username'), 'Owner' if method == 'getProfile' else 'Peer')
            self.assertEqual(profile.findtext('iconUrl'), f'http://arena.example:{self.port}'+DEFAULT_ICON_PATH)
        profiles.update(self.peer, {'iconUrl': 'https://assets.example/peer.png'})
        _, body = await self.exchange('POST', '/ngi/axis/services/userprofile',
                                      request('getMiniProfile', '<username>Peer</username>'), 'JSESSIONID='+token)
        self.assertEqual(ET.fromstring(body).findtext('.//miniProfile/iconUrl'), 'https://assets.example/peer.png')
        _, denied = await self.exchange('POST', '/ngi/axis/services/userprofile',
                                        request('getMiniProfile', '<username>Peer</username>'))
        self.assertEqual(ET.fromstring(denied).findtext('.//ngpexception/errorCode'), '401')
