"""Tomb Raider's native Director's Cut and Shadow Race file containers."""
from dataclasses import dataclass
import struct
import zlib

from .codec import ProtocolError

SNAPSHOT_SIZE = 12684
GHOST_HEADER = struct.Struct('<IHHHIIIiiiH')


@dataclass(frozen=True)
class Clip:
    snapshot_frame: int
    first_frame: int
    last_frame: int
    snapshot: bytes


def read_clip(data):
    if len(data) < 20:
        raise ProtocolError('truncated replay header')
    snapshot_frame, first, last, packed_size = struct.unpack_from('<4I', data)
    if last <= first or last - first > 1000000 or not 0 < packed_size <= len(data) - 20:
        raise ProtocolError('invalid replay header')
    try:
        unpacker = zlib.decompressobj()
        snapshot = unpacker.decompress(data[16:16 + packed_size], SNAPSHOT_SIZE + 1)
    except zlib.error as error:
        raise ProtocolError('invalid compressed replay snapshot') from error
    if len(snapshot) != SNAPSHOT_SIZE or not unpacker.eof or unpacker.unused_data:
        raise ProtocolError('invalid replay snapshot size')
    end = read_input_streams(data, 16 + packed_size)
    if end < len(data):
        if len(data) < end + 4 or struct.unpack_from('<I', data, end)[0] != 1234:
            raise ProtocolError('invalid replay camera marker')
        end += 4
        for _ in range(5):
            if len(data) < end + 2:
                raise ProtocolError('truncated camera stream')
            size, = struct.unpack_from('<H', data, end)
            end += 2
            if size > 5000 or len(data) < end + size:
                raise ProtocolError('invalid camera stream length')
            end += size
    if end != len(data):
        raise ProtocolError('unexpected replay data')
    return Clip(snapshot_frame, first, last, snapshot)


def read_input_streams(data, offset):
    if len(data) < offset + 4:
        raise ProtocolError('truncated replay input header')
    offset += 4
    for _ in range(17):
        if len(data) < offset + 2:
            raise ProtocolError('truncated replay stream length')
        size, = struct.unpack_from('<H', data, offset)
        offset += 2
        if size > 5000 or len(data) < offset + size:
            raise ProtocolError('invalid replay stream length')
        offset += size
    return offset


def clip_inputs(data):
    clip = read_clip(data)
    packed_size, = struct.unpack_from('<I', data, 12)
    offset = 16 + packed_size
    end = read_input_streams(data, offset)
    return data[:12] + clip.snapshot[-8:] + data[offset:end]


def time_checksum(milliseconds):
    value = milliseconds ^ 0x78532369
    value = ((value & 0x33333333) << 2) | ((value & 0xcccccccc) >> 2)
    value = (value - 0x452a0ff3) & 0xffffffff
    return ((value & 0x01010101) << 7) | ((value & 0xfefefefe) >> 1)


@dataclass(frozen=True)
class Ghost:
    race_id: int
    level: int
    checkpoint_count: int
    milliseconds: int
    course: bytes
    replay: bytes


def read_ghost(data):
    if len(data) < GHOST_HEADER.size:
        raise ProtocolError('truncated race header')
    race_id, level, room, count, rotation, excluded_items, limit_frames, x, y, z, magic = GHOST_HEADER.unpack_from(data)
    if magic != 0x1234 or not 1 <= count <= 50 or not 1 <= level <= 15:
        raise ProtocolError('invalid race description')
    offset = GHOST_HEADER.size + count * 12
    if len(data) < offset + 28:
        raise ProtocolError('truncated race checkpoints')
    milliseconds, checksum = struct.unpack_from('<II', data, offset)
    if not 0 < milliseconds <= 86400000 or checksum != time_checksum(milliseconds):
        raise ProtocolError('invalid race time checksum')
    replay = data[offset + 8:]
    if len(replay) < 24:
        raise ProtocolError('truncated ghost replay')
    start, first, last = struct.unpack_from('<3I', replay)
    if last <= first or last - first > 1000000:
        raise ProtocolError('invalid ghost replay frame range')
    if read_input_streams(replay, 20) != len(replay):
        raise ProtocolError('unexpected ghost replay data')
    return Ghost(race_id, level, count, milliseconds, data[:offset], replay)
