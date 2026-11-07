"""Read DS3 display masks and localized weapon names from game data."""
from collections import defaultdict
from pathlib import PureWindowsPath
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from soulstruct.base.text.fmg import FMG
from soulstruct.containers import Binder


DS3_REGULATION_KEY = b"ds3#jn/8_7(rsY9pg55GFN7VFL#+3n/)"
DS3_WEAPON_NAME_ENTRIES = {11, 211, 251}


def param_rows(data, minimum_row_size):
    if len(data) < 64 or data[44] != 0 or not data[45] & 0x04:
        raise ValueError("Unsupported PARAM header")
    count = struct.unpack_from("<H", data, 10)[0]
    table_end = 64 + count * 24
    if table_end > len(data):
        raise ValueError("Truncated PARAM row table")
    for index in range(count):
        id, offset, _ = struct.unpack_from("<i4xQQ", data, 64 + index * 24)
        if offset < table_end or offset + minimum_row_size > len(data):
            raise ValueError("Invalid PARAM row offset")
        yield id, memoryview(data)[offset:offset + minimum_row_size]


def decrypt_regulation(data, key):
    if data.startswith((b"BND4", b"DCX\0")):
        return Binder.from_bytes(data)
    if len(data) < 32:
        raise ValueError("Truncated regulation")
    iv, payload = data[:16], data[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    payload += bytes(-len(payload) % 16)
    return Binder.from_bytes(decryptor.update(payload) + decryptor.finalize())


def ds3_metadata(files):
    path = files.root / "Data0.bdt"
    if not path.is_file():
        return {}, {}
    regulation = decrypt_regulation(path.read_bytes(), DS3_REGULATION_KEY)
    tables = {PureWindowsPath(entry.path).name.lower(): entry for entry in regulation.entries}

    masks = {}
    npc = tables.get("npcparam.param")
    if npc:
        rows = param_rows(npc.get_uncompressed_data(), 0x14C)
        for id, row in sorted(rows, key=lambda entry: entry[0]):
            model = f"c{id // 100:04}"
            data = bytes(row[0x146:0x148]) + bytes(row[0x14A:0x14C])
            flags = int.from_bytes(data, "little")
            masks.setdefault(model, frozenset(f"{i:02}" for i in range(32) if flags & (1 << i)))

    names = {}
    for msg in sorted(name for name in files.files if name.startswith("msg/engus/")):
        for entry in Binder.from_bytes(files.read(msg)).entries:
            if entry.entry_id in DS3_WEAPON_NAME_ENTRIES:
                names.update(FMG.from_bytes(entry.get_uncompressed_data()).entries)

    weapons = defaultdict(list)
    equip = tables.get("equipparamweapon.param")
    if equip:
        rows = param_rows(equip.get_uncompressed_data(), 0xBA)
        for id, row in sorted(rows, key=lambda entry: entry[0]):
            name = names.get(id, "").strip()
            if not name or name == "?":
                continue
            model = f"wp_a_{struct.unpack_from('<H', row, 0xB8)[0]:04}"
            if name not in weapons[model]:
                weapons[model].append(name)
    return masks, {model: tuple(labels) for model, labels in weapons.items()}
