import asyncio
import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer, SOAP
from arena.runtime import default_games


def community(method, **params):
    root = ET.Element('{'+SOAP+'}Envelope')
    operation = ET.SubElement(ET.SubElement(root, '{'+SOAP+'}Body'), '{urn:CommunityApp}'+method)
    for key, value in params.items():
        ET.SubElement(operation, key).text = value
    return ET.tostring(root)

class CommunityCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AccountStore(self.directory.name)
        self.server = CommunityServer(self.store, default_games(self.store))
    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

class CommunityTransportCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AccountStore(self.directory.name)
        self.server = CommunityServer(self.store, default_games(self.store))
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
