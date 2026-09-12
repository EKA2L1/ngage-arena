"""A local, persistent implementation of the original N-Gage AirPlay transport."""
import argparse
import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import logging
import hashlib
import json
from pathlib import Path
import secrets
import struct
import time

from .codec import HEADER, Object, ProtocolError, Reader, file_chunks, pages, string
from .store import Store
from .replay import read_clip

LOG = logging.getLogger('arena')
MAX_UPLOAD = 8 * 1024 * 1024

@dataclass
class Upload:
    size: int
    kind: int
    caption: str
    value1: int
    value2: int
    target: str = ''
    chunks: dict = field(default_factory=dict)

    def accept(self, payload):
        reader = Reader(payload)
        start, end, size = reader.unpack('III')
        chunk = reader.take(size)
        reader.finish()
        if end != start + size - 1 or end >= self.size or size == 0:
            raise ProtocolError('invalid upload range')
        for offset, previous in self.chunks.items():
            if start == offset and previous == chunk:
                return None
            if start < offset + len(previous) and offset < start + size:
                raise ProtocolError('overlapping upload range')
        self.chunks[start] = chunk
        if sum(map(len, self.chunks.values())) != self.size:
            return None
        position, data = 0, bytearray()
        for offset, chunk in sorted(self.chunks.items()):
            if offset != position:
                raise ProtocolError('upload contains a gap')
            data.extend(chunk)
            position += len(chunk)
        return bytes(data)

@dataclass
class Peer:
    seen: OrderedDict = field(default_factory=OrderedDict)
    pending: dict = field(default_factory=dict)
    queue: deque = field(default_factory=deque)
    user: int | None = None
    upload: Upload | None = None
    race_id: int | None = None
    last_seen: float = field(default_factory=time.monotonic)

