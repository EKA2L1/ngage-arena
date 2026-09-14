"""High Seize's little-endian game packets inside SNAP dedicated-server data."""

from dataclasses import dataclass, replace
from enum import IntEnum
import struct

HEADER = struct.Struct('<BBHI')
MAX_PACKET_SIZE = 4096 + 12
PART_SIZE = 768
SETTINGS = struct.Struct('<8IBBI32s128s')
BATTLE_HEADER = struct.Struct('<IIIIIBII')
MISSIONS = {
    (2, 2): tuple(f'MPS{i}' for i in range(1, 15)),
    (2, 3): tuple(f'MPS{i}' for i in range(15, 19)),
    (2, 4): tuple(f'MPS{i}' for i in range(19, 23)),
    (3, 2): ('MPN23', 'MPN26', 'MPN29', 'MPN32'),
    (3, 3): ('MPN24', 'MPN27', 'MPN30', 'MPN33'),
    (3, 4): ('MPN25', 'MPN28', 'MPN31', 'MPN34'),
}


class BattleKind(IntEnum):
    MOVE_UNIT = 0
    ATTACK_UNIT = 1
    ATTACK_TERRAIN = 2
    ATTACK_AREA = 3
    WAIT = 5
    CAPTURE_PROPERTY = 6
    CONSTRUCT_UNIT = 7
    FLUSH = 8
    UNDO = 9
    END_TURN = 10
    LOAD = 11
    UNLOAD = 12
    JOIN = 13
    SUPPLY = 14
    USE_PERK = 15
    SURRENDER = 16
    SELECT_OBJECT = 17
    UNIT_CONSTRUCT_UNIT = 18
    SAVE = 19
    UI_ELEMENT_CLICK = 20
    ACCEPTED = 21
    REJECTED = 22
    BEGIN = 23
    BREAK_ALLIANCE = 24
    END_GAME = 25
    SYNCHRONIZATION = 26


@dataclass(frozen=True)
class BattleMessage:
    kind: BattleKind
    identifier: int = 0
    source: int = 0
    turn: int = 0
    flag: bool = False
    pre_crc: int = 0
    post_crc: int = 0
    payload: bytes = b''

    @classmethod
    def decode(cls, data):
        if not BATTLE_HEADER.size <= len(data) <= MAX_PACKET_SIZE - HEADER.size:
            raise ValueError('Invalid High Seize battle message size')
        size, kind, ident, source, turn, flag, pre, post = BATTLE_HEADER.unpack_from(data)
        if size != len(data) - 4 or source > 4 or flag not in (0, 1):
            raise ValueError('Invalid High Seize battle header')
        return cls(BattleKind(kind), ident, source, turn, bool(flag), pre, post,
                   data[BATTLE_HEADER.size:])

    def encode(self):
        body = BATTLE_HEADER.pack(BATTLE_HEADER.size - 4 + len(self.payload), self.kind,
                                  self.identifier, self.source, self.turn, self.flag,
                                  self.pre_crc, self.post_crc) + self.payload
        self.decode(body)
        return body

    def packet(self):
        # The native receiver uses bit 0 to classify a server-delivered message.
        return GamePacket(16, self.encode(), self.source, 1)


@dataclass(frozen=True)
class GameSettings:
    style: int
    game_type: int
    matchup: int
    players: int
    skill_points: int
    turn_time: int
    host: int
    map_index: int
    ranked: bool
    fog: bool
    commander_mode: int
    name: str
    mission: str

    @classmethod
    def decode(cls, data):
        if len(data) != SETTINGS.size:
            raise ValueError('Invalid High Seize settings size')
        values = SETTINGS.unpack(data)
        if values[8] not in (0, 1) or values[9] not in (0, 1):
            raise ValueError('Invalid High Seize settings flags')
        strings = []
        for raw in values[-2:]:
            value, separator, _ = raw.partition(b'\0')
            if not separator:
                raise ValueError('Unterminated High Seize settings string')
            strings.append(value.decode('ascii'))
        return cls(*values[:-2], *strings)

    def encode(self):
        name, mission = self.name.encode('ascii'), self.mission.encode('ascii')
        if len(name) > 31 or len(mission) > 127 or b'\0' in name + mission:
            raise ValueError('Invalid High Seize settings string')
        return SETTINGS.pack(self.style, self.game_type, self.matchup, self.players,
                             self.skill_points, self.turn_time, self.host, self.map_index,
                             self.ranked, self.fog, self.commander_mode, name, mission)

    def resolve(self, name, host):
        missions = MISSIONS.get((self.style, self.players), ())
        if not 0 <= self.map_index < len(missions) or not 1 <= host <= 4:
            raise ValueError('Invalid High Seize room settings')
        return replace(self, game_type=6, host=host, name=name,
                       mission=missions[self.map_index])


