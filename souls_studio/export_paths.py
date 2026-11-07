from hashlib import sha256
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile


def safe_name(value, fallback="Asset"):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:120].rstrip(" .")
    if not name:
        return fallback
    device = name.split(".", 1)[0].upper()
    if device in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(COM|LPT)[1-9¹²³]", device):
        return "_" + name
    return name


def atomic_write(path, *parts):
    with NamedTemporaryFile(dir=path.parent, prefix=".export-", delete=False) as output:
        temp = Path(output.name)
        try:
            for part in parts:
                output.write(part)
            output.close()
            os.replace(temp, path)
        finally:
            output.close()
            temp.unlink(missing_ok=True)


def sidecar(path, name, suffix, data):
    folder = path.with_name(safe_name(path.stem) + "_files")
    folder.mkdir(exist_ok=True)
    if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)():
        raise ValueError(f"Export folder redirects to another location: {folder.name}")
    digest = sha256(data).hexdigest()[:16]
    target = folder / f"{safe_name(name)}-{digest}{suffix}"
    if not target.is_file():
        atomic_write(target, data)
    return target.relative_to(path.parent).as_posix()
