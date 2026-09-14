import asyncio
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from arena.games.tomb_raider.codec import HEADER, Object, ProtocolError, Reader, file_chunks, pages, string
from arena.games.tomb_raider.server import Arena, Upload
from arena.games.tomb_raider.store import Store


from arena.games.tomb_raider.tests.fixtures import fixture_clip

class CodecTests(unittest.TestCase):
    def test_guest_directory_layout(self):
        obj = Object(912,0,'League',value1=17,value2=23,value3=29,value4=31)
        page, = pages([obj.encode()],struct.pack('<I',1))
        self.assertEqual(page[:7],bytes.fromhex('01000101000000'))
        self.assertEqual(struct.unpack_from('<IHHIIII',page,7),(912,0,0,17,23,29,31))
        reader = Reader(page[31:])
        self.assertEqual(reader.string(),'League')
        self.assertEqual(reader.string(),'')
        reader.finish()

    def test_page_boundaries(self):
        records = [Object(i,2222,'A'*20,'B'*20).encode() for i in range(75)]
        result = pages(records,struct.pack('<I',1301))
        self.assertGreater(len(result),1)
        self.assertEqual(sum(p[0] for p in result),75)
        self.assertTrue(all(len(p)<=1100 for p in result))
        self.assertEqual([p[1] for p in result],list(range(len(result))))
        self.assertEqual({p[2] for p in result},{len(result)})

    def test_file_ranges_are_inclusive(self):
        data = bytes(range(251))*13
        result = list(file_chunks(data,1234))
        assembled = bytearray(len(data))
        for chunk in reversed(result):
            total,start,end,size = struct.unpack_from('<4I',chunk)
            self.assertEqual(total,len(data))
            self.assertEqual(end,start+size-1)
            self.assertEqual(struct.unpack_from('<I',chunk,16+size)[0],1234)
            assembled[start:end+1] = chunk[16:16+size]
        self.assertEqual(bytes(assembled),data)

    def test_reject_truncated_and_oversized_strings(self):
        for data in (b'\1',struct.pack('<I',5)+b'ab',struct.pack('<I',2**31)):
            with self.assertRaises(ProtocolError):
                Reader(data).string()

    def test_reordered_upload_and_duplicate(self):
        upload = Upload(6,1002,'Clip',1,2)
        tail = struct.pack('<III',3,5,3)+b'def'
        self.assertIsNone(upload.accept(tail))
        self.assertIsNone(upload.accept(tail))
        self.assertEqual(upload.accept(struct.pack('<III',0,2,3)+b'abc'),b'abcdef')

    def test_overlapping_upload_rejected(self):
        upload = Upload(6,1002,'Clip',1,2)
        upload.accept(struct.pack('<III',0,2,3)+b'abc')
        with self.assertRaises(ProtocolError):
            upload.accept(struct.pack('<III',2,4,3)+b'cde')
        with self.assertRaises(ProtocolError):
            upload.accept(struct.pack('<III',5,7,3)+b'fgh')

class StoreTests(unittest.TestCase):
    def test_identity_ownership_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            status,uid = store.login('Lara','device-one')
            self.assertEqual(status,0)
            self.assertEqual(store.login('lara','device-two'),(3,None))
            self.assertEqual(store.login('Lara2','device-one'),(0,uid))
            oid = store.add_content(1301,2222,'Jump',b'replay',uid)
            store.close()
            store = Store(directory)
            self.assertEqual(store.login('Lara2','device-one'),(0,uid))
            self.assertEqual(store.content(oid),b'replay')
            identities = str(list(store.db.execute('SELECT identity FROM users')))
            self.assertNotIn('device-one',identities)
            store.close()

class QueueClient(asyncio.DatagramProtocol):
    def __init__(self):
        self.queue = asyncio.Queue()

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        self.queue.put_nowait(data)

class WireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        loop = asyncio.get_running_loop()
        self.transport,self.server = await loop.create_datagram_endpoint(
            lambda:Arena(self.store,Path(__file__).resolve().parents[1]/'assets/abtesrv.dll'),local_addr=('127.0.0.1',0))
        self.client_transport,self.client = await loop.create_datagram_endpoint(QueueClient,remote_addr=self.transport.get_extra_info('sockname'))
        self.sequence = 1

    async def asyncTearDown(self):
        self.client_transport.close()
        self.transport.close()
        await asyncio.sleep(0)
        self.store.close()
        self.directory.cleanup()

    def send(self, command, body=b''):
        self.sequence += 1
        packet = HEADER.pack(self.sequence,command,0,255)+body
        self.client_transport.sendto(packet)
        return packet

    async def receive(self, expected):
        while True:
            packet = await asyncio.wait_for(self.client.queue.get(),2)
            seq,command,flag,extra = HEADER.unpack_from(packet)
            if command == 250:
                continue
            self.sequence += 1
            self.client_transport.sendto(HEADER.pack(self.sequence,250,1,0)+struct.pack('<I',seq))
            self.assertEqual(command,expected)
            return packet[8:]

    async def login(self):
        self.send(50,struct.pack('<H',2)+string('local-1')+string(hashlib.md5(self.server.billing.read_bytes()).hexdigest())+struct.pack('<HH',34,9)+string('test-device')+string('test-sim'))
        self.assertEqual(await self.receive(150),b'\0'+string(''))
        self.send(0,struct.pack('<5H',3,34,9,13,0)+string('')+struct.pack('<I',5)+string('Lara')+string('AndyC')+string('test-device')+string('test-sim')+b'\1')
        self.assertEqual(await self.receive(120),b'\0\0')

    async def test_guest_login_upload_download(self):
        await self.login()
        data = fixture_clip()
        self.send(6,struct.pack('<HI',1002,len(data))+string('Test clip')+struct.pack('<II',1202,0))
        self.assertEqual(await self.receive(122),b'')
        chunks = list(file_chunks(data,17))
        for chunk in reversed(chunks):
            total,start,end,size = struct.unpack_from('<4I',chunk)
            packet = self.send(8,struct.pack('<III',start,end,size)+chunk[16:16+size])
            self.client_transport.sendto(packet)
        self.assertEqual(await self.receive(123),b'')
        objects = self.store.objects(1301)
        self.assertEqual(len(objects),1)
        self.assertEqual(objects[0].kind,2222)
        oid = objects[0].id
        self.send(3,struct.pack('<I',oid)+string(''))
        received = bytearray(len(data))
        for _ in chunks:
            chunk = await self.receive(121)
            total,start,end,size = struct.unpack_from('<4I',chunk)
            received[start:end+1] = chunk[16:16+size]
        self.assertEqual(bytes(received),data)
        self.assertEqual(self.store.content(oid),data)

    async def test_native_challenge_fields_and_result_upload(self):
        from arena.games.tomb_raider.tests.fixtures import fixture_ghost
        await self.login()
        self.store.import_course('Caves',fixture_ghost())
        _,opponent = self.store.login('Racer','another-device')
        recording = self.store.finish_race(opponent,fixture_ghost(4000),'Reference')
        self.send(9,struct.pack('<I',915)+string('Racer'))
        page = await self.receive(124)
        self.assertEqual(page[:7],bytes((2,0,1))+struct.pack('<I',915))
        reader = Reader(page[7:])
        first = reader.unpack('IHHIIII')
        self.assertEqual((reader.string(),reader.string()),('Racer','1'))
        second = reader.unpack('IHHIIII')
        self.assertEqual((reader.string(),reader.string()),('Lara','0'))
        reader.finish()
        self.assertEqual(first[3:],(4000,0,10,5))
        self.assertEqual(second[-2:],(7,recording))
        self.send(3,struct.pack('<I',recording)+string('701,7'))
        for _ in file_chunks(self.store.content(recording),recording):
            await self.receive(121)
        data = fixture_ghost(3000)
        self.send(6,struct.pack('<HI',1001,len(data))+string('Good race')+struct.pack('<II',3000,recording))
        await self.receive(122)
        for chunk in file_chunks(data):
            total,start,end,size = struct.unpack_from('<4I',chunk)
            self.send(8,struct.pack('<III',start,end,size)+chunk[16:])
        await self.receive(123)
        self.send(9,struct.pack('<I',918)+string('7'))
        page = await self.receive(124)
        reader = Reader(page[7:])
        result = reader.unpack('IHHIIII')
        self.assertEqual(reader.string(),'Lara');reader.string()
        outcome = reader.unpack('IHHIIII')
        self.assertEqual(result[3:6],(3000,10,1))
        self.assertEqual(outcome[3:5],(1,10))
        self.assertEqual(self.store.messages(opponent)[0]['body'],'Good race')

    async def test_native_guide_upload_category(self):
        await self.login()
        self.send(9,struct.pack('<I',1203)+string(''))
        page = await self.receive(124)
        reader = Reader(page[7:])
        categories = {}
        for _ in range(page[0]):
            fields = reader.unpack('IHHIIII')
            categories[reader.string()] = fields[:2]
            reader.string()
        reader.finish()
        category,kind = categories['Caves']
        self.assertEqual(kind,2)
        data = fixture_clip()
        self.send(6,struct.pack('<HI',1002,len(data))+string('Caves route')+struct.pack('<II',0,category))
        await self.receive(122)
        for chunk in file_chunks(data):
            total,start,end,size = struct.unpack_from('<4I',chunk)
            self.send(8,struct.pack('<III',start,end,size)+chunk[16:])
        await self.receive(123)
        self.send(9,struct.pack('<I',1403)+string(''))
        page = await self.receive(124)
        reader = Reader(page[7:])
        fields = reader.unpack('IHHIIII')
        self.assertEqual(fields[1],2222)
        self.assertEqual(reader.string(),'Caves route')
        reader.string(); reader.finish()
        self.assertEqual(self.store.content(fields[0]),data)
        self.assertEqual(self.store.objects(1301),[])

if __name__ == '__main__':
    unittest.main()
