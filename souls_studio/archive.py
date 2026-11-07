"""Read-only access to FromSoftware BHD5/BDT archives."""
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import load_pem_public_key


@dataclass(frozen=True)
class ArchiveProfile:
    reference: str
    archives: tuple
    wide_hash: bool = False


DS3 = ArchiveProfile("DarkSouls3", ("Data1", "Data2", "Data3", "Data4", "Data5", "DLC1", "DLC2"))
NIGHTREIGN = ArchiveProfile("EldenRingNightreign", ("Data0", "Data1", "Data2", "Data3"), True)


def path_hash(path, wide=False):
    result = 0
    prime, mask = (0x85, 0xFFFFFFFFFFFFFFFF) if wide else (37, 0xFFFFFFFF)
    for char in "/" + path.replace("\\", "/").lower().lstrip("/"):
        result = (result * prime + ord(char)) & mask
    return result


def decrypt_header(data, key):
    if data.startswith(b"BHD5"):
        return data
    numbers = load_pem_public_key(key).public_numbers()
    width = (numbers.n.bit_length() + 7) // 8
    if len(data) % width:
        raise ValueError("Truncated encrypted BHD header")
    return b"".join(
        pow(int.from_bytes(data[i:i + width], "big"), numbers.e, numbers.n)
        .to_bytes(width - 1, "big")
        for i in range(0, len(data), width)
    )


@dataclass(frozen=True)
class Entry:
    archive: Path
    offset: int
    padded: int
    size: int
    key: bytes = b""
    ranges: tuple = ()

    def read(self):
        with self.archive.open("rb") as stream:
            stream.seek(self.offset)
            data = bytearray(stream.read(self.padded))
        if len(data) != self.padded:
            raise ValueError(f"Truncated archive entry in {self.archive.name}")
        if self.key:
            decryptor = Cipher(algorithms.AES(self.key), modes.ECB()).decryptor()
            for start, end in self.ranges:
                data[start:end] = decryptor.update(data[start:end])
            decryptor.finalize()
        return bytes(data[:self.size])


def read_index(header, archive, wanted, wide_hash=False):
    if header[:4] != b"BHD5" or header[4] not in (0, 255):
        raise ValueError(f"Invalid BHD header for {archive.name}")
    endian = "<" if header[4] == 255 else ">"
    wide_table = len(header) > 40 and struct.unpack_from(endian + "I", header, 20)[0] == 0 and struct.unpack_from(endian + "I", header, 28)[0] == 0
    count, table = struct.unpack_from(endian + ("QQ" if wide_table else "II"), header, 16)
    bucket_size = 16 if wide_table else 8
    if table + count * bucket_size > len(header):
        raise ValueError(f"Invalid bucket table in {archive.name}")
    for bucket in range(count):
        entries, offset = struct.unpack_from(endian + ("I4xQ" if wide_table else "II"),
                                             header, table + bucket * bucket_size)
        if offset + entries * 40 > len(header):
            raise ValueError(f"Invalid file table in {archive.name}")
        for index in range(entries):
            row = offset + index * 40
            if wide_hash:
                digest, padded, size, start, _, aes = struct.unpack_from(endian + "QIIQqq", header, row)
            else:
                digest, padded, start, _, aes, size = struct.unpack_from(endian + "IIQqqq", header, row)
            if digest not in wanted:
                continue
            size = size or padded
            if not 0 < size <= padded:
                raise ValueError(f"Invalid entry size in {archive.name}: {wanted[digest]}")
            key, ranges = b"", []
            if aes:
                key, range_count = struct.unpack_from(endian + "16sI", header, aes)
                for i in range(range_count):
                    lo, hi = struct.unpack_from(endian + "qq", header, aes + 20 + i * 16)
                    if lo == -1 or hi == -1 or lo == hi:
                        continue
                    if not 0 <= lo < hi <= padded or (hi - lo) % 16:
                        raise ValueError(f"Invalid AES range in {archive.name}")
                    ranges.append((lo, hi))
            yield wanted[digest], Entry(archive, start, padded, size, key, tuple(ranges))


def relevant(name):
    return bool(re.fullmatch(
        r"(?:chr/c\d{4}(?:_[\w]+)?\.(?:chrbnd|anibnd|texbnd|tpf)"
        r"|parts/wp_[a-z]_\d+(?:_[\w]+)?\.(?:partsbnd|anibnd|texbnd|tpf)"
        r"|msg/engus/item(?:_dlc\d+)?\.msgbnd"
        r"|mtd/allmaterialbnd\.mtdbnd|material/allmaterial(?:_dlc\d+)?\.matbinbnd)(?:\.dcx)?", name))


class GameFiles:
    def __init__(self, root, reference, profile=DS3, progress=lambda _: None):
        self.root = Path(root).resolve()
        self.oodle = None
        self.files = {}
        pairs = [name for name in profile.archives
                 if (self.root / f"{name}.bhd").is_file() and (self.root / f"{name}.bdt").is_file()]
        if pairs:
            uxmdir = reference / "UXM"
            lookup = uxmdir / "keys.json"
            if lookup.is_file():
                keys = json.loads(lookup.read_text(encoding="utf-8"))[profile.reference]
            else:
                section = (uxmdir / "ArchiveKeys.cs").read_text(encoding="utf-8-sig")
                section = section.split(profile.reference + "Keys", 1)[1].split("};", 1)[0]
                keys = dict(re.findall(
                    r'\["(\w+)"\]\s*=\s*@"(-----BEGIN RSA PUBLIC KEY-----.*?-----END RSA PUBLIC KEY-----)"',
                    section, re.S))
            names = (uxmdir / f"res/{profile.reference}Dictionary.txt").read_text(encoding="utf-8-sig")
            wanted = {}
            for line in names.splitlines():
                name = line.strip().lower().lstrip("/")
                if relevant(name):
                    digest = path_hash(name, profile.wide_hash)
                    if digest in wanted and wanted[digest] != name:
                        raise ValueError(f"Archive hash collision for {name}")
                    wanted[digest] = name
            for name in pairs:
                progress(f"Indexing {name}")
                header = decrypt_header((self.root / f"{name}.bhd").read_bytes(), keys[name].encode())
                self.files.update(read_index(header, self.root / f"{name}.bdt", wanted, profile.wide_hash))
        for subfolder in ("chr", "parts", "mtd", "material", "msg/engus"):
            for file in (self.root / subfolder).glob("*"):
                name = str(PurePosixPath(subfolder, file.name)).lower()
                if file.is_file() and relevant(name):
                    self.files[name] = file
        if not self.files:
            raise ValueError("No game asset archives or loose assets found")

    def read(self, name):
        entry = self.files[name]
        raw = entry.read_bytes() if isinstance(entry, Path) else entry.read()
        return self.oodle.unwrap(raw) if self.oodle else raw
