import struct


def commander_wire(name=b'Captain', description=b'5200', control=1, slot=1):
    data = b'CMM01' + struct.pack('<4iB5i', control, 0, 0, slot - 1, 1, 0, 28, slot, 0, 0)
    data += bytes(37) + bytes(30) + struct.pack('<i', 4)
    for text in (name, description):
        data += struct.pack('<I', len(text)) + text + b'\0'
    data += struct.pack('<iI', 0, 8) * 42
    data += bytes(21 * 4 * 6) + bytes(30) + struct.pack('<ii', 0, slot)
    return data
