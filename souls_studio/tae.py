"""Read gameplay event types from DS3 and Nightreign TimeAct tables."""
import struct


def tae_event_types(data):
    if data[:8] != b"TAE \0\0\0\xff" or data[8:12] not in (b"\x0c\0\x01\0", b"\x0d\0\x01\0"):
        return {}
    count, table = struct.unpack_from("<IQ", data, 0x54)
    if table > len(data) or table + count * 16 > len(data):
        raise ValueError("Invalid TAE animation table")
    animations = {}
    for index in range(count):
        animation, body = struct.unpack_from("<QQ", data, table + index * 16)
        if body + 36 > len(data):
            raise ValueError("Invalid TAE animation body")
        events = struct.unpack_from("<Q", data, body)[0]
        event_count = struct.unpack_from("<I", data, body + 32)[0]
        if events > len(data) or events + event_count * 24 > len(data):
            raise ValueError("Invalid TAE event table")
        types = set()
        for event in range(event_count):
            offset = struct.unpack_from("<Q", data, events + event * 24 + 16)[0]
            if offset + 4 > len(data):
                raise ValueError("Invalid TAE event data")
            types.add(struct.unpack_from("<I", data, offset)[0])
        animations[animation] = types
    return animations


def event_label(types):
    if 304 in types:
        return "Throw Attack"
    if 2 in types:
        return "Projectile"
    if 1 in types:
        return "Attack"
    return ""
