import asyncio
import hashlib



from arena.services.community.tests.support import CommunityTransportCase

class CommunityTransportTests(CommunityTransportCase):
    async def test_native_buddy_invitation_is_authenticated_and_delivered(self):
        self.store.create_user('Host', 'one')
        peer = self.store.create_user('Peer', 'two')
        opening = "<stream:stream xmlns:stream='http://etherx.jabber.org/streams' xmlns='jabber:client' to='ngi-prod'>"
        await self.exchange(opening, b"from='ngage-arena'>")
        invitation = '<presence type="subscribe" from="Forged@ngi-prod" to="Peer@ngi-prod" id="segachat_buddy_req"><status>0Join my friends?</status></presence>'
        self.assertIn(b'type="error"', await self.exchange(invitation, b'</presence>'))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM friendships').fetchone()[0], 0)
        auth = '<iq type="set" id="auth"><query xmlns="jabber:iq:auth"><username>{}</username><password>{}</password><resource>segachat</resource></query></iq>'
        await self.exchange(auth.format('Host', hashlib.sha1(b'one').hexdigest()), b'/>')
        reader, writer = await asyncio.open_connection(*self.listener.sockets[0].getsockname())
        try:
            writer.write(opening.encode())
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b"from='ngage-arena'>"), 2)
            writer.write(auth.format('Peer', hashlib.sha1(b'two').hexdigest()).encode())
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b'/>'), 2)
            writer.write(b'<presence><status>available</status></presence>')
            self.writer.write(invitation.encode())
            await self.writer.drain()
            received = await asyncio.wait_for(reader.readuntil(b'</presence>'), 2)
            self.assertIn(b'from="Host@ngi-prod"', received)
            self.assertNotIn(b'Forged', received)
            self.assertIn(b'<status>0Join my friends?</status>', received)
            writer.write(b'<presence type="subscribed" to="Host@ngi-prod"/>')
            await writer.drain()
            # A roster request completes after the preceding grant on this stream.
            writer.write(b'<iq type="get" id="roster"><query xmlns="jabber:iq:roster"/></iq>')
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b'</iq>'), 2)
            self.assertEqual(self.server.profiles.store.friends(peer), [self.store.authenticate('Host', 'one')])
        finally:
            writer.close()
            await writer.wait_closed()
