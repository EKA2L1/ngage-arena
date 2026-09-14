import hashlib
import xml.etree.ElementTree as ET



from arena.services.community.tests.support import CommunityCase, CommunityTransportCase
from arena.games.ashen.tests.fixtures import leaderboard

class CommunityTests(CommunityCase):
    def test_native_score_submission_rankings_and_identity(self):
        uid = self.store.create_user('PlayerOne', 'one')
        second = self.store.create_user('PlayerTwo', 'two')
        self.assertIn('3dabc|HIGHSCORES|game_total|0|', self.server.snap_response(uid, leaderboard()))
        submit = ET.fromstring('<message to="reporter@ngage-auth" id="segachat_send_event" event_type="submit" game_class_id="42318" snap_name="PlayerTwo"><item name="game_total"><value>1200</value></item><item name="level_1"><value>1200</value></item></message>')
        self.assertIn('0\nOK', self.server.snap_response(uid, submit))
        self.server.games.games["42318"].scores.submit_scores(uid, {'game_total': 1000})
        self.server.games.games["42318"].scores.submit_scores(second, {'game_total': 1300})
        response = ET.fromstring(self.server.snap_response(uid, leaderboard()))
        self.assertEqual(response.findtext('retrieve/response').splitlines(), [
            '0', 'OK', '3dabc|HIGHSCORES|game_total|2|0|2|alltime',
            'PlayerTwo|1|1300|0', 'PlayerOne|2|1200|0'])
        self.assertIn('Login required', self.server.snap_response(None, submit))
        self.assertIn('Invalid leaderboard', self.server.snap_response(uid, leaderboard('level_9')))
        with self.assertRaises(ValueError):
            self.server.games.games["42318"].scores.submit_scores(uid, {'level_1': -1})

class CommunityTransportTests(CommunityTransportCase):
    async def test_legacy_auth_roster_and_fragmented_leaderboard(self):
        self.store.create_user('Native', 'test')
        await self.exchange("<?xml version='1.0'?><stream:stream xmlns:stream='http://etherx.jabber.org/streams' xmlns='jabber:client' to='ngage-arena'>", b"from='ngage-arena'>")
        reply = await self.exchange('<iq type="get" id="segachat_query_username"><query xmlns="jabber:iq:auth"><username>Native</username></query></iq>')
        self.assertIn(b'<password/>', reply)
        digest = hashlib.sha1(b'test').hexdigest()
        reply = await self.exchange(f'<iq type="set" id="segachat_auth"><query xmlns="jabber:iq:auth"><username>Native</username><password>{digest}</password><resource>segachat</resource></query></iq>', b'/>')
        self.assertIn(b'type="result"', reply)
        reply = await self.exchange('<iq type="get" id="segachat_get_roster"><query xmlns="jabber:iq:roster"/></iq>')
        self.assertIn(b'<query xmlns="jabber:iq:roster"/>', reply)
        request = ET.tostring(leaderboard(), encoding='unicode')
        self.writer.write(request[:31].encode())
        await self.writer.drain()
        reply = await self.exchange(request[31:], b'</message>')
        self.assertIn(b'segachat_retrieve_resp', reply)
        self.assertIn(b'3dabc|HIGHSCORES|game_total|0|', reply)