class Arena(asyncio.DatagramProtocol):
    def __init__(self, store, billing):
        self.store = store
        self.billing = billing
        self.peers = {}
        self.sequence = secrets.randbelow(0x10000000)
        self.transport = None
        self.timer = None

    def connection_made(self, transport):
        self.transport = transport
        LOG.info('AirPlay listening on %s', transport.get_extra_info('sockname'))
        self.tick()

    def connection_lost(self, error):
        if self.timer:
            self.timer.cancel()
        self.transport = None

    def packet(self, command, body, flag=0):
        self.sequence = (self.sequence + 1) & 0xffffffff
        return self.sequence, HEADER.pack(self.sequence,command,flag,255) + body

    def send(self, address, command, body=b''):
        peer = self.peers[address]
        sequence, packet = self.packet(command,body)
        # The retail client can lose an IPC completion when a localhost reply is immediate.
        peer.queue.append((sequence,packet,time.monotonic()+0.05))

    def pump(self, address, peer):
        while peer.queue and len(peer.pending) < 4 and peer.queue[0][2] <= time.monotonic():
            sequence, packet, _ = peer.queue.popleft()
            peer.pending[sequence] = [packet,time.monotonic(),0]
            self.transport.sendto(packet,address)

    def tick(self):
        now = time.monotonic()
        for address,peer in list(self.peers.items()):
            if now-peer.last_seen > 600:
                del self.peers[address]
                continue
            for sequence,entry in list(peer.pending.items()):
                packet, sent, retries = entry
                if now-sent > min(1.0 * 2**retries,4):
                    if retries >= 7:
                        del peer.pending[sequence]
                        LOG.warning('Reply %s timed out',sequence)
                    else:
                        self.transport.sendto(packet,address)
                        entry[1:] = [now,retries+1]
            self.pump(address,peer)
        self.timer = asyncio.get_running_loop().call_later(0.02,self.tick)

    def datagram_received(self, data, address):
        if len(data) < HEADER.size:
            return
        sequence,command,flag,extra = HEADER.unpack_from(data)
        body = data[HEADER.size:]
        if address not in self.peers and len(self.peers) >= 256:
            return
        peer = self.peers.setdefault(address,Peer())
        peer.last_seen = time.monotonic()
        if command == 250:
            if len(body) == 4:
                peer.pending.pop(struct.unpack('<I',body)[0],None)
                self.pump(address,peer)
            return
        if flag == 0:
            _,ack = self.packet(250,struct.pack('<I',sequence),1)
            self.transport.sendto(ack,address)
        if sequence in peer.seen:
            return
        peer.seen[sequence] = None
        while len(peer.seen) > 2048:
            peer.seen.popitem(last=False)
        try:
            self.handle(address,peer,command,Reader(body))
        except (ProtocolError,ValueError,UnicodeError,struct.error) as error:
            LOG.warning('Rejected command %d: %s',command,error)
        except Exception:
            LOG.exception('Command %d failed',command)

    def handle(self, address, peer, command, reader):
        if command == 50:
            reader.unpack('H')
            version,digest = reader.string(),reader.string()
            reader.unpack('HH')
            reader.string(); reader.string(); reader.finish()
            current = version == 'local-1' and digest.lower() == hashlib.md5(self.billing.read_bytes()).hexdigest()
            self.send(address,150,bytes((0 if current else 1,)) + string(''))
        elif command == 51:
            for chunk in file_chunks(self.billing.read_bytes()):
                self.send(address,121,chunk)
        elif command == 0:
            reader.unpack('5H'); reader.string(); reader.u32()
            name,password,imei,imsi = (reader.string() for _ in range(4))
            reader.unpack('B'); reader.finish()
            status,peer.user = self.store.login(name,imei)
            self.send(address,120,bytes((status,0)))
            LOG.info('Login status=%d user=%s',status,peer.user)
        elif command == 2:
            name,identity = reader.string(),reader.string()
            reader.finish()
            status,peer.user = self.store.login(name,identity)
            self.send(address,120,bytes((status,0)))
        elif command == 1:
            peer.user = None
            peer.upload = None
        elif command == 12:
            self.send(address,127,reader.take(8))
            reader.finish()
        elif peer.user is None:
            raise ProtocolError('login required')
        elif command == 9:
            parent,filter_text = reader.u32(),reader.string()
            reader.finish()
            records = self.directory(peer,parent,filter_text)
            for page in pages([obj.encode() for obj in records],struct.pack('<I',parent)):
                self.send(address,124,page)
            LOG.info('Directory parent=%d records=%d',parent,len(records))
        elif command == 10:
            reader.finish()
            self.send(address,125,b'\0\0\1')
        elif command == 11:
            filter_text = reader.string(); reader.finish()
            records = [string(row['body'],200) + bytes((1 if row['recipient'] is None else 0,0)) + struct.pack('<I',row['id']) + string(row['sender'],12) + struct.pack('<II',0,0)
                       for row in self.store.messages(peer.user)]
            for page in pages(records):
                self.send(address,126,page)
            LOG.info('Messages count=%d',len(records))
        elif command == 3:
            oid,token = reader.u32(),reader.string(); reader.finish()
            content = self.store.content(oid)
            if content is None:
                raise ProtocolError('unknown download object')
            kind = self.store.db.execute('SELECT kind FROM objects WHERE id=?',(oid,)).fetchone()[0]
            if kind == 1001:
                self.store.start_challenge(peer.user,oid,competitive=token.startswith('701,'))
            for chunk in file_chunks(content,oid):
                self.send(address,121,chunk)
            LOG.info('Download object=%d bytes=%d',oid,len(content))
        elif command in (6,7):
            if command == 6:
                kind = reader.unpack('H')[0]
                target = ''
            else:
                kind,target = 1002,reader.string()
            size,caption = reader.u32(),reader.string()
            value1,value2 = reader.unpack('II'); reader.finish()
            if not 0 < size <= MAX_UPLOAD:
                raise ProtocolError('upload size out of bounds')
            peer.upload = Upload(size,kind,caption,value1,value2,target)
            self.send(address,122)
            LOG.info('Upload started type=%d bytes=%d values=%d,%d',kind,size,value1,value2)
        elif command == 8:
            if peer.upload is None:
                raise ProtocolError('no upload in progress')
            upload = peer.upload
            content = upload.accept(reader.take(len(reader.data)))
            if content is not None:
                if upload.kind == 1002:
                    read_clip(content)
                    oid = self.store.add_content(1301,2222,upload.caption or 'Player recording',content,peer.user,
                        {'upload_type':upload.kind,'value1':upload.value1,'value2':upload.value2,'target':upload.target})
                elif upload.kind == 1001:
                    oid = self.store.finish_race(peer.user,content,upload.caption)
                else:
                    raise ProtocolError('unknown upload type')
                peer.upload = None
                self.send(address,123)
                LOG.info('Upload saved object=%d bytes=%d',oid,len(content))
        else:
            raise ProtocolError('unsupported command')

    def directory(self, peer, parent, filter_text):
        course_row = self.store.db.execute('SELECT metadata FROM objects WHERE id=? AND parent=900', (parent,)).fetchone()
        if course_row:
            peer.race_id = json.loads(course_row['metadata'])['course_id']
            course = self.store.db.execute('SELECT * FROM courses WHERE id=?', (peer.race_id,)).fetchone()
            return [Object(912,0,'High Scores'), Object(course['reference_object'],1001,'Practice course')]
        if parent in (912,915,918):
            courses = self.store.courses()
            if not courses:
                return []
            if parent == 915 and filter_text.endswith(',revenge'):
                filter_text = filter_text[:-len(',revenge')]
                challenged = self.store.db.execute('''SELECT c.race_id FROM challenges c
                    JOIN users u ON u.id=c.user_id JOIN race_results r ON r.id=c.result_id
                    WHERE c.opponent=? AND u.name=? COLLATE NOCASE AND c.competitive=1
                    AND r.milliseconds<c.target_ms ORDER BY c.id DESC LIMIT 1''',
                    (peer.user,filter_text)).fetchone()
                if challenged:
                    peer.race_id = challenged['race_id']
            race_id = peer.race_id or courses[0]['id']
            leaders = self.store.leaders(race_id)
            if parent == 912:
                return [Object(row['object_id'],1001,row['name'],value1=row['milliseconds'],value2=row['score'],value3=10,value4=5)
                        for row in leaders]
            if parent == 915:
                opponent = next((row for row in leaders if row['name'].casefold() == filter_text.casefold()), None)
                if opponent is None:
                    raise ProtocolError('unknown challenge opponent')
                opponent_rank = next(i for i,row in enumerate(leaders,1) if row['user_id'] == opponent['user_id'])
                own = next(((i,row) for i,row in enumerate(leaders,1) if row['user_id'] == peer.user),None)
                name = self.store.db.execute('SELECT name FROM users WHERE id=?',(peer.user,)).fetchone()[0]
                return [Object(opponent['object_id'],1001,opponent['name'],str(opponent_rank),value1=opponent['milliseconds'],value2=opponent['score'],value3=10,value4=5),
                        Object(opponent['object_id'],1001,name,str(own[0] if own else 0),value1=own[1]['milliseconds'] if own else 0,
                               value2=own[1]['score'] if own else 0,value3=race_id,value4=opponent['object_id'])]
            result = self.store.db.execute('''SELECT r.*,u.name,c.target_ms,c.opponent,
                (SELECT name FROM users WHERE id=c.opponent) AS opponent_name,
                COALESCE(e.points,0) AS points,
                COALESCE((SELECT SUM(points) FROM league_events WHERE user_id=r.user_id AND month=?),0) AS score
                FROM race_results r JOIN users u ON r.user_id=u.id
                LEFT JOIN challenges c ON c.result_id=r.id LEFT JOIN league_events e ON e.challenge_id=c.id
                WHERE r.user_id=? ORDER BY r.id DESC LIMIT 1''',(self.store.month(),peer.user)).fetchone()
            if result:
                rank = next((i for i,row in enumerate(self.store.leaders(result['race_id']),1) if row['user_id'] == peer.user),0)
                won = result['target_ms'] is None or result['milliseconds'] < result['target_ms']
                return [Object(result['object_id'],1001,result['name'],value1=result['milliseconds'],value2=result['score'],value3=rank),
                        Object(0,0,'Outcome',value1=int(won),value2=abs(result['points']))]
            return []
        trophies = self.store.trophies()
        months = list(dict.fromkeys(row['month'] for row in trophies))
        month_ids = {40000 + int(month[:4]) * 12 + int(month[5:]):month for month in months}
        if parent == 2001:
            return [Object(oid,0,month) for oid,month in month_ids.items()]
        if parent in month_ids:
            return [Object(parent + row['place'] * 100000,0,f"{('Gold','Silver','Bronze')[row['place']-1]}: {row['name']}")
                    for row in trophies if row['month'] == month_ids[parent]]
        return self.store.objects(parent)

async def run(args):
    loop = asyncio.get_running_loop()
    store = Store(args.data)
    transport,protocol = await loop.create_datagram_endpoint(lambda:Arena(store,args.billing),local_addr=(args.host,args.port))
    try:
        await asyncio.Future()
    finally:
        transport.close()
        store.db.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=41001)
    parser.add_argument('--data',type=Path,default=Path('data'))
    parser.add_argument('--billing',type=Path,default=Path(__file__).resolve().parents[1]/'assets/abtesrv.dll')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
