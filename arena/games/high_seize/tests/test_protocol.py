import struct
import unittest
from dataclasses import replace

from arena.games.high_seize.protocol import (BattleKind, BattleMessage, GameDecoder, GamePacket,
                             GameSettings, Player, encode_players)


class HighSeizeBattleMessageTests(unittest.TestCase):
    def test_native_initialization_and_end_turn(self):
        synchronization = bytes.fromhex(
            '190000001a000000000000000200000000000000000000000000000000')
        end_turn = bytes.fromhex(
            '190000000a000000070000000100000004000000000000000000000000')
        self.assertEqual(BattleMessage.decode(synchronization),
                         BattleMessage(BattleKind.SYNCHRONIZATION, source=2))
        message = BattleMessage(BattleKind.END_TURN, 7, 1, 4)
        self.assertEqual(BattleMessage.decode(end_turn), message)
        self.assertEqual(message.encode(), end_turn)

    def test_server_begin_and_termination_use_receiver_routing_flag(self):
        begin = BattleMessage(BattleKind.BEGIN).packet()
        self.assertEqual(begin, GamePacket(16, bytes.fromhex(
            '1900000017000000000000000000000000000000000000000000000000'), 0, 1))
        end = bytes.fromhex(
            '1d0000001900000066000000000000000600000000000000000000000000000000')
        message = BattleMessage(BattleKind.END_GAME, 102, 0, 6, payload=bytes(4))
        self.assertEqual(message.encode(), end)
        self.assertEqual(BattleMessage.decode(end), message)

    def test_malformed_native_battle_headers_are_rejected(self):
        wire = bytes.fromhex(
            '190000001a000000000000000200000000000000000000000000000000')
        for malformed in (wire[:28], wire + b'\0', wire[:4] + b'\4' + wire[5:],
                          wire[:12] + b'\5' + wire[13:],
                          wire[:20] + b'\2' + wire[21:]):
            with self.subTest(wire=malformed.hex()), self.assertRaises(ValueError):
                BattleMessage.decode(malformed)


class HighSeizeSettingsTests(unittest.TestCase):
    def test_native_settings_field_offsets(self):
        wire = bytes.fromhex('020000000600000000000000020000001e00000032000000'
                             '0100000000000000000101000000')
        wire += b'Room'.ljust(32, b'\0') + b'MPS1'.ljust(128, b'\0')
        settings = GameSettings(2, 6, 0, 2, 30, 50, 1, 0, False, True, 1, 'Room', 'MPS1')
        self.assertEqual(len(wire), 198)
        self.assertEqual(GameSettings.decode(wire), settings)
        self.assertEqual(settings.encode(), wire)
        for malformed in (wire[:-1], wire[:70] + b'X' * 128,
                          wire[:32] + b'\2' + wire[33:]):
            with self.assertRaises(ValueError):
                GameSettings.decode(malformed)

    def test_resolves_mission_from_native_style_player_count_and_selection(self):
        request = GameSettings(2, 0, 0, 2, 30, 50, 0, 0, False, False, 1, 'H', '')
        result = request.resolve('High Seize', 1)
        self.assertEqual((result.game_type, result.host, result.name, result.mission),
                         (6, 1, 'High Seize', 'MPS1'))
        self.assertEqual(replace(request, players=4).resolve('Room', 1).mission, 'MPS19')
        self.assertEqual(replace(request, style=3, players=4, map_index=3)
                         .resolve('Room', 1).mission, 'MPN34')
        for invalid in (replace(request, players=1), replace(request, style=0),
                        replace(request, map_index=14)):
            with self.assertRaises(ValueError):
                invalid.resolve('Room', 1)


