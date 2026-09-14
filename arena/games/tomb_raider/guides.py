"""Native room/tile links from Tomb Raider's adverts.dat reader."""
from collections import Counter
import struct


def encode_links(records):
    result = bytearray()
    counts = Counter()
    for record in records:
        level,room = record['level'],record['room']
        xmin,zmin,xmax,zmax = record.get('bounds',[0,0,31,31])
        directory = record.get('directory',1402+level)
        values = (level,room,xmin,zmin,xmax,zmax,directory)
        if any(type(value) is not int for value in values):
            raise ValueError('Guide link fields must be integers')
        if not 0 <= level <= 15 or not 0 <= room <= 255:
            raise ValueError('Guide link level or room is out of range')
        if not 0 <= xmin <= xmax <= 31 or not 0 <= zmin <= zmax <= 31:
            raise ValueError('Guide bounds must be ordered room-relative tiles in 0..31')
        if not 1 <= directory <= 65535:
            raise ValueError('The native strategy argument has a 16-bit directory ID')
        counts[level] += 1
        if counts[level] > 100:
            raise ValueError('The game loads at most 100 guide links per level')
        word = room | (zmin<<8) | (xmin<<13) | (zmax<<18) | (xmax<<23) | (level<<28)
        result.extend(struct.pack('<II',word,directory))
    return bytes(result)


def decode_links(data):
    if len(data) % 8:
        raise ValueError('Guide link data must contain complete eight-byte records')
    records = []
    for word,directory in struct.iter_unpack('<II',data):
        records.append({'level':word>>28,'room':word&255,
            'bounds':[(word>>13)&31,(word>>8)&31,(word>>23)&31,(word>>18)&31],
            'directory':directory})
    encode_links(records)
    return records
