from collections import defaultdict
from dataclasses import replace
import struct
import tempfile
import unittest

from arena.services.accounts.store import AccountStore
from arena.games.high_seize.protocol import BattleKind, BattleMessage, GameDecoder, GamePacket, GameSettings
from arena.games.high_seize.server import HighSeizeArena, HighSeizeStore
from arena.services.snap.protocol import ACK, RELIABLE, Credentials, Packet, Session, SnapServer, decode_datagram
from arena.games.high_seize.tests.fixtures import commander_wire


from arena.services.snap.tests.support import Transport


class HighSeizeServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
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
            commander = commander_wire(name=f'Commander {slot}'.encode(), slot=slot)
            self.game(peer, GamePacket(18, struct.pack('<HHI', 1, len(commander), slot) + commander, slot))
            self.game(peer, GamePacket(18, struct.pack('<HHI', 2, 0, slot), slot))
            self.game(peer, GamePacket(18, struct.pack('<HHI', 0x20, 0, slot), slot))
        self.assertEqual(room.phase, 'loading')
        for slot, peer in enumerate(self.peers, 1):
            self.game(peer, BattleMessage(BattleKind.SYNCHRONIZATION, source=slot).packet())
        self.assertEqual(room.phase, 'battle')
        return room

    def test_commander_changes_require_readiness_and_preserve_valid_data(self):
        room, _ = self.create_room()
        host, peer = self.peers
        member = room.members[host]
        first = commander_wire(b'First', control=1)
        self.game(host, GamePacket(18, struct.pack('<HHI', 1, len(first), 1) + first, 1))
        self.game(host, GamePacket(18, struct.pack('<HHI', 2, 0, 1), 1))
        self.game(host, GamePacket(18, struct.pack('<HHI', 0x20, 0, 1), 1))
        self.assertTrue(member.ready and member.team_ready)
        before = list(self.games[peer])
        malformed = b'CMM01\0' + bytes(1022)
        self.game(host, GamePacket(18, struct.pack('<HHI', 1, len(malformed), 1) + malformed, 1))
        self.assertEqual(self.games[peer], before)
        self.assertEqual(member.commander_data.name, b'First')
        self.assertTrue(member.ready and member.team_ready)
        second = commander_wire(b'A much longer captain name', control=2)
        self.game(host, GamePacket(18, struct.pack('<HHI', 1, len(second), 1) + second, 1))
        self.assertEqual(member.commander_data.name, b'A much longer captain name')
        self.assertFalse(member.ready or member.team_ready)
        self.assertEqual(self.games[peer][-1].body[8:], second)

    def test_started_match_retains_exact_commander_records(self):
        room = self.begin()
        rows = self.store.db.execute(
            'SELECT slot,commander FROM hs_players WHERE match_id=? ORDER BY slot', (room.match,)).fetchall()
        self.assertEqual([tuple(row) for row in rows], [
            (slot, commander_wire(name=f'Commander {slot}'.encode(), slot=slot)) for slot in (1, 2)])

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
        self.assertFalse(any(m.kind == BattleKind.MOVE_UNIT for m in self.battle_messages(peer)))
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

    def preview(self, identifier=1, turn=0):
        return BattleMessage(BattleKind.MOVE_UNIT, identifier, 1, turn, True, 0x38b32ca7, 0xc44c9358,
                             bytes.fromhex('03000000020000000100000002000000020000000100000002000000'))

    def test_undo_then_reselection_only_publishes_the_committed_move(self):
        room = self.begin()
        host, peer = self.peers
        before = self.battle_messages(peer)
        self.battle(host, self.preview())
        self.battle(host, BattleMessage(BattleKind.UNDO, 2, 1, 0))
        self.assertEqual(self.battle_messages(peer), before)
        self.assertFalse(room.moves)
        self.battle(host, self.preview(3))
        self.battle(host, BattleMessage(BattleKind.WAIT, 4, 1, 0, payload=struct.pack('<I', 3)))
        self.assertEqual([(m.kind, m.identifier) for m in self.battle_messages(peer)[len(before):]], [(0, 3), (5, 4)])
        self.assertEqual([tuple(r) for r in self.store.db.execute(
            'SELECT message_id,state FROM hs_events WHERE source=1 AND kind=0 ORDER BY ordinal')],
            [(1, 'undone'), (3, 'accepted')])

    def test_timeout_discards_preview_and_allows_movement_on_the_next_turn(self):
        room = self.begin()
        host, peer = self.peers
        room.settings = replace(room.settings, turn_time=10)
        self.application.turn_deadline(room, self.now)
        self.battle(host, self.preview())
        self.now += 10
        self.server.tick()
        self.drain()
        self.assertFalse(room.moves)
        self.assertEqual((room.turn, room.active), (1, 2))
        self.assertFalse(any(m.kind == BattleKind.MOVE_UNIT for m in self.battle_messages(peer)))
        self.battle(host, BattleMessage(BattleKind.WAIT, 2, 1, 0, payload=struct.pack('<I', 3)))
        self.assertEqual(self.battle_messages(host)[-1].kind, BattleKind.REJECTED)
        self.battle(peer, BattleMessage(BattleKind.END_TURN, 1, 2, 1))
        self.battle(host, self.preview(3, 2))
        self.battle(host, BattleMessage(BattleKind.WAIT, 4, 1, 2, payload=struct.pack('<I', 3)))
        moves = [m for m in self.battle_messages(peer) if m.kind == BattleKind.MOVE_UNIT]
        self.assertEqual(moves, [self.preview(3, 2)])
        self.assertFalse(room.moves)

    def test_manual_end_turn_discards_preview(self):
        room = self.begin()
        host, peer = self.peers
        self.battle(host, self.preview())
        self.battle(host, BattleMessage(BattleKind.END_TURN, 2, 1, 0))
        self.assertFalse(room.moves)
        self.assertEqual((room.turn, room.active), (1, 2))
        self.assertFalse(any(m.kind == BattleKind.MOVE_UNIT for m in self.battle_messages(peer)))
        self.assertEqual(self.store.db.execute('SELECT state FROM hs_events WHERE kind=0').fetchone()[0], 'undone')

    def test_move_without_tentative_flag_is_committed_immediately(self):
        room = self.begin()
        host, peer = self.peers
        move = replace(self.preview(), flag=False)
        self.battle(host, move)
        self.assertFalse(room.moves)
        self.assertEqual(self.battle_messages(peer)[-1], move)
        self.assertEqual(self.battle_messages(host)[-1].kind, BattleKind.ACCEPTED)
        self.assertEqual(self.store.db.execute('SELECT state FROM hs_events WHERE kind=0').fetchone()[0], 'accepted')

    def test_surrender_does_not_publish_a_tentative_move(self):
        room = self.begin()
        host, peer = self.peers
        self.battle(host, self.preview())
        self.battle(host, BattleMessage(BattleKind.SURRENDER, 2, 1, 0))
        self.now += 3
        self.server.tick()
        self.drain()
        self.assertEqual(room.phase, 'finished')
        self.assertFalse(room.moves)
        self.assertFalse(any(m.kind == BattleKind.MOVE_UNIT for m in self.battle_messages(peer)))
        self.assertEqual(self.store.db.execute('SELECT state FROM hs_events WHERE kind=0').fetchone()[0], 'undone')
        self.assertEqual(self.store.db.execute('SELECT winner_team FROM hs_matches').fetchone()[0], 1)

    def test_departure_and_recovery_discard_uncommitted_moves(self):
        room = self.begin()
        host, peer = self.peers
        self.battle(host, self.preview())
        self.send(host, 7, flags=0xb000)
        self.assertFalse(room.moves)
        self.assertFalse(any(m.kind == BattleKind.MOVE_UNIT for m in self.battle_messages(peer)))
        self.assertEqual(self.store.db.execute('SELECT state FROM hs_events WHERE kind=0').fetchone()[0], 'undone')
        for finish in (lambda match: self.store.finish(match, None, 'server shutdown'), lambda match: self.store.recover()):
            match = self.store.start(room.settings, room.members.values())
            self.store.event(match, self.preview(), 0, 'pending')
            finish(match)
            self.assertEqual(self.store.db.execute('SELECT state FROM hs_events WHERE match_id=?', (match,)).fetchone()[0], 'undone')

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
