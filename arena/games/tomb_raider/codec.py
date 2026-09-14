"""Little-endian AirPlay UDP messages, decoded from the retail ARM client."""
import struct
from dataclasses import dataclass

HEADER = struct.Struct('<IBBH')
MAX_STRING = 4096
CHUNK_SIZE = 1200

class ProtocolError(ValueError):
    pass

class Reader:
    def __init__(self, data):
        self.data = memoryview(data)
        self.offset = 0

    def take(self, length):
        if length < 0 or self.offset + length > len(self.data):
            raise ProtocolError('truncated message')
        start = self.offset
        self.offset += length
        return bytes(self.data[start:self.offset])

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))

    def u32(self):
        return self.unpack('I')[0]

    def string(self, limit=MAX_STRING):
        length = self.u32()
        if length > limit:
            raise ProtocolError('string exceeds limit')
        return self.take(length).decode('latin-1')

    def finish(self):
        if self.offset != len(self.data):
            raise ProtocolError('unexpected trailing bytes')


def string(value, limit=MAX_STRING):
    data = value.encode('latin-1', errors='replace')[:limit]
    return struct.pack('<I', len(data)) + data

@dataclass(frozen=True)
class Object:
    id: int
    kind: int
    name: str
    name2: str = ''
    billing: int = 0
    value1: int = 0
    value2: int = 0
    value3: int = 0
    value4: int = 0

    def encode(self):
        return struct.pack('<IHHIIII', self.id, self.kind, self.billing,
                           self.value1 & 0xffffffff, self.value2 & 0xffffffff, self.value3 & 0xffffffff, self.value4 & 0xffffffff) + string(self.name, 20) + string(self.name2, 20)


def pages(records, prefix=b'', budget=1100):
    chunks, current, size = [], [], 3 + len(prefix)
    for record in records:
        if current and (size + len(record) > budget or len(current) == 255):
            chunks.append(current)
            current, size = [], 3 + len(prefix)
        if len(record) + 3 + len(prefix) > budget:
            raise ProtocolError('record exceeds packet size')
        current.append(record)
        size += len(record)
    chunks.append(current)
    if len(chunks) > 255:
        raise ProtocolError('too many directory pages')
    return [bytes((len(chunk), index, len(chunks))) + prefix + b''.join(chunk)
            for index, chunk in enumerate(chunks)]


def file_chunks(data, object_id=None):
    if not data:
        raise ProtocolError('empty files are not supported by this client')
    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start:start + CHUNK_SIZE]
        result = struct.pack('<4I', len(data), start, start + len(chunk) - 1, len(chunk)) + chunk
        if object_id is not None:
            result += struct.pack('<I', object_id)
        yield result
