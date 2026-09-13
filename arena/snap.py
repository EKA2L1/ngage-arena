"""SNAP 2.1 UDP authentication and session transport used by High Seize."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
import hmac
import ipaddress
import logging
import secrets
import struct
import time

from Crypto.Cipher import Blowfish

LOG = logging.getLogger(__name__)
HEADER = struct.Struct('>HHIII')
TRAILER = bytes.fromhex('ba476611')
SWAN_KEY = b'SNAP-SWAN'
RELIABLE = 0x8000
ACK = 0x4000
MORE = 0x0800


@dataclass(frozen=True)
class Packet:
    kind: int
    body: bytes = b''
    flags: int = 0x3000
    sender: int = 0
    sequence: int = 0
    acknowledgement: int = 0

    def encode(self):
        size = HEADER.size + len(self.body)
        if size > 1023 or self.flags & (1023 | MORE):
            raise ValueError('Invalid SNAP frame size or flags')
        return HEADER.pack(self.flags | size, self.kind, self.sender,
                           self.sequence, self.acknowledgement) + self.body + TRAILER


def decode_datagram(data):
    if len(data) < 20 or data[-4:-1] != TRAILER[:3]:
        raise ValueError('Invalid SNAP datagram')
    frames = []
    offset, end = 0, len(data) - 4
    while offset < end:
        if end - offset < HEADER.size:
            raise ValueError('Truncated SNAP header')
        flags, kind, sender, sequence, ack = HEADER.unpack_from(data, offset)
        size = flags & 1023
        if size < HEADER.size or offset + size > end:
            raise ValueError('Invalid SNAP frame length')
        frames.append(Packet(kind, data[offset + HEADER.size:offset + size],
                             flags & ~1023, sender, sequence, ack))
        offset += size
    if bool(frames[0].flags & MORE) != (len(frames) > 1):
        raise ValueError('Invalid SNAP aggregation flag')
    return frames


def encrypt(key, data):
    return Blowfish.new(key, Blowfish.MODE_ECB).encrypt(
        data.ljust((len(data) + 7) // 8 * 8, b'\0'))


def decrypt(key, data):
    if not data or len(data) % 8:
        raise ValueError('Invalid SNAP ciphertext length')
    return Blowfish.new(key, Blowfish.MODE_ECB).decrypt(data)


def cstring(data):
    value, separator, _ = data.partition(b'\0')
    if not separator:
        raise ValueError('Unterminated SNAP string')
    return value.decode('ascii')


@dataclass(frozen=True)
class Credential:
    user: int
    name: str
    key: bytes = field(repr=False)
    address: str


class Credentials:
    """Keep the verified legacy verifier only while its XMPP connection is open."""

    def __init__(self):
        self.connections = {}

    def remember(self, connection, user, name, credential, address):
        key = bytes.fromhex(credential)
        if len(key) != 20:
            raise ValueError('Invalid SNAP verifier')
        self.connections[connection] = Credential(user, name, key, address)

    def forget(self, connection):
        self.connections.pop(connection, None)

    def lookup(self, name, address):
        return next((credential for credential in self.connections.values()
                     if credential.name.casefold() == name.casefold()
                     and credential.address == address), None)


@dataclass
class Session:
    user: int
    name: str
    client: int
    nonce: bytes = field(repr=False)
    expires: float
    challenge: bytes = b''
    accepted: bytes = b''
    connected: bool = False
    sequence: int = 0
    unreliable_sequence: int = 0
    next_ping: float = 0
    replies: dict = field(default_factory=dict)
    incoming: dict = field(default_factory=dict)
    next_incoming: int = 0
    outgoing: deque = field(default_factory=deque)
    pending: object = None


@dataclass
class Pending:
    sequence: int
    wire: bytes
    deadline: float
    attempts: int = 1


class SnapServer(asyncio.DatagramProtocol):
    def __init__(self, credentials, address='127.0.0.1', port=9090, clock=time.monotonic,
                 application=None):
        self.credentials = credentials
        self.address = int(ipaddress.IPv4Address(address))
        self.port = port
        self.clock = clock
        self.sessions = {}
        self.transport = None
        self.timer = None
        self.application = application
        if application:
            application.bind(self)

    def connection_made(self, transport):
        self.transport = transport
        self.port = transport.get_extra_info('sockname')[1]
        self.schedule_tick()

    def connection_lost(self, error):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.transport = None
        self.sessions.clear()
        if self.application:
            self.application.close()

    def schedule_tick(self):
        self.timer = asyncio.get_running_loop().call_later(.25, self.tick)

    def drop(self, peer, reason):
        LOG.info('SNAP peer %s disconnected: %s', peer, reason)
        if self.sessions.pop(peer, None) and self.application:
            self.application.disconnected(peer, reason)

    def tick(self):
        now = self.clock()
        for peer, session in tuple(self.sessions.items()):
            if session.expires <= now:
                self.drop(peer, 'timeout')
                continue
            pending = session.pending
            if pending and pending.deadline <= now:
                if pending.attempts >= 6:
                    self.drop(peer, 'delivery timeout')
                    continue
                self.transport.sendto(pending.wire, peer)
                pending.attempts += 1
                pending.deadline = now + min(8, 2 ** (pending.attempts - 1))
            if session.connected and session.next_ping <= now:
                if not session.pending and not session.outgoing:
                    self.send(peer, 0)
                session.next_ping = now + 30
        if self.application:
            self.application.tick(now)
        if self.transport:
            self.schedule_tick()

    def send(self, peer, kind, body=b'', flags=0x2000, reliable=True):
        session = self.sessions.get(peer)
        if not session or not session.connected:
            return
        if reliable and len(session.outgoing) >= 128:
            self.drop(peer, 'delivery queue full')
            return
        sequence = session.sequence if reliable else session.unreliable_sequence
        packet = Packet(kind, body, flags | (RELIABLE if reliable else 0),
                        self.port, sequence)
        LOG.debug('SNAP send operation=%d account=%d sequence=%d reliable=%s',
                  kind, session.user, sequence, reliable)
        if reliable:
            session.sequence = (sequence + 1) & 0xffffffff
            session.outgoing.append(packet)
            self.flush(peer, session)
        else:
            session.unreliable_sequence = (sequence + 1) & 0xffffffff
            self.transport.sendto(packet.encode(), peer)

    def flush(self, peer, session):
        # One unacknowledged event preserves order even when UDP reorders packets.
        if session.pending is None and session.outgoing:
            packet = session.outgoing.popleft()
            wire = packet.encode()
            session.pending = Pending(packet.sequence, wire, self.clock() + 1)
            self.transport.sendto(wire, peer)

    def acknowledgement(self, sequence):
        return Packet(0, flags=ACK, sender=self.port, acknowledgement=sequence).encode()

    def datagram_received(self, data, peer):
        try:
            for response in self.receive(data, peer):
                self.transport.sendto(response, peer)
        except (ValueError, UnicodeError, struct.error):
            LOG.debug('Rejected malformed SNAP datagram')

    def receive(self, data, peer):
        now = self.clock()
        if peer in self.sessions and self.sessions[peer].expires <= now:
            self.drop(peer, 'timeout')
        packets = decode_datagram(data)
        session = self.sessions.get(peer)
        if (session and session.connected
                and all(packet.kind & 127 not in (44, 65, 1) for packet in packets)):
            if any(packet.sender != session.user for packet in packets):
                return []
            session.expires = now + 120
            for packet in packets:
                if (packet.flags & ACK and session.pending
                        and packet.acknowledgement == session.pending.sequence):
                    session.pending = None
                    self.flush(peer, session)
            if any(packet.flags & RELIABLE for packet in packets):
                return self.receive_reliable(session, packets, peer, now)
        responses = []
        for packet in packets:
            responses.extend(self.handle(packet, peer, now))
        return responses

    def receive_reliable(self, session, packets, peer, now):
        # Aggregated native frames share the first nonzero reliable sequence.
        sequence = next((packet.sequence for packet in packets
                         if packet.flags & RELIABLE and packet.sequence), 0)
        fingerprint = tuple((packet.kind, packet.body, packet.flags & ~(MORE | ACK))
                            for packet in packets)
        if sequence in session.replies:
            previous, responses = session.replies[sequence]
            return responses if previous == fingerprint else []
        distance = (sequence - session.next_incoming) & 0xffffffff
        if distance >= 0x80000000:
            return [self.acknowledgement(sequence)]
        if distance >= 64:
            return []
        previous = session.incoming.get(sequence)
        if previous and previous[0] != fingerprint:
            raise ValueError('Conflicting SNAP retransmission')
        session.incoming[sequence] = (fingerprint, packets)
        result = []
        while session.next_incoming in session.incoming:
            current = session.next_incoming
            fingerprint, frames = session.incoming.pop(current)
            responses = []
            for frame in frames:
                try:
                    responses.extend(self.handle(frame, peer, now))
                except (ValueError, UnicodeError, struct.error):
                    LOG.debug('Rejected malformed SNAP operation %d', frame.kind & 127)
            responses.append(self.acknowledgement(current))
            session.replies[current] = (fingerprint, responses)
            if len(session.replies) > 128:
                del session.replies[next(iter(session.replies))]
            session.next_incoming = (current + 1) & 0xffffffff
            result.extend(responses)
        return result

    def handle(self, packet, peer, now):
        kind = packet.kind & 127
        session = self.sessions.get(peer)
        if kind == 44:
            if len(packet.body) < 120:
                raise ValueError('Truncated SNAP authentication request')
            name = cstring(packet.body[:40])
            jid = cstring(packet.body[40:100])
            game = struct.unpack_from('>I', packet.body, 100)[0]
            if jid != name + '@ngage-auth' or game != 36280:
                return []
            credential = self.credentials.lookup(name, peer[0])
            if credential is None:
                return []
            if session and not session.accepted and (session.user, session.name) == (credential.user, credential.name):
                return [session.challenge]
            if len(self.sessions) >= 256 and peer not in self.sessions:
                return []
            if session:
                self.drop(peer, 'reauthentication')
            session = Session(credential.user, credential.name, packet.sender, secrets.token_bytes(32), now + 30)
            challenge = bytearray(276)
            # With an empty salt, the inner key is the SHA-1 verifier from XMPP.
            encrypted = encrypt(credential.key, session.nonce)
            struct.pack_into('>II', challenge, 136, len(encrypted), len(session.nonce))
            challenge[148:148 + len(encrypted)] = encrypted
            session.challenge = Packet(64, encrypt(SWAN_KEY, challenge), sender=self.port).encode()
            self.sessions[peer] = session
            return [session.challenge]
        if session is None:
            return []
        if kind == 65:
            credential = self.credentials.lookup(session.name, peer[0])
            if credential is None or credential.user != session.user:
                self.sessions.pop(peer)
                return []
            if packet.sender != session.client or len(packet.body) != 136:
                return []
            proof = decrypt(SWAN_KEY, packet.body)
            size = struct.unpack_from('>I', proof)[0]
            if size != len(session.nonce) or not hmac.compare_digest(proof[8:8 + size], session.nonce):
                return []
            if not session.accepted:
                accepted = bytearray(320)
                name = session.name.encode('ascii')
                accepted[:len(name)] = name
                struct.pack_into('>IIIII', accepted, 40, self.address, self.port, 0, 0,
                                 session.user)
                session.accepted = Packet(45, encrypt(SWAN_KEY, accepted), flags=0x7000,
                    sender=self.port, sequence=1, acknowledgement=packet.sequence).encode()
                session.expires = now + 120
                LOG.info('SNAP UDP authenticated account %d', session.user)
            return [session.accepted]
        if not session.accepted:
            return []
        if kind == 1:
            if packet.sender != session.client or len(packet.body) < 312:
                return []
            if cstring(packet.body[16:32]).casefold() != session.name.casefold():
                return []
            if struct.unpack_from('>I', packet.body, 32)[0] != 36280:
                return []
            session.connected = True
            session.next_ping = now + 30
            session.expires = now + 120
            return [Packet(41, struct.pack('>III', self.port, 0, session.user),
                           sender=self.port, sequence=2).encode()]
        if not session.connected or packet.sender != session.user:
            return []
        session.expires = now + 120
        if kind == 0:
            return []
        if self.application:
            LOG.debug('SNAP receive operation=%d account=%d sequence=%d',
                      packet.kind, session.user, packet.sequence)
            self.application.handle(packet, peer, now)
            return []
        LOG.info('SNAP UDP operation %d from account %d (%d bytes)',
                 kind, session.user, len(packet.body))
        return []
