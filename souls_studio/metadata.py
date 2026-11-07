"""Read display masks and localized weapon names from game data."""
from collections import defaultdict
from pathlib import PureWindowsPath
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from soulstruct.base.text.fmg import FMG
from soulstruct.containers import Binder


DS3_REGULATION_KEY = b"ds3#jn/8_7(rsY9pg55GFN7VFL#+3n/)"
DS3_WEAPON_NAME_ENTRIES = {11, 211, 251}
ER_REGULATION_KEY = bytes.fromhex("99bffc366a6bc8c6f5827d093602d676c42892a01c207fb024d3af4e493fef99")


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


def decrypt_regulation(data, key, unwrap=None):
    if not data.startswith((b"BND4", b"DCX\0")):
        if len(data) < 32:
            raise ValueError("Truncated regulation")
        iv, payload = data[:16], data[16:]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        payload += bytes(-len(payload) % 16)
        data = decryptor.update(payload) + decryptor.finalize()
    return Binder.from_bytes(unwrap(data) if unwrap else data)


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

    return masks, weapon_labels(files, tables.get("equipparamweapon.param"), 0xB8, DS3_WEAPON_NAME_ENTRIES)


def weapon_labels(files, equip, offset, fmg_ids):
    if equip is None:
        return {}
    names = {}
    for msg in sorted(name for name in files.files if name.startswith("msg/engus/")):
        for entry in Binder.from_bytes(files.read(msg)).entries:
            if entry.entry_id in fmg_ids:
                names.update(FMG.from_bytes(entry.get_uncompressed_data()).entries)

    weapons = defaultdict(list)
    rows = param_rows(equip.get_uncompressed_data(), offset + 2)
    for id, row in sorted(rows, key=lambda entry: entry[0]):
        name = names.get(id, "").strip()
        if not name or name.casefold() in {"?", "[error]"}:
            continue
        model = f"wp_a_{struct.unpack_from('<H', row, offset)[0]:04}"
        if name not in weapons[model]:
            weapons[model].append(name)
    return {model: tuple(labels) for model, labels in weapons.items()}


def elden_ring_metadata(files):
    path = files.root / "regulation.bin"
    if not path.is_file():
        return {}, {}
    regulation = decrypt_regulation(path.read_bytes(), ER_REGULATION_KEY, files.unwrap)
    equip = next((entry for entry in regulation.entries
                  if PureWindowsPath(entry.path).name.lower() == "equipparamweapon.param"), None)
    return {}, weapon_labels(files, equip, 0xBC, {11, 310, 410})
