"""Shared XMPP roster, subscriptions and local account messaging."""
import asyncio
import copy
from dataclasses import dataclass, field
import json
import secrets
import xml.etree.ElementTree as ET

from arena.xmlutil import local

CLIENT = 'jabber:client'
ROSTER = 'jabber:iq:roster'
OFFLINE = 'http://jabber.org/protocol/offline'
DISCO_ITEMS = 'http://jabber.org/protocol/disco#items'


def wire(node):
    node = copy.deepcopy(node)
    for child in node.iter():
        if child.tag.startswith('{'+CLIENT+'}'):
            child.tag = local(child.tag)
        elif child.tag.startswith('{'+ROSTER+'}'):
            child.tag = local(child.tag)
            if child.tag == 'query':
                child.set('xmlns', ROSTER)
    return ET.tostring(node, encoding='unicode', short_empty_elements=True).replace(' />', '/>')


@dataclass(eq=False)
class Connection:
    user: int
    domain: str
    resource: str
    send: object
    interested: bool = False
    presence: object = None
    fetched: set = field(default_factory=set)


class Messaging:
    def __init__(self, profiles):
        self.profiles = profiles
        self.db = profiles.db
        self.connections = set()
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS roster_items (
                owner INTEGER NOT NULL REFERENCES users(id),
                contact INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL, groups TEXT NOT NULL,
                PRIMARY KEY(owner,contact), CHECK(owner != contact));
            CREATE TABLE IF NOT EXISTS subscription_requests (
                sender INTEGER NOT NULL REFERENCES users(id),
                recipient INTEGER NOT NULL REFERENCES users(id),
                stanza TEXT NOT NULL, PRIMARY KEY(sender,recipient));
            CREATE TABLE IF NOT EXISTS offline_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sender INTEGER NOT NULL REFERENCES users(id),
                recipient INTEGER NOT NULL REFERENCES users(id), stanza TEXT NOT NULL);
            INSERT OR IGNORE INTO roster_items
                SELECT sender,recipient,users.name,'[]' FROM friendships JOIN users ON users.id=recipient;
            INSERT OR IGNORE INTO roster_items
                SELECT recipient,sender,users.name,'[]' FROM friendships JOIN users ON users.id=sender WHERE accepted=1;
        ''')

    def connect(self, user, domain, resource, send):
        connection = Connection(user, domain, resource, send)
        self.connections.add(connection)
        return connection

    def jid(self, user, domain, resource=''):
        return self.profiles.accounts.name(user)+'@'+domain+('/'+resource if resource else '')

    def target(self, connection, jid):
        bare = jid.split('/', 1)[0]
        name, separator, domain = bare.partition('@')
        if not separator or domain.casefold() != connection.domain.casefold():
            raise ValueError('Remote domains are not supported')
        target = self.profiles.named(name)
        if target == connection.user:
            raise ValueError('Cannot add yourself')
        return target

    def blocked(self, user, other):
        name = self.profiles.accounts.name(other).casefold()
        return name in {entry.casefold() for entry in self.profiles.get(user)['ignoreUsersList']}

    def can_contact(self, user, other):
        return not self.blocked(user, other) and not self.blocked(other, user)

    def subscription(self, user, other):
        rows = list(self.db.execute('SELECT sender,accepted FROM friendships WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)',
                                   (user, other, other, user)))
        outgoing = next((row['accepted'] for row in rows if row['sender'] == user), None)
        incoming = next((row['accepted'] for row in rows if row['sender'] == other), None)
        return ('both' if outgoing and incoming else 'to' if outgoing else 'from' if incoming else 'none', outgoing == 0)

    def contacts(self, user):
        return [row[0] for row in self.db.execute('''
            SELECT contact FROM roster_items WHERE owner=?
            UNION SELECT recipient FROM friendships WHERE sender=?
            UNION SELECT sender FROM friendships WHERE recipient=? AND accepted=1 ORDER BY 1''', (user, user, user))]

    def retain_contact(self, user, other):
        self.db.execute('INSERT OR IGNORE INTO roster_items VALUES(?,?,?,?)',
                        (user, other, self.profiles.accounts.name(other), '[]'))

    def item(self, user, other, domain, removed=False):
        state, pending = self.subscription(user, other)
        row = self.db.execute('SELECT name,groups FROM roster_items WHERE owner=? AND contact=?', (user, other)).fetchone()
        node = ET.Element('item', {'jid': self.jid(other, domain), 'name': row['name'] if row else self.profiles.accounts.name(other),
                                  'subscription': 'remove' if removed else state})
        if pending and not removed:
            node.set('ask', 'subscribe')
        for group in json.loads(row['groups']) if row else []:
            ET.SubElement(node, 'group').text = group
        return node

    async def push(self, user, other, removed=False):
        for connection in tuple(self.connections):
            if connection.user == user and connection.interested:
                iq = ET.Element('iq', {'type': 'set', 'id': 'roster-'+secrets.token_hex(6)})
                ET.SubElement(iq, 'query', {'xmlns': ROSTER}).append(self.item(user, other, connection.domain, removed))
                await self.send_to(connection, wire(iq))

    async def send_to(self, connection, stanza):
        try:
            await connection.send(stanza)
            return True
        except (OSError, asyncio.TimeoutError):
            self.connections.discard(connection)
            return False

    async def deliver(self, sender, recipient, node, resource='', available=True):
        delivered = False
        for connection in tuple(self.connections):
            if connection.user != recipient or (available and connection.presence is None):
                continue
            outgoing = copy.deepcopy(node)
            outgoing.set('from', self.jid(sender, connection.domain, resource))
            outgoing.set('to', self.jid(recipient, connection.domain, connection.resource))
            delivered = await self.send_to(connection, wire(outgoing)) or delivered
        return delivered

    async def disconnect(self, connection):
        self.connections.discard(connection)
        if connection.presence is not None:
            await self.broadcast(connection, ET.Element('presence', {'type': 'unavailable'}))
            connection.presence = None

    async def broadcast(self, connection, node):
        for row in self.db.execute('SELECT sender FROM friendships WHERE recipient=? AND accepted=1', (connection.user,)).fetchall():
            if self.can_contact(connection.user, row[0]):
                await self.deliver(connection.user, row[0], node, connection.resource)

    async def roster(self, connection, node, query):
        identifier = node.get('id', '')
        if node.get('type') == 'get':
            connection.interested = True
            reply = ET.Element('iq', {'type': 'result', 'id': identifier})
            result = ET.SubElement(reply, 'query', {'xmlns': ROSTER})
            for other in self.contacts(connection.user):
                result.append(self.item(connection.user, other, connection.domain))
            await connection.send(wire(reply))
            return
        if node.get('type') != 'set' or len(query) != 1 or local(query[0].tag) != 'item':
            raise ValueError('Expected one roster item')
        item = query[0]
        other = self.target(connection, item.get('jid', ''))
        removed = item.get('subscription') == 'remove'
        if removed:
            await self.cancel(connection, other, 'unsubscribe')
            await self.cancel(connection, other, 'unsubscribed')
            with self.db:
                self.db.execute('DELETE FROM roster_items WHERE owner=? AND contact=?', (connection.user, other))
        else:
            name = item.get('name', self.profiles.accounts.name(other))
            groups = [child.text or '' for child in item if local(child.tag) == 'group']
            if len(name) > 256 or len(groups) > 32 or any(len(group) > 256 for group in groups):
                raise ValueError('Invalid roster item')
            with self.db:
                self.db.execute('INSERT INTO roster_items VALUES(?,?,?,?) ON CONFLICT(owner,contact) DO UPDATE SET name=excluded.name,groups=excluded.groups',
                                (connection.user, other, name, json.dumps(groups)))
        await connection.send(wire(ET.Element('iq', {'type': 'result', 'id': identifier})))
        await self.push(connection.user, other, removed)

    async def cancel(self, connection, other, kind):
        sender, recipient = (connection.user, other) if kind == 'unsubscribe' else (other, connection.user)
        state, _ = self.subscription(sender, recipient)
        if state in ('to', 'both'):
            for available in tuple(self.connections):
                if available.user == recipient and available.presence is not None:
                    await self.deliver(recipient, sender, ET.Element('presence', {'type': 'unavailable'}), available.resource)
        with self.db:
            self.db.execute('DELETE FROM friendships WHERE sender=? AND recipient=?', (sender, recipient))
            self.db.execute('DELETE FROM subscription_requests WHERE sender=? AND recipient=?', (sender, recipient))
        await self.deliver(connection.user, other, ET.Element('presence', {'type': kind}))
        await self.push(connection.user, other)
        await self.push(other, connection.user)

    async def presence(self, connection, node):
        kind = node.get('type', '')
        if not node.get('to') and kind in ('', 'unavailable'):
            first = connection.presence is None
            connection.presence = copy.deepcopy(node) if kind != 'unavailable' else None
            await self.broadcast(connection, node)
            if first and connection.presence is not None:
                for row in self.db.execute('SELECT sender,stanza FROM subscription_requests WHERE recipient=?', (connection.user,)).fetchall():
                    if self.can_contact(connection.user, row['sender']):
                        await self.deliver(row['sender'], connection.user, ET.fromstring(row['stanza']))
                for other in tuple(self.connections):
                    state, _ = self.subscription(connection.user, other.user)
                    if other.presence is not None and state in ('to', 'both') and self.can_contact(connection.user, other.user):
                        await self.deliver(other.user, connection.user, other.presence, other.resource)
            return
        other = self.target(connection, node.get('to', ''))
        if kind in ('unsubscribe', 'unsubscribed'):
            await self.cancel(connection, other, kind)
            return
        if not self.can_contact(connection.user, other):
            raise PermissionError('Player is blocked')
        if kind == 'subscribe':
            state, _ = self.subscription(connection.user, other)
            if state in ('to', 'both'):
                await self.deliver(other, connection.user, ET.Element('presence', {'type': 'subscribed'}))
                return
            self.profiles.request_friend(connection.user, other)
            with self.db:
                self.retain_contact(connection.user, other)
                self.db.execute('INSERT INTO subscription_requests VALUES(?,?,?) ON CONFLICT(sender,recipient) DO UPDATE SET stanza=excluded.stanza',
                                (connection.user, other, wire(node)))
            await self.push(connection.user, other)
            await self.deliver(connection.user, other, node)
        elif kind == 'subscribed':
            self.profiles.accept_friend(connection.user, other)
            with self.db:
                self.retain_contact(connection.user, other)
                self.db.execute('DELETE FROM subscription_requests WHERE sender=? AND recipient=?', (other, connection.user))
            await self.deliver(connection.user, other, node)
            await self.push(connection.user, other)
            await self.push(other, connection.user)
            for available in tuple(self.connections):
                if available.user == connection.user and available.presence is not None:
                    await self.deliver(connection.user, other, available.presence, available.resource)
        elif kind == 'probe':
            state, _ = self.subscription(connection.user, other)
            if state in ('to', 'both'):
                for available in tuple(self.connections):
                    if available.user == other and available.presence is not None:
                        await self.deliver(other, connection.user, available.presence, available.resource)
        else:
            raise ValueError('Unsupported directed presence')

    async def message(self, connection, node):
        other = self.target(connection, node.get('to', ''))
        if not self.can_contact(connection.user, other):
            raise PermissionError('Player is blocked')
        if not any(local(child.tag) == 'body' for child in node):
            raise ValueError('Expected a message body')
        outgoing = copy.deepcopy(node)
        outgoing.set('from', self.jid(connection.user, connection.domain, connection.resource))
        if not await self.deliver(connection.user, other, outgoing, connection.resource):
            with self.db:
                count = self.db.execute('SELECT count(*) FROM offline_messages WHERE recipient=?', (other,)).fetchone()[0]
                if count >= 256:
                    raise ValueError('Recipient mailbox is full')
                self.db.execute('INSERT INTO offline_messages(sender,recipient,stanza) VALUES(?,?,?)', (connection.user, other, wire(outgoing)))

    def mailbox(self, connection, query, headers=False):
        sender = self.target(connection, query.get('jid')) if query.get('jid') else None
        identifier = query.get('node') if not headers else None
        if identifier is not None and (not identifier.isascii() or not identifier.isdigit() or not 0 < int(identifier) < 2**63):
            raise ValueError('Invalid offline message identifier')
        rows = self.db.execute('SELECT id,sender,stanza FROM offline_messages WHERE recipient=? ORDER BY id', (connection.user,)).fetchall()
        return [row for row in rows if row['id'] not in connection.fetched
                and (sender is None or row['sender'] == sender)
                and (identifier is None or row['id'] == int(identifier))]

    async def offline(self, connection, node, query):
        if query.tag == '{'+DISCO_ITEMS+'}query':
            if node.get('type') != 'get' or query.get('node') != OFFLINE:
                raise ValueError('Unsupported discovery node')
            rows = [row for row in self.mailbox(connection, query, headers=True)
                    if self.can_contact(connection.user, row['sender'])]
            reply = ET.Element('iq', {'type': 'result', 'id': node.get('id', '')})
            result = ET.SubElement(reply, 'query', {'xmlns': DISCO_ITEMS, 'node': OFFLINE, 'count': str(len(rows))})
            for row in rows:
                ET.SubElement(result, 'item', {'jid': self.jid(row['sender'], connection.domain), 'node': str(row['id'])})
            await connection.send(wire(reply))
            return
        action = query.get('action')
        if node.get('type') == 'set' and action == 'purge':
            with self.db:
                self.db.executemany('DELETE FROM offline_messages WHERE id=? AND recipient=?',
                                    [(message, connection.user) for message in connection.fetched])
            connection.fetched.clear()
        elif node.get('type') == 'get' and action == 'fetch':
            for row in self.mailbox(connection, query):
                if self.can_contact(connection.user, row['sender']):
                    outgoing = ET.fromstring(row['stanza'])
                    resource = outgoing.get('from', '').partition('/')[2]
                    outgoing.set('from', self.jid(row['sender'], connection.domain, resource))
                    outgoing.set('to', self.jid(connection.user, connection.domain, connection.resource))
                    await connection.send(wire(outgoing))
                connection.fetched.add(row['id'])
        else:
            raise ValueError('Unsupported offline operation')
        if node.get('id'):
            await connection.send(wire(ET.Element('iq', {'type': 'result', 'id': node.get('id')})))
