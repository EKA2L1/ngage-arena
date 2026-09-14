import unittest

from arena.games.tomb_raider.guides import decode_links, encode_links


class GuideLinkTests(unittest.TestCase):
    def test_native_caves_region(self):
        record = {'level':1,'room':0,'bounds':[0,0,31,31],'directory':1403}
        data = bytes.fromhex('0000fc1f7b050000')
        self.assertEqual(encode_links([record]),data)
        self.assertEqual(decode_links(data),[record])

    def test_distinct_tile_fields_and_directory_width(self):
        data = bytes.fromhex('ff229021ffff0000')
        record = {'level':2,'room':255,'bounds':[1,2,3,4],'directory':65535}
        self.assertEqual(encode_links([record]),data)
        self.assertEqual(decode_links(data),[record])

    def test_reject_invalid_regions_and_client_limits(self):
        for record in ({'level':16,'room':0}, {'level':1,'room':256},
                       {'level':1,'room':0,'bounds':[4,0,3,31]},
                       {'level':1,'room':0,'directory':65536}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                encode_links([record])
        with self.assertRaises(ValueError):
            decode_links(b'\0')
        with self.assertRaises(ValueError):
            encode_links([{'level':1,'room':0}]*101)
