import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile
import zlib

from arena.games.high_seize.content import FilePack, Level, Placement, file_hash, inspect


def make_pack(files):
    catalogue = struct.pack('<I', len(files))
    for name, _, _ in files:
        catalogue += struct.pack('<H', len(name)) + name.encode('ascii')
    files = [*files, ('filepack.list', catalogue, False)]
    header_size = 8 + len(files) * 17
    header = struct.pack('<II', header_size, len(files))
    body = b''
    for name, data, compressed in files:
        payload = zlib.compress(data) if compressed else data
        header += struct.pack('<IIIBI', file_hash(name), len(payload), len(data),
                              compressed, header_size + len(body))
        body += payload
    return header + body


def section(kind, data, version=0x100, variant=0):
    return struct.pack('<IIHB', 11 + len(data), kind, version, variant) + data


HEADER = bytes.fromhex('4e444c 0001 0f000000 00000000 00 0200 0200 01 04')
TERRAIN = bytes.fromhex('0000010008020300')
UNITS = bytes.fromhex('00000000010245e30000000007012200')
PROPERTIES = bytes.fromhex('0500feff000000000000000005010200')


def level_bytes():
    return (HEADER + section(1, TERRAIN) + section(0x10, PROPERTIES, 0x101)
            + section(0x100, UNITS, 0x101))


