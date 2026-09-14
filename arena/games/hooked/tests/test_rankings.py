import json
import tempfile
import unittest
import xml.etree.ElementTree as ET

from arena.services.accounts.store import AccountStore
from arena.services.rankings.service import RankingsService, UnsupportedRanking
from arena.runtime import default_games


from arena.games.hooked.tests.fixtures import NATIVE_SUBMIT, NATIVE_TOPN, NATIVE_PROXIMITY

class RankingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = AccountStore(self.directory.name)
        self.owner = self.accounts.create_user('Angler', 'native-test')
        self.peer = self.accounts.create_user('Peer', 'native-test')
        self.service = RankingsService(self.accounts, default_games(self.accounts))

    def tearDown(self):
        self.accounts.close()
        self.directory.cleanup()

    def test_native_report_persists_under_the_shared_account(self):
        payload = ET.fromstring(self.service.response(NATIVE_SUBMIT, self.owner))
        self.assertEqual(payload.get('format'), 'csv')
        self.assertEqual(payload.text.splitlines()[:2], ['0', 'OK'])
        fields = payload.text.splitlines()[2].split('|')
        self.assertEqual(len(fields), 6)
        self.assertEqual(fields[1], '5')
        self.assertIn('submit', payload.text)
        self.service.response(NATIVE_SUBMIT.replace(b'Angler', b'Peer'), self.peer)
        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        rows = list(self.accounts.db.execute('SELECT * FROM ranking_reports ORDER BY id'))
        self.assertEqual([row['user_id'] for row in rows], [self.owner, self.peer])
        self.assertEqual([row['game_class'] for row in rows], ['58600', '58600'])
        self.assertEqual(json.loads(rows[0]['payload']), {
            'TOTAL_XP': 0, 'TOURNAMENT_SCORE': 0, 'FISH_WEIGHT': 0,
            'LOCATION_ID': 378939982, 'TOURNAMENT_ID': 0, 'FISH_ID': 0})
        self.assertEqual(self.accounts.authenticate('ANGLER', 'native-test'), self.owner)

    def test_cannot_submit_for_another_or_missing_account(self):
        for user, body in (
                (None, NATIVE_SUBMIT), (self.peer, NATIVE_SUBMIT),
                (self.owner, NATIVE_SUBMIT.replace(b'<player name="Angler"', b'<player name="Peer"')),
                (self.owner, NATIVE_SUBMIT.replace(b'source="jabber:Angler"', b'source="jabber:Peer"'))):
            with self.subTest(user=user, body=body):
                with self.assertRaises(PermissionError):
                    self.service.response(body, user)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_native_segmented_total_weight_and_item_reports(self):
        for stat, query in [('TOTAL_MASS', '7'), ('TOTAL_ITEMS', '9')]:
            root = ET.fromstring(NATIVE_SUBMIT)
            items = root.find('request/itemlist')
            items.clear()
            for key, value in [(stat, '0'), ('$version', '1'), ('queryid', query)]:
                ET.SubElement(items, 'item', name=key, value=value)
            response = ET.fromstring(self.service.response(ET.tostring(root), self.owner))
            self.assertEqual(response.text.splitlines()[2].split('|')[1], query)
        rows = list(self.accounts.db.execute('SELECT payload FROM ranking_reports ORDER BY id'))
        self.assertEqual([json.loads(row[0]) for row in rows], [{'TOTAL_MASS': 0}, {'TOTAL_ITEMS': 0}])

    def test_malformed_report_never_partially_writes(self):
        invalid = [
            NATIVE_SUBMIT.replace(b'TOTAL_XP" value="0"', b'TOTAL_XP" value="-1"'),
            NATIVE_SUBMIT.replace(b'FISH_WEIGHT" value="0"', b'FISH_WEIGHT" value="4294967296"'),
            NATIVE_SUBMIT.replace(b'TOTAL_XP', b'UNRECOGNIZED_STAT'),
            NATIVE_SUBMIT.replace(b'queryid" value="5"', b'queryid" value="5|forged"'),
            NATIVE_SUBMIT.replace(b'</itemlist>', b'<item name="TOTAL_XP" value="1"/></itemlist>'),
            NATIVE_SUBMIT.replace(b'</rankings>', b'<request type="submit"/></rankings>'),
            NATIVE_SUBMIT.replace(b'<request type="submit"', b'<request type="topn"'),
            b'<!DOCTYPE rankings>'+NATIVE_SUBMIT,
        ]
        for body in invalid:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    self.service.response(body, self.owner)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_native_positive_update_keeps_totals_and_event_boards_separate(self):
        # Native reports from a locally edited save: Barracuda 2.5 kg and Costa Rica Classic 987.
        fish_id, tournament_id = 3885652021, 3164354257
        base = {'TOTAL_XP': 0, 'TOURNAMENT_SCORE': 0, 'FISH_WEIGHT': 0,
                'LOCATION_ID': 378939982, 'TOURNAMENT_ID': 0, 'FISH_ID': 0}
        reports = [dict(base, FISH_ID=fish_id, FISH_WEIGHT=640),
                   dict(base, TOURNAMENT_ID=tournament_id, TOURNAMENT_SCORE=987),
                   dict(base, TOTAL_XP=321), {'TOTAL_MASS': 1280}, {'TOTAL_ITEMS': 3}]
        # After acknowledging journal events, the next native Update sends only the totals.
        for query, values in enumerate(reports + reports[2:], start=1):
            root = ET.fromstring(NATIVE_SUBMIT)
            items = root.find('request/itemlist')
            items.clear()
            for key, value in {**values, '$version': 1, 'queryid': query}.items():
                ET.SubElement(items, 'item', name=key, value=str(value))
            reply = ET.fromstring(self.service.response(ET.tostring(root), self.owner))
            self.assertEqual(reply.text.splitlines()[2].split('|')[1], str(query))

        self.accounts.close()
        self.accounts = AccountStore(self.directory.name)
        self.service = RankingsService(self.accounts, default_games(self.accounts))
        for stat, score, fish, tournament in [
                ('TOTAL_XP', 321, 0, 0), ('TOTAL_MASS', 1280, 0, 0),
                ('TOTAL_ITEMS', 3, 0, 0), ('FISH_WEIGHT', 640, fish_id, 0),
                ('TOURNAMENT_SCORE', 987, 0, tournament_id),
                ('FISH_WEIGHT', None, fish_id + 1, 0)]:
            with self.subTest(stat=stat, fish=fish):
                root = ET.fromstring(NATIVE_TOPN)
                items = root.find('request/itemlist')
                for item in list(items):
                    if item.get('name') == 'stat':
                        item.set('value', stat)
                    if stat in ('TOTAL_MASS', 'TOTAL_ITEMS'):
                        if item.get('name') == 'board':
                            item.set('value', 'highscores')
                        if item.get('name') == 'filters':
                            items.remove(item)
                    elif item.get('name') == 'filters':
                        for entry in item[0]:
                            if entry.get('name') == 'FISH_ID':
                                entry.set('value', str(fish))
                            if entry.get('name') == 'TOURNAMENT_ID':
                                entry.set('value', str(tournament))
                reply = ET.fromstring(self.service.response(ET.tostring(root), None))
                self.assertEqual(reply.text.splitlines()[3:],
                                 [] if score is None else [f'Angler|1|{score}|0'])

    def test_unknown_game_is_not_accepted_by_another_adapter(self):
        with self.assertRaises(UnsupportedRanking):
            self.service.response(NATIVE_SUBMIT.replace(b'58600', b'42318'), self.owner)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_filtered_leaderboard_uses_each_accounts_best_matching_report(self):
        for user, name, score, location in [
                (self.owner, 'Angler', 100, 378939982),
                (self.owner, 'Angler', 80, 378939982),
                (self.owner, 'Angler', 900, 123),
                (self.peer, 'Peer', 100, 378939982)]:
            report = NATIVE_SUBMIT.replace(b'Angler', name.encode())
            report = report.replace(b'TOTAL_XP" value="0"', f'TOTAL_XP" value="{score}"'.encode())
            report = report.replace(b'378939982', str(location).encode())
            self.service.response(report, user)
        adapter = self.service.games.games['58600']
        rows = adapter.reports.high_scores('58600', 'TOTAL_XP',
                                          {'LOCATION_ID': 378939982, 'TOURNAMENT_ID': 0, 'FISH_ID': 0}, 0, 8)
        self.assertEqual([dict(row) for row in rows], [
            {'name': 'Angler', 'score': 100, 'rank': 1}, {'name': 'Peer', 'score': 100, 'rank': 1}])
        reply = ET.fromstring(self.service.response(NATIVE_TOPN, self.owner)).text.splitlines()
        self.assertEqual(reply[:2], ['0', 'OK'])
        self.assertEqual(len(reply[2].split('|')), 8)
        self.assertEqual(reply[2].split('|')[1], '6')
        self.assertEqual(len(reply[3:]), 2)
        self.assertNotIn('900', '|'.join(reply))
        paged = NATIVE_TOPN.replace(b'offset" value="0"', b'offset" value="1"')
        paged = paged.replace(b'limit" value="8"', b'limit" value="1"')
        page = ET.fromstring(self.service.response(paged, self.owner)).text.splitlines()[3:]
        self.assertEqual(len(page), 1)
        self.assertIn('Peer', page[0])

    def test_empty_and_invalid_filtered_queries_do_not_mutate_scores(self):
        reply = ET.fromstring(self.service.response(NATIVE_TOPN, self.owner)).text.splitlines()
        self.assertEqual(len(reply), 3)
        for body in [
                NATIVE_TOPN.replace(b'LOCATION_ID', b'UNKNOWN_FILTER'),
                NATIVE_TOPN.replace(b'378939982', b'-1'),
                NATIVE_TOPN.replace(b'limit" value="8"', b'limit" value="0"'),
                NATIVE_TOPN.replace(b'limit" value="8"', b'limit" value="101"'),
                NATIVE_TOPN.replace(b'LOCATION_ID" value="378939982"', b'FISH_ID" value="0"'),
                NATIVE_TOPN.replace(b'alltime', b'arbitrary'),
                NATIVE_TOPN.replace(b'<item  name="FISH_ID" value="0"/>',
                                    b'<item name="FISH_ID"><itemlist/></item>')]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.service.response(body, self.owner)
        self.assertEqual(self.accounts.db.execute('SELECT count(*) FROM ranking_reports').fetchone()[0], 0)

    def test_public_topn_does_not_depend_on_a_readers_identity(self):
        self.service.response(NATIVE_SUBMIT, self.owner)
        expected = self.service.response(NATIVE_TOPN, self.owner)
        self.assertEqual(self.service.response(NATIVE_TOPN, None), expected)
        query = NATIVE_TOPN.replace(b'Angler', b'Visitor')
        self.assertEqual(self.service.response(query, None), expected)
        self.assertEqual(self.service.response(query, self.peer), expected)
        with self.assertRaises(PermissionError):
            self.service.response(NATIVE_SUBMIT, None)

    def test_public_nearby_ranks_center_on_the_requested_player(self):
        third = self.accounts.create_user('Third', 'native-test')
        for user, name, score in [(self.owner, 'Angler', 100), (self.peer, 'Peer', 80), (third, 'Third', 60)]:
            report = NATIVE_SUBMIT.replace(b'Angler', name.encode())
            report = report.replace(b'TOTAL_XP" value="0"', f'TOTAL_XP" value="{score}"'.encode())
            self.service.response(report, user)
        query = NATIVE_PROXIMITY.replace(b'name" value="Angler"', b'name" value="Peer"')
        rows = ET.fromstring(self.service.response(query, None)).text.splitlines()[3:]
        self.assertEqual([row.split('|')[0] for row in rows], ['Angler', 'Peer', 'Third'])
        self.assertEqual([row.split('|')[1] for row in rows], ['1', '2', '3'])
        missing = query.replace(b'name" value="Peer"', b'name" value="Missing"')
        self.assertEqual(len(ET.fromstring(self.service.response(missing, None)).text.splitlines()), 3)
        first = ET.fromstring(self.service.response(NATIVE_PROXIMITY, None)).text.splitlines()[3:]
        self.assertEqual(len(first), 2)
        with self.assertRaises(ValueError):
            self.service.response(query.replace(b'above" value="1"', b'above" value="101"'), None)
