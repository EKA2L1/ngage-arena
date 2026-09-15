"""High Seize rooms and ordered native battle exchanges over SNAP."""

from dataclasses import dataclass, field
import logging
import struct
import time

from arena.games.high_seize.protocol import (BattleKind, BattleMessage, GameDecoder, GamePacket,
                             GameSettings, Player, encode_players)
from arena.games.high_seize.commander import Commander

LOG = logging.getLogger(__name__)
SETUP = struct.Struct('<HHI')
WORD = struct.Struct('<I')


class HighSeizeStore:
    def __init__(self, db, clock=time.time):
        self.db, self.clock = db, clock
        db.executescript('''
        CREATE TABLE IF NOT EXISTS hs_matches (
            id INTEGER PRIMARY KEY, started REAL NOT NULL, ended REAL,
            settings BLOB NOT NULL, reason TEXT, winner_team INTEGER);
        CREATE TABLE IF NOT EXISTS hs_players (
            match_id INTEGER NOT NULL REFERENCES hs_matches(id),
            user_id INTEGER NOT NULL REFERENCES users(id), slot INTEGER NOT NULL,
            name TEXT NOT NULL, team INTEGER NOT NULL, outcome TEXT,
            commander BLOB,
            PRIMARY KEY(match_id,slot));
        CREATE TABLE IF NOT EXISTS hs_events (
            match_id INTEGER NOT NULL REFERENCES hs_matches(id),
            ordinal INTEGER NOT NULL, elapsed REAL NOT NULL,
            source INTEGER NOT NULL, message_id INTEGER NOT NULL,
            kind INTEGER NOT NULL, turn INTEGER NOT NULL, body BLOB NOT NULL,
            state TEXT NOT NULL, PRIMARY KEY(match_id,ordinal),
            UNIQUE(match_id,source,message_id));
        ''')

    def recover(self):
        with self.db:
            self.db.execute("""UPDATE hs_events SET state='undone' WHERE state='pending'
                AND match_id IN (SELECT id FROM hs_matches WHERE ended IS NULL)""")
            self.db.execute("UPDATE hs_matches SET ended=?,reason='server restart' WHERE ended IS NULL",
                            (self.clock(),))

    def start(self, settings, members):
        with self.db:
            ident = self.db.execute('INSERT INTO hs_matches(started,settings) VALUES(?,?)',
                                    (self.clock(), settings.encode())).lastrowid
            self.db.executemany('''INSERT INTO hs_players
                (match_id,user_id,slot,name,team,commander) VALUES(?,?,?,?,?,?)''',
                ((ident, m.user, m.slot, m.name, m.team, m.commander[8:]) for m in members))
        return ident

    def event(self, match, message, elapsed, state='accepted'):
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO hs_events
                SELECT ?,COALESCE(MAX(ordinal),0)+1,?,?,?,?,?,?,? FROM hs_events WHERE match_id=?''',
                (match, elapsed, message.source, message.identifier, int(message.kind),
                 message.turn, message.encode(), state, match))

    def mark(self, match, message, state):
        with self.db:
            self.db.execute('UPDATE hs_events SET state=? WHERE match_id=? AND source=? AND message_id=?',
                            (state, match, message.source, message.identifier))

    def finish(self, match, winner, reason):
        with self.db:
            changed = self.db.execute('''UPDATE hs_matches SET ended=?,winner_team=?,reason=?
                WHERE id=? AND ended IS NULL''', (self.clock(), winner, reason, match)).rowcount
            if changed and winner is not None:
                self.db.execute("UPDATE hs_players SET outcome=CASE WHEN team=? THEN 'win' ELSE 'loss' END WHERE match_id=?",
                                (winner, match))
            if changed:
                self.db.execute("UPDATE hs_events SET state='undone' WHERE match_id=? AND state='pending'", (match,))
        return bool(changed)

    def profile(self, name):
        return self.db.execute('SELECT id,name FROM users WHERE name=?', (name,)).fetchone()


@dataclass
class Member:
    peer: tuple
    user: int
    name: str
    slot: int
    team: int
    decoder: GameDecoder = field(default_factory=GameDecoder)
    attached: bool = False
    initialized: bool = False
    next_ping: float = 0
    commander: bytes | None = None
    commander_data: Commander | None = None
    ready: bool = False
    team_ready: bool = False
    synchronization: BattleMessage | None = None
    last_message: int = 0
    defeated: bool = False

    def player(self, host):
        return Player(self.slot, self.name, self.team, host=self.peer == host)


@dataclass
class Room:
    identifier: int
    name: str
    host: tuple
    members: dict = field(default_factory=dict)
    settings: GameSettings | None = None
    attributes: dict = field(default_factory=dict)
    phase: str = 'setup'
    match: int | None = None
    started: float = 0
    turn: int = 0
    active: int = 1
    server_message: int = 0
    deadline: float | None = None
    finish_at: float | None = None
    winner: int | None = None
    finish_reason: str = 'surrender'
    moves: dict = field(default_factory=dict)

    @property
    def capacity(self):
        return self.settings.players if self.settings else 4


class HighSeizeArena:
    def __init__(self, store):
        self.store = store
        self.server = None
        self.rooms = {}
        self.memberships = {}
        self.next_room = 100
        self.partition = 0

    def bind(self, server):
        self.server = server

    def close(self):
        for room in self.rooms.values():
            if room.match and room.phase != 'finished':
                self.store.finish(room.match, None, 'server shutdown')
        self.rooms.clear()
        self.memberships.clear()

    def room(self, peer):
        room = self.rooms.get(self.memberships.get(peer))
        if room is None:
            raise ValueError('Not in a High Seize room')
        return room

    def game(self, peer, packet, reliable=True):
        self.partition = (self.partition + 1) & 65535
        for wire in packet.encode(self.partition):
            self.server.send(peer, 15, wire, reliable=reliable)

    def broadcast(self, room, packet, exclude=None):
        for member in tuple(room.members.values()):
            if member.attached and member.peer != exclude:
                self.game(member.peer, packet)

    def setup(self, peer, subtype, slot, body=b'', source=0):
        self.game(peer, GamePacket(18, SETUP.pack(subtype, len(body), slot) + body, source))

    def record(self, room, extended=False):
        prefix = room.name.encode().ljust(16, b'\0')
        if extended:
            prefix += struct.pack('>I', 1)
        return prefix + struct.pack('>IIIII', len(room.members), 0,
                                    0 if room.phase == 'setup' else 1,
                                    room.capacity, room.identifier)

    def member_event(self, peer, member, kind=6):
        body = member.name.encode().ljust(16, b'\0') + struct.pack('>II', member.user, 0)
        self.server.send(peer, kind, body)

    def handle(self, packet, peer, now):
        kind = packet.kind & 127
        session = self.server.sessions[peer]

        def complete(value=0):
            self.server.send(peer, (packet.kind & 0xff00) | 40, struct.pack('>II', kind, value),
                             flags=0x2000 | (packet.flags & 0x1000))

        if kind == 71:
            lobby = b'Local Arena'.ljust(16, b'\0') + struct.pack('>IIIII', len(self.memberships), 0, 100, 0, 1)
            self.server.send(peer, packet.kind, struct.pack('>III', 0, 1, 1) + lobby, flags=0x3000)
        elif kind == 73:
            rooms = [r for r in self.rooms.values() if r.phase == 'setup'
                     and r.settings and len(r.members) < r.capacity][:16]
            # Keep each reply within SNAP's frame size; the native query limit is 16.
            body = struct.pack('>III', 0, len(rooms), len(rooms))
            self.server.send(peer, packet.kind, body + b''.join(self.record(r, True) for r in rooms), flags=0x3000)
        elif kind == 6 and packet.flags & 0x1000:
            if len(packet.body) != 4 or struct.unpack('>I', packet.body)[0] not in (0, 1):
                raise ValueError('Unknown lobby')
            complete(1)
        elif kind in (4, 6):
            if peer in self.memberships:
                self.disconnected(peer, 'changed room')
            if kind == 4:
                if len(packet.body) != 44 or len(self.rooms) >= 64:
                    raise ValueError('Invalid room creation')
                name = packet.body[:16].split(b'\0', 1)[0].decode('ascii')
                if not name or len(name) > 15:
                    raise ValueError('Invalid room name')
                room = Room(self.next_room, name, peer)
                self.next_room += 1
                self.rooms[room.identifier] = room
            else:
                if len(packet.body) != 24:
                    raise ValueError('Invalid room admission')
                room = self.rooms.get(struct.unpack_from('>I', packet.body)[0])
                if room is None or room.phase != 'setup' or len(room.members) >= room.capacity:
                    complete(0xffffffff)
                    return
            used = {m.slot for m in room.members.values()}
            slot = next(slot for slot in range(1, 5) if slot not in used)
            member = Member(peer, session.user, session.name, slot, slot - 1)
            others = tuple(room.members.values())
            room.members[peer] = member
            self.memberships[peer] = room.identifier
            self.server.send(peer, 4, self.record(room))
            complete(room.identifier)
            for other in others:
                self.member_event(peer, other)
                self.member_event(other.peer, member)
            self.member_event(peer, member)
            self.server.send(peer, 8, struct.pack('>I4sI', room.identifier, b'HOST', room.members[room.host].user))
            LOG.info('High Seize account %d joined room %d in slot %d', member.user, room.identifier, slot)
        elif kind == 7:
            complete()
            self.disconnected(peer, 'left room')
        elif kind == 8:
            room = self.room(peer)
            if peer != room.host or len(packet.body) != 8:
                raise ValueError('Invalid room attribute write')
            room.attributes[packet.body[:4]] = packet.body[4:]
            complete()
        elif kind == 9:
            if len(packet.body) != 8:
                raise ValueError('Invalid attribute query')
            ident, tag = struct.unpack('>I4s', packet.body)
            room = self.rooms.get(ident)
            if room and room.host in room.members and tag == b'HOST':
                self.server.send(peer, 8, struct.pack('>I4sI', ident, tag, room.members[room.host].user))
            complete()
        elif kind == 13:
            if len(packet.body) != 4:
                raise ValueError('Invalid player state')
            complete()
        elif kind == 12:
            room = self.room(peer)
            member = room.members[peer]
            if len(packet.body) != 16:
                raise ValueError('Invalid dedicated server attachment')
            member.attached = True
            member.next_ping = now + 10
            complete()
            self.game(peer, GamePacket(11, WORD.pack(0)))
        elif kind == 17:
            room = self.room(peer)
            member = room.members[peer]
            if not member.attached:
                raise ValueError('Dedicated server not attached')
            for game in member.decoder.decode(packet.body):
                self.game_received(room, member, game, now)
        else:
            LOG.info('Unsupported High Seize SNAP operation %d', kind)

    def handshake(self, room, member):
        if room.settings is None:
            raise ValueError('Host settings are not ready')
        others = [m for m in room.members.values() if m.peer != member.peer]
        values = ((2, member.player(room.host).encode()), (3, room.settings.encode()),
                  (4, encode_players([m.player(room.host) for m in others])))
        for state, data in values:
            self.game(member.peer, GamePacket(17, struct.pack('<HH', state, len(data)) + data))
        member.initialized = True
        for other in others:
            if other.initialized:
                self.setup(other.peer, 0x100, member.slot, member.player(room.host).encode())
            if other.commander:
                self.game(member.peer, GamePacket(18, other.commander, other.slot))
            if other.ready:
                self.setup(member.peer, 2, other.slot, source=other.slot)

    def game_received(self, room, member, game, now):
        if game.kind == 12:
            if len(game.body) != 4:
                raise ValueError('Invalid game heartbeat')
            value = WORD.unpack(game.body)[0]
            if value == 0xdeadbeef:
                self.handshake(room, member)
            elif value not in (0xdeaddeaf, member.slot):
                raise ValueError('Invalid game identity')
            return
        if game.kind == 17:
            if member.peer != room.host or room.phase != 'setup' or len(game.body) < 4:
                raise ValueError('Invalid host settings update')
            state, size = struct.unpack_from('<HH', game.body)
            if state != 1 or size != len(game.body) - 4:
                raise ValueError('Invalid settings handshake')
            room.settings = GameSettings.decode(game.body[4:]).resolve(room.name, member.slot)
            self.handshake(room, member)
            return
        if game.source != member.slot or not member.initialized:
            raise ValueError('Game source does not match room membership')
        if game.kind == 18:
            if room.phase != 'setup' or len(game.body) < SETUP.size:
                raise ValueError('Unexpected setup message')
            subtype, size, slot = SETUP.unpack_from(game.body)
            if size != len(game.body) - SETUP.size:
                raise ValueError('Invalid setup size')
            if subtype == 0x10:
                if member.peer != room.host or size != 4:
                    raise ValueError('Only the host can assign teams')
                target = next((m for m in room.members.values() if m.slot == slot), None)
                team = WORD.unpack(game.body[8:])[0]
                if target is None or team >= 4:
                    raise ValueError('Invalid team assignment')
                target.team = team
                for other in room.members.values():
                    other.team_ready = False
            elif slot != member.slot:
                raise ValueError('Invalid setup owner')
            elif subtype == 1:
                member.commander_data = Commander.decode(game.body[8:])
                member.commander = game.body
                member.ready = False
                member.team_ready = False
            elif subtype == 2:
                if size or not member.commander:
                    raise ValueError('Commander must be supplied before Ready')
                member.ready = True
            elif subtype == 0x20:
                if size or not member.ready:
                    raise ValueError('Invalid team readiness')
                member.team_ready = True
            else:
                raise ValueError('Unsupported setup message')
            self.broadcast(room, game, member.peer)
            if (len(room.members) == room.capacity and all(m.team_ready for m in room.members.values())
                    and len({m.team for m in room.members.values()}) > 1):
                room.phase = 'loading'
                for other in room.members.values():
                    self.setup(other.peer, 0x30, room.settings.host)
        elif game.kind == 16:
            self.battle(room, member, BattleMessage.decode(game.body), now)
        elif game.kind != 11:
            LOG.info('Unsupported High Seize game message %d', game.kind)

    def battle_event(self, room, kind, payload=b''):
        room.server_message += 1
        message = BattleMessage(kind, room.server_message, turn=room.turn, payload=payload)
        self.broadcast(room, message.packet())
        self.store.event(room.match, message, self.server.clock() - room.started)

    def accept(self, room, member, message):
        self.game(member.peer, BattleMessage(BattleKind.ACCEPTED, turn=room.turn,
                                            payload=WORD.pack(message.identifier)).packet())
        self.store.mark(room.match, message, 'accepted')

    def battle(self, room, member, message, now):
        kind = message.kind
        if message.source != member.slot:
            raise ValueError('Battle source does not match member')
        if kind == BattleKind.SYNCHRONIZATION:
            if room.phase != 'loading' or message.identifier or message.turn or message.payload:
                raise ValueError('Invalid battle synchronization')
            member.synchronization = message
            if all(m.synchronization for m in room.members.values()):
                room.match = self.store.start(room.settings, room.members.values())
                room.started = now
                for other in room.members.values():
                    self.broadcast(room, other.synchronization.packet())
                    self.store.event(room.match, other.synchronization, 0)
                begin = BattleMessage(BattleKind.BEGIN)
                self.broadcast(room, begin.packet())
                self.store.event(room.match, begin, 0)
                room.phase = 'battle'
                room.active = min(m.slot for m in room.members.values())
                self.turn_deadline(room, now)
                LOG.info('High Seize match %d started', room.match)
            return
        if room.phase != 'battle' or message.identifier <= member.last_message:
            return
        if message.turn != room.turn or member.defeated:
            self.game(member.peer, BattleMessage(BattleKind.REJECTED, turn=room.turn,
                                                payload=WORD.pack(message.identifier)).packet())
            return
        if kind in (BattleKind.SELECT_OBJECT, BattleKind.SAVE, BattleKind.UI_ELEMENT_CLICK):
            member.last_message = message.identifier
            return
        if member.slot != room.active or kind >= BattleKind.ACCEPTED and kind != BattleKind.BREAK_ALLIANCE:
            raise ValueError('Unexpected client battle action')
        if kind in (BattleKind.END_TURN, BattleKind.SURRENDER, BattleKind.UNDO) and message.payload:
            raise ValueError('Unexpected action payload')
        tentative = kind == BattleKind.MOVE_UNIT and message.flag
        if kind == BattleKind.MOVE_UNIT:
            if len(message.payload) < 12 or len(message.payload) != 12 + 8 * struct.unpack_from('<I', message.payload, 4)[0]:
                raise ValueError('Invalid move path')
            if tentative and member.slot in room.moves:
                raise ValueError('Uncommitted move already exists')
        if kind == BattleKind.ATTACK_UNIT and len(message.payload) != 8:
            raise ValueError('Invalid unit attack')
        if kind == BattleKind.WAIT and len(message.payload) != 4:
            raise ValueError('Invalid wait action')
        member.last_message = message.identifier
        self.store.event(room.match, message, now - room.started,
                         'pending' if tentative else 'accepted')
        if kind == BattleKind.END_TURN:
            self.end_turn(room, now)
            return
        if tentative:
            room.moves[member.slot] = message
            return
        if kind == BattleKind.UNDO:
            self.discard_move(room, member.slot)
            return
        if kind == BattleKind.SURRENDER:
            self.discard_move(room, member.slot)
        else:
            move = room.moves.pop(member.slot, None)
            if move:
                self.broadcast(room, move.packet(), member.peer)
                self.accept(room, member, move)
        self.broadcast(room, message.packet(), member.peer)
        self.accept(room, member, message)
        if kind == BattleKind.SURRENDER:
            member.defeated = True
            self.check_finish(room, now, 'surrender')

    def turn_deadline(self, room, now):
        room.deadline = (None if room.settings.turn_time == 0xffffffff
                         else now + max(1, room.settings.turn_time))

    def discard_move(self, room, slot):
        move = room.moves.pop(slot, None)
        if move:
            self.store.mark(room.match, move, 'undone')

    def end_turn(self, room, now):
        self.discard_move(room, room.active)
        self.battle_event(room, BattleKind.END_TURN)
        slots = sorted(m.slot for m in room.members.values() if not m.defeated)
        if not slots:
            return
        room.active = next((slot for slot in slots if slot > room.active), slots[0])
        room.turn += 1
        self.turn_deadline(room, now)

    def check_finish(self, room, now, reason):
        teams = {m.team for m in room.members.values() if not m.defeated}
        if len(teams) <= 1:
            room.winner = next(iter(teams), None)
            room.finish_reason = reason
            room.phase = 'finishing'
            room.finish_at = now + 3
            room.deadline = None
        else:
            self.end_turn(room, now)

    def disconnected(self, peer, reason):
        room = self.rooms.get(self.memberships.pop(peer, None))
        if room is None:
            return
        member = room.members[peer]
        member.attached = False
        if room.phase == 'battle':
            self.discard_move(room, member.slot)
            member.defeated = True
            message = BattleMessage(BattleKind.END_GAME, member.last_message + 1,
                                    member.slot, room.turn, payload=WORD.pack(0))
            self.broadcast(room, message.packet(), peer)
            self.store.event(room.match, message, self.server.clock() - room.started)
            self.check_finish(room, self.server.clock(), reason)
        elif room.phase in ('setup', 'loading'):
            for other in tuple(room.members.values()):
                if other.peer != peer:
                    self.member_event(other.peer, member, 7)
                    if other.initialized:
                        self.setup(other.peer, 0x300, member.slot)
            if peer == room.host or room.phase == 'loading':
                for other in tuple(room.members.values()):
                    self.memberships.pop(other.peer, None)
                del self.rooms[room.identifier]
                return
        if room.phase not in ('battle', 'finishing'):
            room.members.pop(peer, None)
        if not any(p in self.memberships for p in room.members):
            if room.match:
                self.store.finish(room.match, None, reason)
            self.rooms.pop(room.identifier, None)

    def tick(self, now):
        for room in tuple(self.rooms.values()):
            for member in tuple(room.members.values()):
                if member.attached and member.peer in self.memberships and member.next_ping <= now:
                    self.game(member.peer, GamePacket(11, WORD.pack(0)), reliable=False)
                    member.next_ping = now + 10
            if room.phase == 'battle' and room.deadline is not None and room.deadline <= now:
                self.end_turn(room, now)
            if room.phase == 'finishing' and room.finish_at <= now:
                self.battle_event(room, BattleKind.END_GAME, WORD.pack(2))
                self.store.finish(room.match, room.winner, room.finish_reason)
                room.phase = 'finished'
                LOG.info('High Seize match %d ended: %s', room.match, room.finish_reason)
