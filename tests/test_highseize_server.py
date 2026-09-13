from collections import defaultdict
from dataclasses import replace
import struct
import tempfile
import unittest

from arena.ashen import AshenStore
from arena.highseize import BattleKind, BattleMessage, GameDecoder, GamePacket, GameSettings
from arena.highseize_server import HighSeizeArena, HighSeizeStore
from arena.snap import ACK, RELIABLE, Credentials, Packet, Session, SnapServer, decode_datagram


class Transport:
    def __init__(self):
        self.sent = []

    def sendto(self, wire, peer):
        self.sent.append((peer, wire))


class HighSeizeServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AshenStore(self.directory.name)
        self.now = 100
        self.store = HighSeizeStore(self.accounts.db, clock=lambda: self.now)
        self.application = HighSeizeArena(self.store)
        self.server = SnapServer(Credentials(), clock=lambda: self.now, application=self.application)
        self.transport = Transport()
        self.server.transport = self.transport
        self.server.schedule_tick = lambda: None
        self.peers = [('127.0.0.1', 2000), ('127.0.0.1', 2001)]
        self.sequence = defaultdict(int)
        self.decoders = {peer: GameDecoder() for peer in self.peers}
        self.controls = defaultdict(list)
        self.games = defaultdict(list)
        for peer, name in zip(self.peers, ('Host', 'Peer')):
            user = self.accounts.create_user(name, 'password')
            self.server.sessions[peer] = Session(user, name, peer[1], b'', 220,
                                                accepted=b'authenticated', connected=True)

    def tearDown(self):
        self.server.connection_lost(None)
        self.accounts.close()
        self.directory.cleanup()

    def drain(self):
        count = 0
        while self.transport.sent:
            peer, wire = self.transport.sent.pop(0)
            for packet in decode_datagram(wire):
                self.controls[peer].append(packet)
                if packet.kind == 15:
                    self.games[peer].extend(self.decoders[peer].decode(packet.body))
                if packet.flags & RELIABLE:
                    ack = Packet(0, flags=ACK, sender=self.server.sessions[peer].user,
                                 acknowledgement=packet.sequence)
                    self.server.datagram_received(ack.encode(), peer)
            count += 1
            self.assertLess(count, 1000, 'Server responses did not settle')

    def send(self, peer, kind, body=b'', flags=0xa000):
        sequence = self.sequence[peer]
        self.sequence[peer] += 1
        packet = Packet(kind, body, flags, self.server.sessions[peer].user, sequence)
        self.server.datagram_received(packet.encode(), peer)
        self.drain()
        return packet

    def game(self, peer, packet):
        for part in packet.encode(self.sequence[peer]):
            self.send(peer, 17, part)

    def create_room(self):
        host, peer = self.peers
        create = self.send(host, 4, b'Room'.ljust(16, b'\0') + bytes(28), 0xb000)
        room = self.application.room(host)
        self.send(host, 12, bytes(16))
        settings = GameSettings(2, 0, 0, 2, 30, 0xffffffff, 0, 0, False, True, 1, '', '')
        data = settings.encode()
        self.game(host, GamePacket(17, struct.pack('<HH', 1, len(data)) + data, 0xc1))
        self.send(peer, 6, struct.pack('>I', room.identifier) + bytes(20))
        self.send(peer, 12, bytes(16))
        self.game(peer, GamePacket(12, struct.pack('<I', 0xdeadbeef), 0xc1))
        return room, create

    def begin(self):
        room, _ = self.create_room()
        for slot, peer in enumerate(self.peers, 1):
            commander = b'CMM01\0' + bytes(1022)
            self.game(peer, GamePacket(18, struct.pack('<HHI', 1, len(commander), slot) + commander, slot))
            self.game(peer, GamePacket(18, struct.pack('<HHI', 2, 0, slot), slot))
            self.game(peer, GamePacket(18, struct.pack('<HHI', 0x20, 0, slot), slot))
        self.assertEqual(room.phase, 'loading')
        for slot, peer in enumerate(self.peers, 1):
            self.game(peer, BattleMessage(BattleKind.SYNCHRONIZATION, source=slot).packet())
        self.assertEqual(room.phase, 'battle')
        return room

    def battle(self, peer, message):
        self.game(peer, replace(message.packet(), destination=0))

    def battle_messages(self, peer):
        return [BattleMessage.decode(packet.body) for packet in self.games[peer] if packet.kind == 16]

    def test_idle_lobby_stays_connected_when_native_acknowledges_keepalives(self):
        host, _ = self.peers
        self.send(host, 71, flags=0xb000)
        for _ in range(5):
            self.now += 30
            self.server.tick()
            self.drain()
        self.assertIn(host, self.server.sessions)
        keepalives = [p for p in self.controls[host] if p.kind == 0 and p.flags & RELIABLE]
        self.assertEqual(len(keepalives), 5)

    def test_room_records_handshake_and_duplicate_creation(self):
        room, create = self.create_room()
        host, peer = self.peers
        self.assertEqual(len(self.application.rooms), 1)
        self.server.datagram_received(create.encode(), host)
        self.drain()
        self.assertEqual(len(self.application.rooms), 1)
        self.assertEqual(len(room.members), 2)
        for slot, client in enumerate(self.peers, 1):
            states = [p for p in self.games[client] if p.kind == 17]
            own = next(p.body[4:] for p in states if p.body[:2] == b'\2\0')
            self.assertEqual(struct.unpack_from('<I', own, 1)[0], slot)
            self.assertEqual(own[-2], slot == 1)
            settings = next(p.body[4:] for p in states if p.body[:2] == b'\3\0')
            self.assertEqual(GameSettings.decode(settings).mission, 'MPS1')
        self.send(peer, 73, bytes(30), 0xb000)
        listing = self.controls[peer][-2]
        self.assertEqual(listing.kind, 73)
        self.assertEqual(listing.body, struct.pack('>III', 0, 0, 0))

    def test_first_game_callback_follows_attachment_completion(self):
        self.create_room()
        for peer in self.peers:
            packets = self.controls[peer]
            attached = next(i for i, p in enumerate(packets)
                            if p.kind == 40 and p.body == struct.pack('>II', 12, 0))
            first_game = next(i for i, p in enumerate(packets) if p.kind == 15)
            self.assertGreater(first_game, attached)
            self.assertTrue(packets[first_game].flags & RELIABLE)

    def test_participant_sync_precedes_begin_on_both_clients(self):
        self.begin()
        for peer in self.peers:
            messages = self.battle_messages(peer)
            self.assertEqual([(m.kind, m.source, m.identifier) for m in messages],
                             [(26, 1, 0), (26, 2, 0), (23, 0, 0)])
            self.assertTrue(all(p.destination == 1 for p in self.games[peer] if p.kind == 16))

    def test_native_moves_attack_and_surrender_are_ordered_and_persisted_once(self):
        room = self.begin()
        host, peer = self.peers
        move = BattleMessage(BattleKind.MOVE_UNIT, 1, 1, 0, True, 0x38b32ca7, 0xc44c9358,
                             bytes.fromhex('03000000020000000100000002000000020000000100000002000000'))
        wait = BattleMessage(BattleKind.WAIT, 2, 1, 0, False, 0xc44c9358, 0xc44c9358, struct.pack('<I', 3))
        self.battle(host, move)
        self.assertFalse(any(m.kind == BattleKind.ACCEPTED for m in self.battle_messages(host)))
        self.battle(host, wait)
        accepts = [struct.unpack('<I', m.payload)[0] for m in self.battle_messages(host) if m.kind == 21]
        self.assertEqual(accepts, [1, 2])
        self.assertEqual(self.battle_messages(peer)[-2:], [move, wait])
        self.battle(host, BattleMessage(BattleKind.END_TURN, 4, 1, 0))
        self.assertEqual((room.turn, room.active), (1, 2))
        reverse = BattleMessage(BattleKind.MOVE_UNIT, 1, 2, 1, True, 0xab331a7, 0xf74c8e58,
                                bytes.fromhex('040000000300000002000000070000000200000006000000020000000500000002000000'))
        self.battle(peer, reverse)
        self.battle(peer, BattleMessage(BattleKind.WAIT, 2, 2, 1, False, 0xf74c8e58, 0xf74c8e58, struct.pack('<I', 4)))
        self.battle(peer, BattleMessage(BattleKind.END_TURN, 4, 2, 1))
        self.battle(host, BattleMessage(BattleKind.END_TURN, 6, 1, 2))
        approach = BattleMessage(BattleKind.MOVE_UNIT, 5, 2, 3, True, 0x8b233a7, 0xf64d8c58,
                                 bytes.fromhex('04000000020000000100000005000000020000000400000002000000'))
        attack = BattleMessage(BattleKind.ATTACK_UNIT, 6, 2, 3, False, 0xf64d8c58, 0xf64d8d74,
                               bytes.fromhex('0400000022000000'))
        self.battle(peer, approach)
        self.battle(peer, attack)
        self.assertEqual(self.battle_messages(host)[-2:], [approach, attack])
        surrender = BattleMessage(BattleKind.SURRENDER, 7, 2, 3)
        self.battle(peer, surrender)
        self.battle(peer, surrender)
        self.now += 3
        self.server.tick()
        self.drain()
        self.assertEqual(room.phase, 'finished')
        for client in self.peers:
            end = self.battle_messages(client)[-1]
            self.assertEqual((end.kind, end.source, end.payload), (25, 0, struct.pack('<I', 2)))
        db = self.store.db
        self.assertEqual(db.execute('SELECT COUNT(*) FROM hs_matches').fetchone()[0], 1)
        authority = [tuple(r) for r in db.execute(
            'SELECT kind,message_id FROM hs_events WHERE source=0 ORDER BY ordinal')]
        self.assertEqual(authority, [(23, 0), (10, 1), (10, 2), (10, 3), (25, 4)])
        self.assertEqual([tuple(r) for r in db.execute('SELECT slot,outcome FROM hs_players ORDER BY slot')],
                         [(1, 'win'), (2, 'loss')])
        self.assertEqual(db.execute('SELECT COUNT(*) FROM hs_events WHERE kind=16').fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM hs_events WHERE state='pending'").fetchone()[0], 0)
        self.assertFalse(self.store.finish(room.match, 1, 'duplicate'))
        self.assertEqual(db.execute('SELECT winner_team FROM hs_matches').fetchone()[0], 0)
        self.send(host, 7, flags=0xb000)
        self.send(peer, 7, flags=0xb000)
        self.assertFalse(self.application.rooms)
        self.assertFalse(self.application.memberships)

    def test_spoofed_source_and_wrong_turn_do_not_change_match(self):
        room = self.begin()
        host, peer = self.peers
        self.battle(peer, BattleMessage(BattleKind.SURRENDER, 1, 1, 0))
        self.battle(peer, BattleMessage(BattleKind.SURRENDER, 1, 2, 0))
        self.battle(host, BattleMessage(BattleKind.SURRENDER, 1, 1, 3))
        self.assertEqual(room.phase, 'battle')
        self.assertFalse(any(m.defeated for m in room.members.values()))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM hs_events WHERE kind=16').fetchone()[0], 0)
        self.assertEqual(self.battle_messages(host)[-1].kind, BattleKind.REJECTED)

    def test_deadline_host_departure_and_restart_do_not_leave_live_matches(self):
        room = self.begin()
        host, peer = self.peers
        room.settings = replace(room.settings, turn_time=10)
        self.application.turn_deadline(room, self.now)
        self.now += 10
        self.server.tick()
        self.drain()
        self.assertEqual((room.turn, room.active), (1, 2))
        self.send(host, 7, flags=0xb000)
        self.now += 3
        self.server.tick()
        self.drain()
        self.assertEqual(room.phase, 'finished')
        self.assertEqual(self.store.db.execute('SELECT winner_team FROM hs_matches').fetchone()[0], 1)
        self.store.start(room.settings, room.members.values())
        self.store.recover()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM hs_matches WHERE ended IS NULL').fetchone()[0], 0)


class SnapDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.peer = ('127.0.0.1', 2000)
        self.server = SnapServer(Credentials(), clock=lambda: self.now)
        self.server.sessions[self.peer] = Session(1, 'Host', 2000, b'', 220,
                                                  accepted=b'authenticated', connected=True)
        self.transport = Transport()
        self.server.transport = self.transport
        self.server.schedule_tick = lambda: None

    def test_lost_ack_retries_identical_event_and_preserves_queue_order(self):
        self.server.send(self.peer, 15, b'first')
        self.server.send(self.peer, 15, b'second')
        self.assertEqual(len(self.transport.sent), 1)
        first = self.transport.sent[0][1]
        self.now += 1
        self.server.tick()
        self.assertEqual([wire for _, wire in self.transport.sent], [first, first])
        packet = decode_datagram(first)[0]
        self.server.datagram_received(Packet(0, flags=ACK, sender=1,
                                             acknowledgement=packet.sequence).encode(), self.peer)
        self.assertEqual(decode_datagram(self.transport.sent[-1][1])[0].body, b'second')
        self.server.datagram_received(Packet(0, flags=ACK, sender=1,
                                             acknowledgement=packet.sequence).encode(), self.peer)
        self.assertIsNotNone(self.server.sessions[self.peer].pending)

    def test_native_reliable_sequence_starts_at_zero_and_excludes_heartbeats(self):
        # snapcomm 0x10002526 resets the receive sequence; 0x10008b58 requires equality.
        self.server.send(self.peer, 15, b'heartbeat', reliable=False)
        self.server.send(self.peer, 71, b'lobby')
        first = decode_datagram(self.transport.sent[-1][1])[0]
        self.assertEqual(first.sequence, 0)
        self.server.send(self.peer, 15, b'heartbeat', reliable=False)
        self.server.send(self.peer, 73, b'rooms')
        self.server.datagram_received(Packet(0, flags=ACK, sender=1, acknowledgement=0).encode(), self.peer)
        second = decode_datagram(self.transport.sent[-1][1])[0]
        self.assertEqual((second.kind, second.sequence), (73, 1))

    def test_reordered_input_and_duplicates_apply_each_operation_once(self):
        calls = []
        class Application:
            def handle(self, packet, peer, now):
                calls.append(packet.body)
        self.server.application = Application()
        first = Packet(17, b'first', RELIABLE, 1, 0).encode()
        second = Packet(17, b'second', RELIABLE, 1, 1).encode()
        self.assertEqual(self.server.receive(second, self.peer), [])
        self.assertFalse(calls)
        replies = self.server.receive(first, self.peer)
        self.assertEqual(calls, [b'first', b'second'])
        self.assertEqual([decode_datagram(r)[0].acknowledgement for r in replies], [0, 1])
        self.server.receive(first, self.peer)
        self.server.receive(second, self.peer)
        self.assertEqual(calls, [b'first', b'second'])

    def test_native_aggregate_uses_one_sequence_and_applies_all_frames(self):
        calls = []
        class Application:
            def handle(self, packet, peer, now):
                calls.append(packet.kind)
        self.server.application = Application()
        wire = bytes.fromhex('a818000800000001000000030000000041524e4100000000'
                             'a018010800000001000000000000000041524e4200000000'
                             'a018020800000001000000000000000041524e4300000000'
                             'a018030800000001000000000000000041524e4400000000ba476611')
        self.server.sessions[self.peer].next_incoming = 3
        reply, = self.server.receive(wire, self.peer)
        self.assertEqual(calls, [8, 0x108, 0x208, 0x308])
        self.assertEqual(decode_datagram(reply)[0].acknowledgement, 3)
        self.server.receive(wire, self.peer)
        self.assertEqual(len(calls), 4)

    def test_missing_ack_expires_peer_and_releases_pending_events(self):
        self.server.send(self.peer, 15, b'first')
        for _ in range(6):
            self.now += 8
            self.server.tick()
        self.assertNotIn(self.peer, self.server.sessions)
