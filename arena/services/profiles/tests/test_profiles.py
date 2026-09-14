import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.services.accounts.store import AccountStore
from arena.services.profiles.service import NGP, SOAP, POINT_TYPES, ProfileService, ProfileStore


def request(method, content=''):
    namespace = NGP+ProfileService.METHODS[method]
    return f'<s:Envelope xmlns:s="{SOAP}"><s:Body><n:{method} xmlns:n="{namespace}">{content}</n:{method}></s:Body></s:Envelope>'.encode()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
        self.owner = self.accounts.create_user('Owner', 'native-test')
        self.peer = self.accounts.create_user('Peer', 'native-test')
        self.store = ProfileStore(self.accounts)
        self.service = ProfileService(self.store)

    def tearDown(self):
        self.accounts.close()
        self.directory.cleanup()

    def response(self, method, content='', user=None):
        return ET.fromstring(self.service.response(request(method, content), user)).find('{'+SOAP+'}Body')[0]

    def test_native_miniprofile_choice_and_point_categories(self):
        result = self.response('getMiniProfile', '<username>owner</username>', self.peer)
        self.assertEqual(result.tag, '{'+NGP+'getminiprofile}getMiniProfileResponse')
        self.assertEqual([child.tag for child in result], ['miniProfile'])
        mini = result[0]
        self.assertEqual([child.tag for child in mini], ['username', 'iconUrl', 'ngps', 'games'])
        self.assertEqual(mini.findtext('username'), 'Owner')
        self.assertEqual([item.findtext('type') for item in mini.find('ngps')], list(POINT_TYPES))
        self.assertEqual([item.findtext('score') for item in mini.find('ngps')], ['0']*3)
        self.assertEqual(len(mini.find('games')), 0)

    def test_sync_cursor_roundtrip_preserves_submicrosecond_clock_updates(self):
        self.store.clock = lambda: 2000000000.0000002
        self.store.update(self.owner, {'quote': 'First'})
        old = '<lastSynchDate>2000-01-01T00:00:00Z</lastSynchDate>'
        result = self.response('getProfile', old, self.owner)
        cursor = result.findtext('user/lastProfileEditDate')
        self.assertEqual(cursor, '2033-05-18T03:33:20.000000Z')
        current = f'<lastSynchDate>{cursor}</lastSynchDate>'
        self.assertIsNone(self.response('getProfile', current, self.owner).find('user'))
        self.store.update(self.owner, {'quote': 'Second'})
        changed = self.response('getProfile', current, self.owner)
        self.assertEqual(changed.findtext('user/quote'), 'Second')
        self.assertGreater(changed.findtext('user/lastProfileEditDate'), cursor)

    def test_native_full_profile_sequence_is_private_and_timestamped(self):
        content = '<lastSynchDate>2000-01-01T00:00:00Z</lastSynchDate>'
        self.store.update(self.owner, {'email': 'owner@example.test', 'quote': 'Hello <sea> & fish'})
        denied = self.response('getProfile', content)
        self.assertEqual(denied.findtext('ngpException/errorCode'), '401')
        result = self.response('getProfile', content, self.owner)
        profile = result.find('user')
        self.assertEqual([child.tag for child in profile], [
            'firstName', 'lastName', 'email', 'phoneNum', 'city', 'state', 'country', 'gender',
            'quote', 'favoriteGame', 'alertSubscription', 'privacySetting', 'ignoreUsersList',
            'newsLetterSubscription', 'username', 'dateOfBirth', 'lastProfileEditDate', 'iconUrl', 'level', 'reputation'])
        self.assertEqual(profile.findtext('quote'), 'Hello <sea> & fish')
        self.assertEqual(profile.findtext('email'), 'owner@example.test')
        peer = self.response('getProfile', content+'<username>Owner</username>', self.peer)
        self.assertEqual(peer.findtext('user/username'), 'Peer')
        self.assertEqual(peer.findtext('user/email'), '')
        date = profile.findtext('lastProfileEditDate')
        unchanged = self.response('getProfile', f'<lastSynchDate>{date}</lastSynchDate>', self.owner)
        self.assertIsNone(unchanged.find('user'))

    def test_update_persists_profile_and_games_without_changing_account_credentials(self):
        content = '''<user><firstName>Marin</firstName><quote>Fishing &amp; friends</quote>
            <alertSubscription><alert name="friends" subscribed="true"/></alertSubscription>
            <privacySetting><displayMyFriendsList>true</displayMyFriendsList><displayMyCity>false</displayMyCity><displayMyCountry>true</displayMyCountry></privacySetting>
            <ignoreUsersList><username>Blocked</username></ignoreUsersList><newsLetterSubscription>false</newsLetterSubscription>
            <games><game><uid>536915900</uid><classId>4110</classId><singlePlayerNGPs>35</singlePlayerNGPs><multiPlayerNGPs>10</multiPlayerNGPs></game></games>
            <userIcon><id>5</id><type>builtin</type></userIcon></user>'''
        result = self.response('updateProfile', content, self.owner)
        self.assertIsNotNone(result.find('timeStamp'))
        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        self.store = ProfileStore(self.accounts)
        self.service = ProfileService(self.store)
        profile = self.store.get(self.owner)
        self.assertEqual(profile['firstName'], 'Marin')
        self.assertEqual(profile['alertSubscription'], [{'name': 'friends', 'subscribed': True}])
        self.assertEqual(profile['ignoreUsersList'], ['Blocked'])
        self.assertEqual(self.store.points(self.owner), [0, 0, 0])
        self.assertEqual(self.store.points(self.peer), [0, 0, 0])
        self.assertEqual(self.accounts.authenticate('Owner', 'native-test'), self.owner)

    def test_invalid_update_is_atomic_and_cannot_assign_readonly_fields(self):
        before = self.store.get(self.owner)
        for content in ['<user><firstName>Changed</firstName><username>Peer</username></user>',
                        '<user><firstName>Changed</firstName><games><game><uid>-1</uid></game></games></user>',
                        '<user><firstName>Changed</firstName><newsLetterSubscription>yes</newsLetterSubscription></user>',
                        '<user><firstName>A</firstName><firstName>B</firstName></user>']:
            result = self.response('updateProfile', content, self.owner)
            self.assertIsNotNone(result.find('ngpexception'))
            self.assertEqual(self.store.get(self.owner), before)
        denied = self.response('updateProfile', '<user><firstName>Changed</firstName></user>')
        self.assertEqual(denied.findtext('ngpexception/errorCode'), '401')
        self.assertEqual(self.store.get(self.owner), before)

    def test_friend_profiles_require_acceptance_and_removal_is_reflected(self):
        content = '<lastSyncDate>0001-01-01T00:00:00Z</lastSyncDate>'
        self.store.request_friend(self.owner, self.peer)
        pending = self.response('getFriendsMiniProfiles', content, self.owner)
        self.assertEqual(len(pending.findall('friendsMiniProfiles/miniProfile')), 0)
        self.assertEqual(self.response('getFriendsExtendedProfile', '<username>Peer</username>', self.owner).findtext('ngpexception/errorCode'), '401')
        self.store.accept_friend(self.peer, self.owner)
        for user, name in [(self.owner, 'Peer'), (self.peer, 'Owner')]:
            result = self.response('getFriendsMiniProfiles', content, user)
            self.assertEqual(result.findtext('friendsMiniProfiles/miniProfile/username'), name)
            self.assertIsNotNone(result.find('friendsMiniProfiles/timestamp'))
        self.store.remove_friend(self.owner, self.peer)
        self.assertEqual(self.store.friends(self.owner), [])
        self.assertEqual(self.store.friends(self.peer), [])

    def test_email_change_is_confined_to_the_session_owner(self):
        result = self.response('setUserEmailAddress', '<emailAddress>new@example.test</emailAddress>', self.owner)
        self.assertEqual(len(result), 0)
        self.assertEqual(self.store.get(self.owner)['email'], 'new@example.test')
        self.assertEqual(self.store.get(self.peer)['email'], '')
