import struct
import zlib
from arena.games.tomb_raider.replay import SNAPSHOT_SIZE, GHOST_HEADER, clip_inputs, time_checksum

def fixture_clip():
    snapshot = zlib.compress(bytes(SNAPSHOT_SIZE))
    inputs = bytes(range(251)) * 15
    return (struct.pack('<4I', 0, 0, 100, len(snapshot)) + snapshot
            + struct.pack('<I',100) + struct.pack('<H',len(inputs)) + inputs
            + struct.pack('<H',1) + b'\0') + (b'\1\0\0' * 15)

def fixture_ghost(milliseconds=4000, race_id=7):
    course = GHOST_HEADER.pack(race_id,1,0,1,0,0,7500,0,0,0,0x1234)
    course += struct.pack('<iii',0,0,1024)
    return course + struct.pack('<II',milliseconds,time_checksum(milliseconds)) + clip_inputs(fixture_clip())