class HighSeizePlayerTests(unittest.TestCase):
    def test_slot_team_and_host_have_distinct_fields(self):
        wire = Player(2, 'Peer', team=1).encode()
        self.assertEqual(len(wire), 51)
        self.assertEqual(wire[:13], bytes.fromhex('00020000000100000000000000'))
        self.assertEqual(wire[13:45], b'Peer'.ljust(32, b'\0'))
        self.assertEqual(wire[45:], bytes(6))
        self.assertEqual(Player(1, 'Host', host=True).encode()[-2:], b'\1\0')

    def test_native_linked_list_is_nested_before_current_fields(self):
        host, peer = Player(1, 'Host', host=True), Player(2, 'Peer', team=1)
        wire = encode_players([host, peer])
        self.assertEqual(wire, b'\1' + peer.encode() + host.encode()[1:])
        self.assertEqual(encode_players([]), b'')
        with self.assertRaises(ValueError):
            encode_players([host, host])
        for player in (Player(0, 'Invalid'), Player(5, 'Invalid'),
                       Player(1, 'Invalid', team=4), Player(1, 'a\0b')):
            with self.subTest(player=player), self.assertRaises(ValueError):
                player.encode()


class HighSeizePacketTests(unittest.TestCase):
    def test_native_host_announcement(self):
        wire = bytes.fromhex('11000000000e00fe0cc104000000fe0000afdeadde')
        packet = GamePacket(12, bytes.fromhex('afdeadde'), 193)
        self.assertEqual(GameDecoder().decode(wire), [packet])
        self.assertEqual(packet.encode(), [wire])

    def test_multipart_layout_and_out_of_order_duplicate(self):
        first = bytes.fromhex('11000000010700000002000800fe110004fe000000')
        last = bytes.fromhex('0f00000001070001000800fe000061fe626364')
        decoder = GameDecoder()
        self.assertEqual(decoder.decode(last), [])
        self.assertEqual(decoder.decode(last), [])
        self.assertEqual(decoder.decode(first), [GamePacket(17, b'abcd')])
        self.assertFalse(decoder.fragments)

    def test_odd_payload_splits_after_floor_half(self):
        # DataPartition uses integer division before inserting its second marker.
        wire = bytes.fromhex('10000000000d00fe1100030000fe000000616263')
        packet = GamePacket(17, b'abc')
        self.assertEqual(packet.encode(), [wire])
        self.assertEqual(GameDecoder().decode(wire), [packet])

    def test_commander_sized_packet_fragments_at_native_boundary(self):
        packet = GamePacket(18, bytes(1036), 1)
        first, last = packet.encode(message_id=1)
        self.assertEqual(first[:14], bytes.fromhex('0b030000010100000002000203fe'))
        self.assertEqual(last[:12], bytes.fromhex('1d01000001010001001601fe'))
        decoder = GameDecoder()
        self.assertEqual(decoder.decode(first), [])
        self.assertEqual(decoder.decode(last), [packet])

    def test_empty_stream_and_multiple_partitions(self):
        self.assertEqual(GameDecoder().decode(bytes(4)), [])
        ping = GamePacket(11, bytes(4))
        state = GamePacket(17, bytes.fromhex('04000000'))
        parts = ping.encode()[0][4:] + state.encode()[0][4:]
        self.assertEqual(GameDecoder().decode(struct.pack('<I', len(parts)) + parts), [ping, state])

    def test_rejects_malformed_lengths_markers_and_conflicts(self):
        wire = bytes.fromhex('11000000000e00fe0cc104000000fe0000afdeadde')
        for malformed in (wire[:3], wire[:-1], wire[:7] + b'\0' + wire[8:],
                          wire[:10] + b'\x05' + wire[11:],
                          bytes.fromhex('070000000107000000ffff')):
            with self.subTest(wire=malformed.hex()), self.assertRaises(ValueError):
                GameDecoder().decode(malformed)
        first, _ = GamePacket(18, bytes(1036), 1).encode(message_id=1)
        decoder = GameDecoder()
        decoder.decode(first)
        with self.assertRaises(ValueError):
            decoder.decode(first[:-1] + b'\1')
        self.assertFalse(decoder.fragments)

    def test_message_and_pending_fragment_limits(self):
        with self.assertRaises(ValueError):
            GamePacket(18, bytes(4101)).encode()
        decoder = GameDecoder()
        for ident in range(8):
            decoder.decode(GamePacket(18, bytes(1036)).encode(ident)[0])
        with self.assertRaises(ValueError):
            decoder.decode(GamePacket(18, bytes(1036)).encode(8)[0])
