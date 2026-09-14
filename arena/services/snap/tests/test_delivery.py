import unittest

from arena.services.snap.protocol import ACK, RELIABLE, Credentials, Packet, Session, SnapServer, decode_datagram


from arena.services.snap.tests.support import Transport


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
