import hashlib
import struct
import unittest

from Crypto.Cipher import Blowfish

from arena.services.snap.protocol import Credentials, Packet, SnapServer, decode_datagram


class SnapCodecTests(unittest.TestCase):
    def test_native_lobby_query_and_aggregated_join(self):
        query = bytes.fromhex('b0100047000000010000000000000000ba476611')
        self.assertEqual(decode_datagram(query), [Packet(71, flags=0xb000, sender=1)])
        self.assertEqual(decode_datagram(query)[0].encode(), query)
        joined = bytes.fromhex('a814000d000000010000000100000000e1e00501'
                               'b014000600000001000000000000000000000000ba476611')
        frames = decode_datagram(joined)
        self.assertEqual([(frame.kind, frame.body) for frame in frames],
                         [(13, bytes.fromhex('e1e00501')), (6, bytes(4))])
        attributes = bytes.fromhex(
            'a818000800000001000000030000000041524e4100000000'
            'a018010800000001000000000000000041524e4200000000'
            'a018020800000001000000000000000041524e4300000000'
            'a018030800000001000000000000000041524e4400000000ba476611')
        self.assertEqual([frame.kind for frame in decode_datagram(attributes)],
                         [8, 0x108, 0x208, 0x308])

    def test_rejects_incomplete_frames_and_inconsistent_aggregation(self):
        data = Packet(71).encode()
        malformed = [data[:19], data[:-1], data[:-4] + b'junk',
                     bytes.fromhex('3011') + data[2:],
                     bytes.fromhex('300f') + data[2:],
                     bytes.fromhex('3810') + data[2:],
                     data[:-4] + data]
        for wire in malformed:
            with self.subTest(wire=wire.hex()), self.assertRaises(ValueError):
                decode_datagram(wire)


class SnapAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.peer = ('127.0.0.1', 2000)
        self.credentials = Credentials()
        self.credentials.remember('xmpp', 17, 'Native', hashlib.sha1(b'password').hexdigest(), self.peer[0])
        self.server = SnapServer(self.credentials, clock=lambda: self.now)
        body = b'Native'.ljust(40, b'\0') + b'Native@ngage-auth'.ljust(60, b'\0')
        body += struct.pack('>IIIIIH2sI2sI', 36280, 0, 0, 2000, 2, 2, b'LC', 100, b'MR', 10)
        self.login = Packet(44, body, sender=2000).encode()

    def challenge_proof(self):
        challenge, = self.server.receive(self.login, self.peer)
        packet, = decode_datagram(challenge)
        self.assertEqual(packet.kind, 64)
        body = Blowfish.new(b'SNAP-SWAN', Blowfish.MODE_ECB).decrypt(packet.body)
        status, salt_size = struct.unpack_from('>II', body)
        self.assertEqual(status, 0)
        size, actual = struct.unpack_from('>II', body, 136)
        key = hashlib.sha1(b'password' + body[8:8 + salt_size]).digest()
        nonce = Blowfish.new(key, Blowfish.MODE_ECB).decrypt(body[148:148 + size])[:actual]
        proof = struct.pack('>II', actual, 0) + nonce.ljust(128, b'\0')
        ciphertext = Blowfish.new(b'SNAP-SWAN', Blowfish.MODE_ECB).encrypt(proof)
        return challenge, Packet(65, ciphertext, flags=0xb000, sender=2000).encode()

    def test_two_phase_login_and_retransmission(self):
        challenge, proof = self.challenge_proof()
        self.assertEqual(self.server.receive(self.login, self.peer), [challenge])
        reply, = self.server.receive(proof, self.peer)
        packet, = decode_datagram(reply)
        self.assertEqual((packet.kind, packet.flags, packet.sequence, packet.acknowledgement),
                         (45, 0x7000, 1, 0))
        accepted = Blowfish.new(b'SNAP-SWAN', Blowfish.MODE_ECB).decrypt(packet.body)
        self.assertEqual(accepted[:40].split(b'\0')[0], b'Native')
        self.assertEqual(struct.unpack_from('>IIIII', accepted, 40), (0x7f000001, 9090, 0, 0, 17))
        self.assertEqual(self.server.receive(proof, self.peer), [reply])
        body = bytearray(326)
        body[16:22] = b'Native'
        struct.pack_into('>I', body, 32, 36280)
        connected, = self.server.receive(Packet(1, body, sender=2000).encode(), self.peer)
        packet, = decode_datagram(connected)
        self.assertEqual((packet.kind, struct.unpack('>III', packet.body)), (41, (9090, 0, 17)))

    def test_wrong_proof_peer_expiry_and_revoked_credentials(self):
        _, proof = self.challenge_proof()
        self.assertEqual(self.server.receive(proof, ('127.0.0.1', 2001)), [])
        wrong = Packet(65, bytes(136), flags=0xb000, sender=2000).encode()
        self.assertEqual(self.server.receive(wrong, self.peer), [])
        self.now += 31
        self.assertEqual(self.server.receive(proof, self.peer), [])
        self.assertEqual(self.server.receive(self.login, ('127.0.0.2', 2000)), [])
        self.credentials.forget('xmpp')
        self.assertEqual(self.server.receive(self.login, self.peer), [])

    def test_challenges_are_new_after_expiry(self):
        first, proof = self.challenge_proof()
        self.now += 31
        second, _ = self.challenge_proof()
        self.assertNotEqual(first, second)
        self.assertEqual(self.server.receive(proof, self.peer), [])

    def test_pending_challenge_cannot_complete_after_xmpp_logout(self):
        _, proof = self.challenge_proof()
        self.credentials.forget('xmpp')
        self.assertEqual(self.server.receive(proof, self.peer), [])
        self.assertNotIn(self.peer, self.server.sessions)
