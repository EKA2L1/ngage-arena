"""Read owned High Seize resources and inspect the initial NDL battlefield."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import struct
from zipfile import BadZipFile, ZipFile
import zlib


MAX_PACK_SIZE = 512 * 1024 * 1024
MAX_RESOURCE_SIZE = 64 * 1024 * 1024
MAX_MAP_CELLS = 65536


def file_hash(name):
    name = name.replace('\\', '/')
    if name.startswith('.'):
        name = name[2:]
    try:
        encoded = name.encode('ascii')
    except UnicodeEncodeError as error:
        raise ValueError('FilePack paths must be ASCII') from error
    if not encoded or b'\0' in encoded:
        raise ValueError('Invalid FilePack path')
    seed, value = len(encoded), 0
    # FilePack::open uses an evolving multiplier, not CRC32.
    for byte in encoded.upper():
        value = (value + seed * byte) & 0xffffffff
        seed = (seed & 0xffff) * 18000 + (seed >> 16)
    return value & 0x7fffffff


@dataclass(frozen=True)
class Resource:
    hash: int
    packed_size: int
    size: int
    compressed: int
    offset: int


class FilePack:
    def __init__(self, data):
        if not 8 <= len(data) <= MAX_PACK_SIZE:
            raise ValueError('Invalid FilePack size')
        header_size, count = struct.unpack_from('<II', data)
        if not count or header_size != 8 + count * 17 or header_size > len(data):
            raise ValueError('Invalid FilePack directory')
        self.data = data
        self.entries = {}
        intervals = []
        for index in range(count):
            entry = Resource(*struct.unpack_from('<IIIBI', data, 8 + index * 17))
            if (entry.hash in self.entries or entry.compressed not in (0, 1)
                    or entry.size > MAX_RESOURCE_SIZE or entry.offset < header_size
                    or entry.offset + entry.packed_size > len(data)
                    or (not entry.compressed and entry.packed_size != entry.size)):
                raise ValueError('Invalid FilePack resource')
            self.entries[entry.hash] = entry
            intervals.append((entry.offset, entry.offset + entry.packed_size))
        end = header_size
        for start, stop in sorted(intervals):
            if start < end:
                raise ValueError('Overlapping FilePack resources')
            end = stop

    @classmethod
    def open(cls, path):
        path = Path(path)
        if path.suffix.lower() == '.zip':
            with ZipFile(path) as archive:
                candidates = [entry for entry in archive.infolist()
                              if entry.filename.replace('\\', '/').lower()
                              == 'system/apps/6r36/data/data.pak']
                if len(candidates) != 1 or candidates[0].file_size > MAX_PACK_SIZE:
                    raise ValueError('Expected one High Seize data.pak in the ZIP')
                return cls(archive.read(candidates[0]))
        if path.stat().st_size > MAX_PACK_SIZE:
            raise ValueError('FilePack exceeds the resource limit')
        return cls(path.read_bytes())

    def read(self, name):
        entry = self.entries.get(file_hash(name))
        if entry is None:
            raise ValueError(f'FilePack resource not found: {name}')
        data = self.data[entry.offset:entry.offset + entry.packed_size]
        if entry.compressed:
            inflater = zlib.decompressobj()
            try:
                data = inflater.decompress(data, entry.size + 1)
            except zlib.error as error:
                raise ValueError(f'Invalid compressed resource: {name}') from error
            if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                raise ValueError(f'Incomplete or trailing compressed resource: {name}')
        if len(data) != entry.size:
            raise ValueError(f'Incorrect resource size: {name}')
        return data

    def names(self):
        reader = Reader(self.read('filepack.list'))
        count, = reader.unpack('<I')
        if count != len(self.entries) - 1:
            raise ValueError('FilePack catalogue count mismatch')
        names, seen = [], {file_hash('filepack.list')}
        for _ in range(count):
            size, = reader.unpack('<H')
            try:
                name = reader.take(size).decode('ascii')
            except UnicodeDecodeError as error:
                raise ValueError('Invalid FilePack catalogue path') from error
            key = file_hash(name)
            if key in seen or key not in self.entries:
                raise ValueError('FilePack catalogue hash mismatch')
            seen.add(key)
            names.append(name)
        reader.finish()
        return tuple(names)


class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, size):
        end = self.offset + size
        if size < 0 or end > len(self.data):
            raise ValueError('Truncated resource')
        data = self.data[self.offset:end]
        self.offset = end
        return data

    def unpack(self, layout):
        return struct.unpack(layout, self.take(struct.calcsize(layout)))

    def finish(self):
        if self.offset != len(self.data):
            raise ValueError('Trailing resource data')


@dataclass(frozen=True)
class Section:
    kind: int
    version: int
    variant: int
    data: bytes


@dataclass(frozen=True)
class Placement:
    x: int
    y: int
    type_id: int
    owner: int
    object_id: int
    direction: int = 0


@dataclass(frozen=True)
class Level:
    width: int
    height: int
    terrain: tuple
    units: tuple
    properties: tuple
    sections: tuple

    @classmethod
    def decode(cls, data):
        reader = Reader(data)
        magic, version, _, _, _, width, height, _, _ = reader.unpack('<3sHIIBHHBB')
        if magic != b'NDL' or version != 0x100:
            raise ValueError('Unsupported NDL header')
        if not width or not height or width * height > MAX_MAP_CELLS:
            raise ValueError('Invalid NDL dimensions')
        sections = {}
        while reader.offset < len(data):
            size, kind, version, variant = reader.unpack('<IIHB')
            if size < 11 or kind in sections:
                raise ValueError('Invalid or duplicate NDL section')
            sections[kind] = Section(kind, version, variant, reader.take(size - 11))

        def grid(kind, version, stride):
            section = sections.get(kind)
            if section is None or (section.version, section.variant) != (version, 0):
                raise ValueError(f'Unsupported or missing NDL grid: {kind:#x}')
            if len(section.data) != width * height * stride:
                raise ValueError('NDL grid size mismatch')
            return section.data

        terrain = tuple(value for value, in struct.iter_unpack('<H', grid(1, 0x100, 2)))

        def placements(kind):
            result = []
            for index, (value,) in enumerate(struct.iter_unpack('<I', grid(kind, 0x101, 4))):
                if value:
                    unit = kind == 0x100
                    result.append(Placement(index % width, index // width, value & 255,
                                            (value >> 8) & 255,
                                            (value >> 16) & (0x3fff if unit else 0xffff),
                                            value >> 30 if unit else 0))
            return tuple(result)

        return cls(width, height, terrain, placements(0x100), placements(0x10),
                   tuple(sections.values()))

    def summary(self):
        return {'width': self.width, 'height': self.height,
                'units': [asdict(unit) for unit in self.units],
                'properties': [asdict(prop) for prop in self.properties],
                'sections': [{'kind': section.kind, 'version': section.version,
                              'variant': section.variant, 'size': len(section.data)}
                             for section in self.sections]}


def inspect(pack, verify=False):
    names = pack.names()
    levels = {}
    for name in names:
        if name.lower().endswith('.ndl'):
            data = pack.read(name)
            levels[name] = {'sha256': hashlib.sha256(data).hexdigest(),
                            **Level.decode(data).summary()}
        elif verify:
            pack.read(name)
    return {'pack_sha256': hashlib.sha256(pack.data).hexdigest(),
            'resources': len(names), 'verified_all_resources': verify, 'levels': levels}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Owned data.pak or the original High Seize ZIP')
    parser.add_argument('--verify', action='store_true', help='Decompress and validate every resource')
    args = parser.parse_args()
    try:
        result = inspect(FilePack.open(args.source), args.verify)
    except (OSError, ValueError, BadZipFile) as error:
        parser.exit(1, f'Content inspection failed: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
