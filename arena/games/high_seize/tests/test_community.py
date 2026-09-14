import xml.etree.ElementTree as ET



from arena.services.community.tests.support import community, CommunityCase

class CommunityTests(CommunityCase):
    def test_high_seize_authentication_returns_typed_snap_username(self):
        self.store.create_user('HighSeize', 'native-test')
        for password, expected in [('native-test', ['true', 'HighSeize']), ('wrong', ['false', None])]:
            response = ET.fromstring(self.server.soap_response(community(
                'authenticateUser2', username='highseize', password=password)))
            result = response.find('.//{urn:CommunityApp}authenticateUser2Return')
            self.assertEqual([item.text for item in result], expected)
            self.assertEqual([item.get('{http://www.w3.org/2001/XMLSchema-instance}type') for item in result],
                             ['xsd:boolean', 'xsd:string'])
    def test_high_seize_native_profile_returns_the_requested_account(self):
        user = self.store.create_user('Host', 'one')
        self.store.create_user('Peer', 'two')
        node = ET.fromstring('<message to="retrieval36280@ngage-auth" id="segachat_retrieve_req" event_type="getplayer" game_class_id="36280"/>')
        query = ET.Element('itemlist')
        for key, value in dict(board='player_skills', skilltype='arena', format='csv', queryid='1', name='peer').items():
            ET.SubElement(query, 'item', name=key, value=value)
        request = ET.SubElement(ET.SubElement(node, 'retrieve'), 'request')
        request.text = ET.tostring(query, encoding='unicode')
        response = ET.fromstring(self.server.snap_response(user, node)).findtext('retrieve/response')
        self.assertEqual(response, '0\nOK\n1|1|0|0|playerskills|1|0\n0|1|0|0|100|Peer\n')
        self.assertIn('Login required', self.server.snap_response(None, node))
