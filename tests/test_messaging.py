import asyncio
import tempfile
import unittest
import xml.etree.ElementTree as ET
from xml.parsers import expat

from arena.accounts import AccountStore
from arena.messaging import Messaging, ROSTER, wire
from arena.profiles import ProfileStore


def stanza(text):
    return ET.fromstring(text)


async def immediate_sleep(_):
    pass


class MessagingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
        self.alice = self.accounts.create_user('Alice', 'one')
        self.bob = self.accounts.create_user('Bob', 'two')
        self.profiles = ProfileStore(self.accounts)
        self.hub = Messaging(self.profiles, sleep=immediate_sleep)
        self.a, self.a_messages = self.client(self.alice)
        self.b, self.b_messages = self.client(self.bob)

    async def asyncTearDown(self):
        self.accounts.close()
        self.directory.cleanup()

    def client(self, user, resource='segachat'):
        messages = []
        async def send(text):
            messages.append(stanza(text))
        return self.hub.connect(user, 'ngi-prod', resource, send), messages

    async def available(self, connection):
        await self.hub.presence(connection, stanza('<presence><status>available</status><ext_pres GCID="115c"/></presence>'))

    async def subscribe(self, sender, target):
        await self.hub.presence(sender, stanza(f'<presence type="subscribe" to="{target}@ngi-prod" id="segachat_buddy_req"><status>0Join my friends?</status></presence>'))

    async def accept(self, sender, target):
        await self.hub.presence(sender, stanza(f'<presence type="subscribed" to="{target}@ngi-prod"/>'))

    async def roster(self, connection):
        node = stanza('<iq type="get" id="segachat_get_roster"><query xmlns="jabber:iq:roster"/></iq>')
        await self.hub.roster(connection, node, node[0])

    async def fetch(self, connection, **attributes):
        node = stanza('<iq type="get" id="segachat_get_off_messages"><query xmlns="http://jabber.org/protocol/offline" action="fetch"/></iq>')
        node[0].attrib.update(attributes)
        await self.hub.offline(connection, node, node[0])

    async def purge(self, connection):
        node = stanza('<iq type="set"><query xmlns="http://jabber.org/protocol/offline" action="purge"/></iq>')
        await self.hub.offline(connection, node, node[0])

    async def test_invitation_acceptance_and_reciprocal_subscription(self):
        # RFC 6121 subscriptions are directional until both accounts grant them.
        await self.roster(self.a)
        await self.roster(self.b)
        await self.available(self.a)
        await self.available(self.b)
        await self.subscribe(self.a, 'bOB')
        self.assertEqual(self.profiles.friends(self.alice), [])
        invitation = self.b_messages[-1]
        self.assertEqual(invitation.get('from'), 'Alice@ngi-prod')
        self.assertEqual(invitation.get('type'), 'subscribe')
        self.assertEqual(invitation.findtext('status'), '0Join my friends?')
        item = self.a_messages[-1].find('{'+ROSTER+'}query/{'+ROSTER+'}item')
        self.assertEqual((item.get('subscription'), item.get('ask')), ('none', 'subscribe'))
        await self.accept(self.b, 'Alice')
        self.assertEqual(self.profiles.friends(self.alice), [self.bob])
        self.assertEqual(self.hub.subscription(self.alice, self.bob), ('to', False))
        self.assertEqual(self.hub.subscription(self.bob, self.alice), ('from', False))
        self.assertEqual(self.a_messages[-1].find('ext_pres').get('GCID'), '115c')
        await self.subscribe(self.b, 'Alice')
        await self.accept(self.a, 'Bob')
        self.assertEqual(self.hub.subscription(self.alice, self.bob), ('both', False))
        self.assertEqual(self.hub.subscription(self.bob, self.alice), ('both', False))
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM subscription_requests').fetchone()[0], 0)

    async def test_pending_invitation_survives_database_reopen(self):
        await self.available(self.a)
        await self.subscribe(self.a, 'Bob')
        await self.subscribe(self.a, 'Bob')
        self.assertEqual(self.b_messages, [])
        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        self.profiles = ProfileStore(self.accounts)
        self.hub = Messaging(self.profiles, sleep=immediate_sleep)
        bob, received = self.client(self.bob)
        await self.available(bob)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].get('type'), 'subscribe')
        await self.accept(bob, 'Alice')
        self.assertEqual(self.profiles.friends(self.bob), [self.alice])

    async def test_reject_and_remove_revoke_grants(self):
        await self.subscribe(self.a, 'Bob')
        await self.hub.presence(self.b, stanza('<presence type="unsubscribed" to="Alice@ngi-prod"/>'))
        self.assertEqual(self.profiles.friends(self.alice), [])
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM subscription_requests').fetchone()[0], 0)
        self.assertEqual(self.hub.contacts(self.alice), [self.bob])
        self.assertEqual(self.hub.contacts(self.bob), [])
        await self.subscribe(self.a, 'Bob')
        await self.accept(self.b, 'Alice')
        await self.subscribe(self.b, 'Alice')
        await self.accept(self.a, 'Bob')
        await self.roster(self.a)
        node = stanza('<iq type="set" id="remove"><query xmlns="jabber:iq:roster"><item jid="Bob@ngi-prod" subscription="remove"/></query></iq>')
        await self.hub.roster(self.a, node, node[0])
        self.assertEqual(self.profiles.friends(self.alice), [])
        self.assertEqual(self.profiles.friends(self.bob), [])
        self.assertEqual(self.hub.contacts(self.alice), [])
        self.assertEqual(self.hub.contacts(self.bob), [self.alice])
        self.assertEqual(self.a_messages[-1].find('{'+ROSTER+'}query/{'+ROSTER+'}item').get('subscription'), 'remove')

    async def test_subscription_revocation_clears_visible_presence(self):
        await self.subscribe(self.a, 'Bob')
        await self.accept(self.b, 'Alice')
        await self.available(self.a)
        await self.available(self.b)
        self.a_messages.clear()
        await self.hub.presence(self.b, stanza('<presence type="unsubscribed" to="Alice@ngi-prod"/>'))
        self.assertEqual([node.get('type') for node in self.a_messages], ['unavailable', 'unsubscribed'])
        self.assertEqual(self.a_messages[0].get('from'), 'Bob@ngi-prod/segachat')
        self.a_messages.clear()
        await self.hub.presence(self.b, stanza('<presence><status>away</status></presence>'))
        self.assertEqual(self.a_messages, [])

    async def test_friend_roster_and_messages_are_shared_between_game_domains(self):
        await self.subscribe(self.a, 'Bob')
        await self.accept(self.b, 'Alice')
        self.b.domain = 'ngage-auth'
        await self.available(self.b)
        await self.roster(self.b)
        item = self.b_messages[-1].find('{'+ROSTER+'}query/{'+ROSTER+'}item')
        self.assertEqual(item.get('jid'), 'Alice@ngage-auth')
        self.assertEqual(item.get('subscription'), 'from')
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>Same account</body></message>'))
        self.assertEqual(self.b_messages[-1].get('from'), 'Alice@ngage-auth/segachat')
        self.assertEqual(self.b_messages[-1].get('to'), 'Bob@ngage-auth/segachat')

    async def test_presence_preserves_game_and_disconnect_resource(self):
        await self.subscribe(self.a, 'Bob')
        await self.accept(self.b, 'Alice')
        await self.available(self.a)
        await self.available(self.b)
        self.a_messages.clear()
        await self.hub.presence(self.b, stanza('<presence from="Forged@ngi-prod"><status>away</status><ext_pres GCID="e4e8"/></presence>'))
        self.assertEqual(self.a_messages[-1].get('from'), 'Bob@ngi-prod/segachat')
        self.assertEqual(self.a_messages[-1].find('ext_pres').get('GCID'), 'e4e8')
        await self.hub.disconnect(self.b)
        self.assertEqual(self.a_messages[-1].get('type'), 'unavailable')
        self.assertEqual(self.a_messages[-1].get('from'), 'Bob@ngi-prod/segachat')

    async def test_online_and_offline_messages_use_authenticated_sender(self):
        await self.available(self.a)
        await self.available(self.b)
        message = stanza('<message to="Bob@ngi-prod" from="Other@ngi-prod" type="chat" id="hello"><body>Hello &amp; good fishing</body></message>')
        await self.hub.message(self.a, message)
        self.assertEqual(self.b_messages[-1].get('from'), 'Alice@ngi-prod/segachat')
        self.assertEqual(self.b_messages[-1].findtext('body'), 'Hello & good fishing')
        await self.hub.disconnect(self.b)
        await self.hub.message(self.a, message)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 1)
        await self.fetch(self.a)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 1)
        bob, received = self.client(self.bob)
        await self.fetch(bob)
        self.assertEqual(received[0].get('from'), 'Alice@ngi-prod/segachat')
        self.assertEqual(received[0].findtext('body'), 'Hello & good fishing')
        self.assertEqual(received[-1].get('type'), 'result')
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 1)
        await self.purge(bob)
        received.clear()
        await self.fetch(bob)
        self.assertEqual(len(received), 1)

    async def test_offline_purge_only_removes_this_accounts_fetched_batch(self):
        message = stanza('<message to="Bob@ngi-prod"><body>First</body></message>')
        await self.hub.message(self.a, message)
        await self.fetch(self.b)
        message.find('body').text = 'Arrived after fetch'
        await self.hub.message(self.a, message)
        await self.purge(self.a)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 2)
        await self.purge(self.b)
        rows = list(self.accounts.db.execute('SELECT stanza FROM offline_messages'))
        self.assertEqual(len(rows), 1)
        self.assertIn('Arrived after fetch', rows[0][0])

    async def test_late_purge_from_another_resource_cannot_delete_a_new_message(self):
        second, _ = self.client(self.bob, 'other')
        message = stanza('<message to="Bob@ngi-prod"><body>First</body></message>')
        await self.hub.message(self.a, message)
        await self.fetch(self.b)
        await self.fetch(second)
        await self.purge(self.b)
        message.find('body').text = 'New message'
        await self.hub.message(self.a, message)
        await self.purge(second)
        rows = list(self.accounts.db.execute('SELECT stanza FROM offline_messages'))
        self.assertEqual(len(rows), 1)
        self.assertIn('New message', rows[0][0])

    async def test_native_selective_then_bulk_fetch_repeats_until_purge(self):
        carol = self.accounts.create_user('Carol', 'three')
        c, _ = self.client(carol)
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>0001First</body></message>'))
        await self.hub.message(c, stanza('<message to="Bob@ngi-prod"><body>0001Other friend</body></message>'))
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>0001Second</body></message>'))
        row = self.accounts.db.execute('SELECT * FROM offline_messages ORDER BY id DESC LIMIT 1').fetchone()
        identifier = self.hub.message_node(row)
        await self.fetch(self.b, jid='Carol@ngi-prod', node=identifier)
        self.assertEqual(len(self.b_messages), 1)
        await self.fetch(self.b, jid='Alice@ngi-prod', node=identifier)
        await self.fetch(self.b)
        await self.fetch(self.b)
        messages = [node for node in self.b_messages if node.tag == 'message']
        self.assertEqual([node.findtext('body') for node in messages], [
            '0001Second', '0001First', '0001Other friend', '0001Second',
            '0001First', '0001Other friend', '0001Second'])
        self.assertTrue(all(node.get('type') is None and node.get('id') is None for node in messages))
        await self.purge(self.b)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 0)

    async def test_unacknowledged_messages_survive_reconnect_and_foreign_ids_are_empty(self):
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>Unacknowledged</body></message>'))
        identifier = str(self.accounts.db.execute('SELECT id FROM offline_messages').fetchone()[0])
        await self.fetch(self.a, jid='Bob@ngi-prod', node=identifier)
        self.assertEqual(len(self.a_messages), 1)
        await self.fetch(self.b)
        await self.hub.disconnect(self.b)
        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        self.hub = Messaging(ProfileStore(self.accounts), sleep=immediate_sleep)
        bob, received = self.client(self.bob)
        await self.fetch(bob)
        self.assertEqual(received[0].findtext('body'), 'Unacknowledged')
        await self.purge(bob)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 0)

    async def test_offline_delivery_retains_server_utc_timestamp_after_reopen(self):
        self.hub.clock = lambda: 0
        await self.hub.message(self.a, stanza('''<message to="Bob@ngi-prod"><body>0001Stored</body>
            <x xmlns="jabber:x:delay" stamp="spoofed"/>
            <delay xmlns="urn:xmpp:delay" stamp="spoofed"/></message>'''))
        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        self.hub = Messaging(ProfileStore(self.accounts), clock=lambda: 86400,
                             sleep=immediate_sleep)
        bob, received = self.client(self.bob)
        await self.fetch(bob)
        message = received[0]
        delay = message.findall('{jabber:x:delay}x')
        self.assertEqual(len(delay), 1)
        self.assertEqual(delay[0].attrib, {'from': 'ngi-prod', 'stamp': '19700101T00:00:00'})
        self.assertIsNone(message.find('{urn:xmpp:delay}delay'))
        self.assertEqual(message.findtext('body'), '0001Stored')
        self.assertIsNone(message.get('id'))
        self.assertIsNone(message.get('type'))
        # The native parser looks up literal element names, including prefixes.
        elements = []
        parser = expat.ParserCreate()
        parser.StartElementHandler = lambda name, attrs: elements.append((name, attrs))
        parser.Parse(wire(message), True)
        self.assertEqual([name for name, attrs in elements], ['message', 'body', 'x'])
        self.assertEqual(elements[-1][1]['xmlns'], 'jabber:x:delay')

    async def test_offline_timestamps_are_unique_within_one_second(self):
        self.hub.clock = lambda: 0
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>First</body></message>'))
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>Second</body></message>'))
        rows = self.accounts.db.execute('SELECT * FROM offline_messages ORDER BY id').fetchall()
        self.assertEqual([self.hub.message_node(row) for row in rows], [
            '19700101T00:00:00', '19700101T00:00:01'])

    async def test_offline_fetch_rejects_malformed_node(self):
        with self.assertRaises(ValueError):
            await self.fetch(self.b, node='../1')

    async def test_offline_fetch_waits_for_legacy_roster_callbacks(self):
        waits = []
        async def record(delay):
            waits.append(delay)
        self.hub.sleep = record
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>Queued</body></message>'))
        await self.fetch(self.b)
        self.assertEqual(waits, [1.0])
        self.assertEqual(self.b_messages[0].findtext('body'), 'Queued')

    async def test_blocking_hides_presence_and_already_queued_message_headers(self):
        await self.subscribe(self.a, 'Bob')
        await self.accept(self.b, 'Alice')
        await self.hub.message(self.b, stanza('<message to="Alice@ngi-prod"><body>Before block</body></message>'))
        self.profiles.update(self.bob, {'ignoreUsersList': ['Alice']})
        await self.available(self.b)
        self.a_messages.clear()
        await self.available(self.a)
        self.assertEqual(self.a_messages, [])
        node = stanza('<iq type="get" id="segachat_get_off_headers"><query xmlns="http://jabber.org/protocol/disco#items" node="http://jabber.org/protocol/offline"/></iq>')
        await self.hub.offline(self.a, node, node[0])
        self.assertEqual(self.a_messages[-1][0].get('count'), '0')
        await self.fetch(self.a)
        self.assertFalse(any(node.tag == 'message' for node in self.a_messages))
        await self.purge(self.a)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 0)
        await self.hub.presence(self.a, stanza('<presence type="unsubscribe" to="Bob@ngi-prod"/>'))
        self.assertEqual(self.profiles.friends(self.alice), [])

    async def test_native_offline_headers_are_scoped_to_the_receiving_account(self):
        await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>Queued</body></message>'))
        query = stanza('<iq type="get" id="segachat_get_off_headers"><query xmlns="http://jabber.org/protocol/disco#items" node="http://jabber.org/protocol/offline" jid="Alice@ngi-prod"/></iq>')
        await self.hub.offline(self.b, query, query[0])
        result = self.b_messages[-1][0]
        self.assertEqual(result.get('count'), '1')
        self.assertEqual(result[0].get('jid'), 'Alice@ngi-prod')
        self.assertRegex(result[0].get('node'), r'^\d{8}T\d{2}:\d{2}:\d{2}$')
        query[0].set('jid', 'Bob@ngi-prod')
        await self.hub.offline(self.a, query, query[0])
        self.assertEqual(self.a_messages[-1][0].get('count'), '0')
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 1)

    async def test_blocked_accounts_unknown_targets_and_unsolicited_grants(self):
        self.profiles.update(self.bob, {'ignoreUsersList': ['alice']})
        with self.assertRaises(PermissionError):
            await self.subscribe(self.a, 'Bob')
        with self.assertRaises(PermissionError):
            await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>No</body></message>'))
        for jid in ('Alice@ngi-prod', 'Bob@external.example', 'Missing@ngi-prod', 'Bob'):
            with self.assertRaises((ValueError, LookupError)):
                self.hub.target(self.a, jid)
        self.profiles.update(self.bob, {'ignoreUsersList': []})
        with self.assertRaises(ValueError):
            await self.accept(self.a, 'Bob')
        self.assertEqual(self.profiles.friends(self.alice), [])

    async def test_roster_edits_cannot_grant_subscriptions(self):
        await self.roster(self.a)
        node = stanza('<iq type="set" id="edit"><query xmlns="jabber:iq:roster"><item jid="Bob@ngi-prod" name="Fishing partner" subscription="both"><group>Fishing</group></item></query></iq>')
        await self.hub.roster(self.a, node, node[0])
        await self.roster(self.a)
        item = self.a_messages[-1].find('{'+ROSTER+'}query/{'+ROSTER+'}item')
        self.assertEqual(item.get('subscription'), 'none')
        self.assertEqual(item.get('name'), 'Fishing partner')
        self.assertEqual(item.findtext('{'+ROSTER+'}group'), 'Fishing')
        self.assertEqual(self.profiles.friends(self.alice), [])

    async def test_disconnected_recipient_does_not_break_delivery_to_other_resource(self):
        other, received = self.client(self.bob, 'other')
        await self.available(other)
        for failure in (ConnectionResetError, asyncio.TimeoutError):
            with self.subTest(failure=failure):
                failed, _ = self.client(self.bob, 'closed')
                await self.available(failed)
                async def broken(text):
                    raise failure()
                failed.send = broken
                await self.hub.message(self.a, stanza('<message to="Bob@ngi-prod"><body>Still delivered</body></message>'))
                self.assertEqual(received[-1].findtext('body'), 'Still delivered')
                self.assertNotIn(failed, self.hub.connections)
                self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM offline_messages').fetchone()[0], 0)