@dataclass(frozen=True)
class Player:
    slot: int
    name: str
    team: int = 0
    skill_points: int = 0
    nationality: int = 0
    host: bool = False

    def encode(self, following=b''):
        name = self.name.encode('ascii')
        if not 1 <= self.slot <= 4 or not 0 <= self.team < 4:
            raise ValueError('Invalid High Seize player slot or team')
        if not name or len(name) > 31 or b'\0' in name:
            raise ValueError('Invalid High Seize player name')
        # The linked-list base serializes the following player before this one.
        return (bytes((bool(following),)) + following
                + struct.pack('<III32sIBB', self.slot, self.team, self.skill_points,
                              name, self.nationality, self.host, 0))


def encode_players(players):
    if len(players) > 4 or len({player.slot for player in players}) != len(players):
        raise ValueError('Invalid High Seize player list')
    following = b''
    for player in reversed(players):
        following = player.encode(following)
    return following


@dataclass(frozen=True)
class GamePacket:
    kind: int
    body: bytes = b''
    source: int = 0
    destination: int = 0

    def encode(self, message_id=0):
        raw = HEADER.pack(self.kind, self.source, len(self.body), self.destination) + self.body
        if len(raw) > MAX_PACKET_SIZE:
            raise ValueError('High Seize game packet too large')
        parts = [raw[i:i + PART_SIZE] for i in range(0, len(raw), PART_SIZE)]
        result = []
        for index, part in enumerate(parts):
            if len(parts) == 1:
                header = b'\0'
            else:
                header = struct.pack('<BHH', 1, message_id, index)
                if index == 0:
                    header += struct.pack('<H', len(parts))
            mid = len(part) // 2
            wire = (header + struct.pack('<H', len(part) + 2)
                    + b'\xfe' + part[:mid] + b'\xfe' + part[mid:])
            result.append(struct.pack('<I', len(wire)) + wire)
        return result


class GameDecoder:
    """Reassemble one peer's partitions after SNAP reliable deduplication."""

    def __init__(self):
        self.fragments = {}

    def decode(self, data):
        if len(data) < 4 or struct.unpack_from('<I', data)[0] != len(data) - 4:
            raise ValueError('Invalid High Seize stream length')
        stream, result = memoryview(data)[4:], []
        while stream:
            kind, offset, ident, index, count = stream[0], 1, 0, 0, None
            if kind == 1:
                if len(stream) < 7:
                    raise ValueError('Truncated High Seize multipart header')
                ident, index = struct.unpack_from('<HH', stream, offset)
                offset += 4
                if index == 0:
                    count = struct.unpack_from('<H', stream, offset)[0]
                    offset += 2
                limit = (MAX_PACKET_SIZE + PART_SIZE - 1) // PART_SIZE
                if index >= limit or count is not None and not 2 <= count <= limit:
                    raise ValueError('Invalid High Seize fragment count')
            elif kind not in (0, 2):
                raise ValueError('Unknown High Seize partition type')
            if len(stream) < offset + 2:
                raise ValueError('Truncated High Seize partition length')
            length = struct.unpack_from('<H', stream, offset)[0]
            offset += 2
            if not 2 <= length <= PART_SIZE + 2 or len(stream) < offset + length:
                raise ValueError('Invalid High Seize partition length')
            mid = (length - 2) // 2
            if stream[offset] != 0xfe or stream[offset + mid + 1] != 0xfe:
                raise ValueError('Invalid High Seize partition markers')
            raw = bytes(stream[offset + 1:offset + mid + 1]) + bytes(stream[offset + mid + 2:offset + length])
            stream = stream[offset + length:]
            if kind == 1:
                if ident not in self.fragments and len(self.fragments) >= 8:
                    raise ValueError('Too many incomplete High Seize messages')
                entry = self.fragments.setdefault(ident, {'count': None, 'parts': {}})
                if (index in entry['parts'] and entry['parts'][index] != raw
                        or count is not None and entry['count'] not in (None, count)):
                    del self.fragments[ident]
                    raise ValueError('Conflicting High Seize fragments')
                if count is not None:
                    entry['count'] = count
                entry['parts'][index] = raw
                count = entry['count']
                if count is not None and any(i >= count for i in entry['parts']):
                    del self.fragments[ident]
                    raise ValueError('High Seize fragment index exceeds count')
                if count is None or len(entry['parts']) < count:
                    continue
                del self.fragments[ident]
                raw = b''.join(entry['parts'][i] for i in range(count))
            if not HEADER.size <= len(raw) <= MAX_PACKET_SIZE:
                raise ValueError('Invalid High Seize game packet size')
            packet_kind, source, size, destination = HEADER.unpack_from(raw)
            if size != len(raw) - HEADER.size:
                raise ValueError('Invalid High Seize game body length')
            result.append(GamePacket(packet_kind, raw[HEADER.size:], source, destination))
        return result
