import struct
import tempfile
import unittest

from arena.codec import ProtocolError
from arena.replay import GHOST_HEADER, clip_inputs, read_clip, read_ghost, time_checksum
from arena.store import Store
from arena.server import Arena, Peer
from test_protocol import fixture_clip


def fixture_ghost(milliseconds=4000, race_id=7):
    course = GHOST_HEADER.pack(race_id,1,0,1,0,0,7500,0,0,0,0x1234)
    course += struct.pack('<iii',0,0,1024)
    return course + struct.pack('<II',milliseconds,time_checksum(milliseconds)) + clip_inputs(fixture_clip())


class ReplayTests(unittest.TestCase):
    def test_clip_and_ghost_have_distinct_snapshots(self):
        clip = fixture_clip()
        self.assertEqual(len(read_clip(clip).snapshot),12684)
        ghost = read_ghost(fixture_ghost())
        self.assertEqual(ghost.race_id,7)
        self.assertEqual(ghost.milliseconds,4000)
        self.assertEqual(ghost.replay[12:20],bytes(8))
        with self.assertRaises(ProtocolError):
            read_clip(ghost.replay)

    def test_recording_can_start_after_initial_snapshot(self):
        data = bytearray(fixture_clip())
        struct.pack_into('<3I',data,0,1500,1700,2000)
        clip = read_clip(data)
        self.assertEqual((clip.snapshot_frame,clip.first_frame,clip.last_frame),(1500,1700,2000))

    def test_checksum_matches_native_race_writer(self):
        self.assertEqual(time_checksum(701),3323542079)

    def test_corruption_and_truncation(self):
        data = fixture_ghost()
        for broken in (data[:30],data[:-1],data+b'x',data[:52]+b'\0'*4+data[56:]):
            with self.assertRaises(ProtocolError):
                read_ghost(broken)
        with self.assertRaises(ProtocolError):
            read_clip(fixture_clip()[:-1])

class RaceTests(unittest.TestCase):
    def test_revenge_selects_the_challenged_course_after_a_new_login(self):
        with tempfile.TemporaryDirectory() as path:
            store = Store(path)
            _,alice = store.login('Alice','test-a')
            _,bob = store.login('Bob','test-b')
            store.import_course('First',fixture_ghost(5000,7))
            store.import_course('Second',fixture_ghost(5000,8))
            alice_record = store.finish_race(alice,fixture_ghost(4000,8),'')
            store.start_challenge(bob,alice_record)
            bob_record = store.finish_race(bob,fixture_ghost(3000,8),'Good race')
            peer = Peer(user=alice)
            rows = Arena(store,None).directory(peer,915,'Bob,revenge')
            self.assertEqual(peer.race_id,8)
            self.assertEqual(rows[0].id,bob_record)
            self.assertEqual(rows[1].value3,8)
            store.close()

    def test_losing_reference_is_not_published_as_the_challengers_record(self):
        with tempfile.TemporaryDirectory() as path:
            store = Store(path)
            _,alice = store.login('Alice','test-a')
            _,bob = store.login('Bob','test-b')
            store.import_course('Caves',fixture_ghost(5000))
            recording = fixture_ghost(4000)
            alice_record = store.finish_race(alice,recording,'')
            challenge = store.start_challenge(bob,alice_record)
            # The client returns the downloaded opponent recording after an abandoned race.
            result = store.finish_race(bob,recording,'')
            self.assertEqual([r['name'] for r in store.leaders(7)],['Alice'])
            self.assertEqual(store.db.execute('SELECT points FROM league_events WHERE challenge_id=?',(challenge,)).fetchone()[0],-5)
            self.assertEqual(store.finish_race(bob,recording,''),result)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM league_events').fetchone()[0],1)
            store.close()

    def test_challenge_rank_message_and_monthly_trophies(self):
        with tempfile.TemporaryDirectory() as path:
            store = Store(path)
            _,alice = store.login('Alice','test-a')
            _,bob = store.login('Bob','test-b')
            reference = store.import_course('Caves',fixture_ghost(5000))
            alice_record = store.finish_race(alice,fixture_ghost(4000),'Alice run')
            challenge = store.start_challenge(bob,alice_record)
            store.finish_race(bob,fixture_ghost(3000),'Good race!')
            self.assertEqual([r['name'] for r in store.leaders(7)],['Bob','Alice'])
            self.assertEqual(store.messages(alice)[0]['body'],'Good race!')
            self.assertEqual(store.db.execute('SELECT points FROM league_events WHERE challenge_id=?',(challenge,)).fetchone()[0],10)
            with self.assertRaises(ValueError):
                store.finish_race(bob,fixture_ghost(3500),'Another run')
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM league_events').fetchone()[0],1)
            with store.db:
                store.db.execute("UPDATE league_events SET month='2003-10'")
            trophy, = store.trophies()
            self.assertEqual((trophy['name'],trophy['place'],trophy['points']),('Bob',1,10))
            self.assertIsNotNone(store.content(reference))
            store.close()

    def test_unpublished_or_changed_course_is_rejected(self):
        with tempfile.TemporaryDirectory() as path:
            store = Store(path)
            _,user = store.login('Alice','test-a')
            with self.assertRaises(ValueError):
                store.finish_race(user,fixture_ghost(),'Invalid')
            store.import_course('Caves',fixture_ghost())
            changed = bytearray(fixture_ghost())
            struct.pack_into('<i',changed,36,512)
            with self.assertRaises(ValueError):
                store.finish_race(user,bytes(changed),'Changed route')
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM race_results').fetchone()[0],0)
            store.close()