class HighSeizeFilePackTests(unittest.TestCase):
    def test_native_hash_vectors_and_path_normalization(self):
        self.assertEqual(file_hash('filepack.list'), 0x5d9d93e8)
        for name in ('Data\\anim\\01-Intro.lap', './data/anim/01-intro.lap',
                     '.\\DATA/ANIM/01-INTRO.LAP'):
            self.assertEqual(file_hash(name), 0x6fbf0616)
        self.assertEqual(file_hash('Data/Levels/mp1-s2p_first_blood.ndl'), 0x7e91e641)
        for name in ('', './', 'data\0.txt', '非ASCII'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                file_hash(name)

    def test_catalogue_and_both_storage_modes(self):
        pack = FilePack(make_pack([('Data/A.txt', b'alpha', True),
                                   ('Data/B.txt', b'beta', False)]))
        self.assertEqual(pack.names(), ('Data/A.txt', 'Data/B.txt'))
        self.assertEqual(pack.read('.\\data\\a.TXT'), b'alpha')
        self.assertEqual(pack.read('DATA/B.txt'), b'beta')
        with self.assertRaises(ValueError):
            pack.read('Data/missing.txt')

    def test_catalogue_is_resolved_by_hash_not_directory_order(self):
        data = bytearray(make_pack([('A', b'alpha', True), ('B', b'beta', False)]))
        data[8:25], data[25:42] = data[25:42], data[8:25]
        pack = FilePack(bytes(data))
        self.assertEqual(pack.names(), ('A', 'B'))
        self.assertEqual(pack.read('A'), b'alpha')

    def test_invalid_directory_bounds_flags_overlap_and_hashes(self):
        original = make_pack([('A', b'alpha', False)])
        cases = [b'', original[:7], original[:15], original[:-1]]
        for offset, layout, value in ((0, '<I', 8), (4, '<I', 0),
                                      (20, '<B', 2), (23, '<H', 0xffff),
                                      (21, '<I', 8), (12, '<I', 0xffffffff),
                                      (16, '<I', 0xffffffff),
                                      (25, '<I', file_hash('A')),
                                      (38, '<I', 42)):
            malformed = bytearray(original)
            struct.pack_into(layout, malformed, offset, value)
            cases.append(bytes(malformed))
        for data in cases:
            with self.subTest(data=data.hex()), self.assertRaises(ValueError):
                FilePack(data)

    def test_catalogue_rejects_missing_duplicate_and_trailing_entries(self):
        original = make_pack([('A', b'alpha', False)])
        for catalogue in (bytes.fromhex('01000000010042'),
                          bytes.fromhex('02000000010041010041'),
                          bytes.fromhex('0100000001004100')):
            data = bytearray(original[:47] + catalogue)
            struct.pack_into('<II', data, 29, len(catalogue), len(catalogue))
            with self.subTest(catalogue=catalogue.hex()), self.assertRaises(ValueError):
                FilePack(bytes(data)).names()

    def test_compression_must_end_at_declared_size(self):
        original = make_pack([('A', b'alpha' * 50, True)])
        for declared in (0, 249, 251):
            data = bytearray(original)
            struct.pack_into('<I', data, 16, declared)
            with self.subTest(size=declared), self.assertRaises(ValueError):
                FilePack(bytes(data)).read('A')
        data = bytearray(original)
        data[42] = 0
        with self.assertRaises(ValueError):
            FilePack(bytes(data)).read('A')
        # A second valid zlib stream cannot hide behind the first one.
        packed = zlib.compress(b'a') + zlib.compress(b'b')
        data = struct.pack('<II', 25, 1) + struct.pack('<IIIBI', file_hash('A'),
                                                    len(packed), 1, 1, 25) + packed
        with self.assertRaises(ValueError):
            FilePack(data).read('A')

    def test_original_zip_is_read_without_extracting_game_files(self):
        data = make_pack([('A', b'alpha', True)])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'owned.zip'
            with ZipFile(source, 'w') as archive:
                archive.writestr('system/apps/6r36/data/DATA.PAK', data)
            self.assertEqual(FilePack.open(source).read('A'), b'alpha')
            self.assertEqual(list(Path(directory).iterdir()), [source])
            with ZipFile(source, 'w') as archive:
                archive.writestr('unrelated/data.pak', data)
            with self.assertRaises(ValueError):
                FilePack.open(source)


class HighSeizeLevelTests(unittest.TestCase):
    def test_native_grid_fields_and_row_major_coordinates(self):
        level = Level.decode(level_bytes())
        self.assertEqual((level.width, level.height), (2, 2))
        self.assertEqual(level.terrain, (0, 1, 0x208, 3))
        self.assertEqual(level.units, (Placement(1, 0, 1, 2, 0x2345, 3),
                                       Placement(1, 1, 7, 1, 34)))
        self.assertEqual(level.properties, (Placement(0, 0, 5, 0, 65534),
                                            Placement(1, 1, 5, 1, 2)))

    def test_other_sections_are_preserved_without_invented_rules(self):
        data = level_bytes() + section(0x1000, b'opaque script records')
        level = Level.decode(data)
        self.assertEqual(level.sections[-1].data, b'opaque script records')
        report = inspect(FilePack(make_pack([('Data/test.ndl', data, True)])), True)
        decoded = json.loads(json.dumps(report))
        self.assertEqual(decoded['levels']['Data/test.ndl']['units'][0]['object_id'], 0x2345)
        self.assertTrue(decoded['verified_all_resources'])

    def test_invalid_headers_grids_and_sections(self):
        original = level_bytes()
        cases = [b'', original[:19], original[:-1], original + b'\0',
                 original + section(1, TERRAIN),
                 HEADER + section(1, TERRAIN[:-2]) + original[39:],
                 HEADER + section(1, TERRAIN, 0x101) + original[39:],
                 HEADER + section(1, TERRAIN, variant=1) + original[39:],
                 HEADER + section(1, TERRAIN)]
        for offset, layout, value in ((0, '<B', 0), (3, '<H', 0x101),
                                      (14, '<H', 0), (14, '<I', 0xffffffff),
                                      (20, '<I', 0), (20, '<I', 0xffffffff)):
            malformed = bytearray(original)
            struct.pack_into(layout, malformed, offset, value)
            cases.append(bytes(malformed))
        for data in cases:
            with self.subTest(data=data.hex()), self.assertRaises(ValueError):
                Level.decode(data)


if __name__ == '__main__':
    unittest.main()
