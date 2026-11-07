import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import sys
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "blender_addon/souls_asset_studio"
sys.path.insert(0, str(ROOT))

from souls_studio import __version__


def addon_filename():
    version = tomllib.loads((ADDON / "blender_manifest.toml").read_text(encoding="utf-8"))["version"]
    return f"EffigyExporter-Blender-{version}.zip"


def copy_licenses(stage):
    destination = stage / "licenses"
    shutil.copytree(ROOT / "licenses", destination, dirs_exist_ok=True)
    shutil.copytree(ROOT / "build/runtime/licenses", destination, dirs_exist_ok=True)
    distributions = ("numpy", "scipy", "Pillow", "soulstruct", "PyOpenGL", "pyopengltk",
                     "cryptography", "cffi", "pyinstaller")
    for name in distributions:
        dist = importlib.metadata.distribution(name)
        for item in dist.files or ():
            if not item.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                continue
            source = Path(dist.locate_file(item))
            if source.is_file():
                target = destination / name / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    prefix = Path(sys.base_prefix)
    for name, source in (
        ("Python.txt", prefix / "LICENSE.txt"),
        ("Tcl.txt", prefix / "tcl/tcl8.6/license.terms"),
        ("Tk.txt", prefix / "tcl/tk8.6/license.terms"),
    ):
        if source.is_file():
            shutil.copyfile(source, destination / name)


def zip_files(target, source, prefix=Path()):
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=5) as archive:
        for file in sorted(source.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                archive.write(file, prefix / file.relative_to(source))
    with ZipFile(target) as archive:
        if archive.testzip():
            raise RuntimeError(f"Archive integrity check failed: {target.name}")


def package(stage, releases):
    if not (stage / "EffigyExporter.exe").is_file() or not (stage / "_internal").is_dir():
        raise FileNotFoundError("Windows build missing")
    releases.mkdir(parents=True, exist_ok=True)
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, stage)
    copy_licenses(stage)
    addon_zip = releases / addon_filename()
    zip_files(addon_zip, ADDON)
    shutil.copy2(addon_zip, stage)
    portable = releases / f"EffigyExporter-{__version__}-Windows-x64.zip"
    zip_files(portable, stage, Path("EffigyExporter"))
    return addon_zip


def checksums(releases):
    assets = sorted((*releases.glob(f"EffigyExporter-{__version__}-*"), releases / addon_filename()))
    rows = []
    for asset in assets:
        with asset.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        rows.append(f"{digest}  {asset.name}")
    (releases / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, default=ROOT / "build/dist/EffigyExporter")
    parser.add_argument("--releases", type=Path, default=ROOT / "Releases")
    parser.add_argument("--checksums", action="store_true")
    args = parser.parse_args()
    if args.checksums:
        checksums(args.releases)
    else:
        print(package(args.stage, args.releases))


if __name__ == "__main__":
    main()
