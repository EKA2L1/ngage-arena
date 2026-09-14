import asyncio
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import unittest
import warnings

from arena.services.community.tls import CommunityListener, server_context


@unittest.skipUnless(shutil.which('openssl'), 'openssl is needed to create a temporary test certificate')
class CommunityTLSTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.cert = Path(cls.directory.name)/'cert.pem'
        cls.key = Path(cls.directory.name)/'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-noenc',
                        '-keyout', str(cls.key), '-out', str(cls.cert), '-days', '1',
                        '-subj', '/CN=arena.test', '-addext', 'subjectAltName=DNS:arena.test'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    async def asyncSetUp(self):
        async def echo(reader, writer):
            writer.write(await reader.readexactly(4))
            await writer.drain()
        self.server = CommunityListener(echo, '127.0.0.1', 0,
                                        server_context(self.cert, self.key, legacy=True))
        self.port = self.server.socket.getsockname()[1]
        self.task = asyncio.create_task(self.server.serve_forever())
        await asyncio.sleep(0)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await asyncio.gather(self.task, return_exceptions=True)

    async def test_plaintext_and_verified_tls10_share_a_port(self):
        for secure in (False, True):
            options = {}
            if secure:
                context = ssl.create_default_context(cafile=str(self.cert))
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', DeprecationWarning)
                    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1
                context.set_ciphers('AES128-SHA:@SECLEVEL=0')
                options = {'ssl': context, 'server_hostname': 'arena.test'}
            reader, writer = await asyncio.open_connection('127.0.0.1', self.port, **options)
            writer.write(b'POST')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(4), 3), b'POST')
            writer.close()
            await writer.wait_closed()
        self.assertGreaterEqual(server_context(self.cert, self.key).minimum_version, ssl.TLSVersion.TLSv1_2)

    async def test_shutdown_cancels_a_client_that_has_not_sent_headers(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        self.server.close()
        await asyncio.wait_for(self.server.wait_closed(), 1)
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
        writer.close()
        await writer.wait_closed()
