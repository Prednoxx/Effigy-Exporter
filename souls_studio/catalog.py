from dataclasses import dataclass
from functools import partial
import json
from pathlib import Path
import re

from .archive import DS3, NIGHTREIGN, GameFiles


GAMES = {"Dark Souls III": "ds3", "Elden Ring Nightreign": "nightreign",
         "Dark Souls": "ds1", "Dark Souls II / Scholar": "ds2", "Elden Ring": "er"}

# Model identifiers cross-checked against the DS3 Character Model IDs reference.
BOSSES = {
    "c1320": "Crystal Sage", "c2090": "Oceiros", "c2240": "Vordt of the Boreal Valley",
    "c3040": "Abyss Watchers", "c3050": "Old Demon King", "c3141": "Ancient Wyvern",
    "c3160": "Dragonslayer Armour", "c5010": "Nameless King", "c5020": "Demon Prince",
    "c5030": "King of the Storm", "c5110": "Gundyr", "c5140": "Pontiff Sulyvahn",
    "c5150": "Aldrich", "c5160": "High Lord Wolnir", "c5180": "Curse-Rotted Greatwood",
    "c5220": "Archdeacon of the Deep", "c5250": "Twin Princes", "c5260": "Yhorm the Giant",
    "c5270": "Dancer of the Boreal Valley", "c5280": "Soul of Cinder",
    "c6010": "Father Ariandel", "c6020": "Sister Friede", "c6030": "Gravetender Greatwolf",
    "c6200": "Slave Knight Gael · Phase 1", "c6201": "Slave Knight Gael · Phase 2",
    "c6211": "Darkeater Midir",
}


WEAPON_NAMES = {"wp_a_0201": "Longsword", "wp_a_2104": "Knight Shield"}


def steam_roots():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return
    yield steam
    library_file = steam / "steamapps/libraryfolders.vdf"
    if library_file.is_file():
        for value in re.findall(r'"path"\s+"([^"]+)"', library_file.read_text(encoding="utf-8")):
            root = Path(value.replace("\\\\", "\\"))
            if root != steam:
                yield root


def detect_steam(app_id, executable):
    for steam in steam_roots():
        steamapps = steam / "steamapps"
        manifest = steamapps / f"appmanifest_{app_id}.acf"
        if not manifest.is_file():
            continue
        match = re.search(r'"installdir"\s+"([^"]+)"', manifest.read_text(encoding="utf-8"))
        if match:
            root = steamapps / "common" / match[1] / "Game"
            if (root / executable).is_file():
                return root
    return None


def detect_ds3():
    return detect_steam(374320, "DarkSoulsIII.exe")


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    category: str
    source: str
    aliases: tuple = ()


class SoulsCatalog:
    profile = DS3
    bosses = BOSSES
    characters = {}
    weapons = WEAPON_NAMES
    executable = "DarkSoulsIII.exe"
    app_id = 374320

    @classmethod
    def detect(cls):
        return detect_steam(cls.app_id, cls.executable)

    def __init__(self, root, reference, progress):
        root = Path(root).resolve()
        if (root / "Game").is_dir():
            root /= "Game"
        self.files = GameFiles(root, reference, self.profile, progress)
        self.warnings = []
        self.display_masks, weapon_labels = self.metadata()
        assets = {}
        for path in sorted(self.files.files):
            id = Path(path).name.split(".", 1)[0]
            if re.fullmatch(r"chr/c\d{4}\.chrbnd(?:\.dcx)?", path):
                category = "Bosses" if id in self.bosses else "Characters"
                if id != "c0000":
                    name = self.bosses.get(id) or self.characters.get(id, id)
                    assets[id] = Asset(id, name, category, path)
            elif re.fullmatch(r"parts/wp_[a-z]_\d+\.partsbnd(?:\.dcx)?", path):
                labels = weapon_labels.get(id, (self.weapons.get(id, id.upper()),))
                assets[id] = Asset(id, labels[0], "Weapons", path, labels[1:])
        self.assets = tuple(sorted(assets.values(), key=lambda asset: (asset.name.casefold(), asset.id)))

    def metadata(self):
        return {}, {}

    def load(self, asset, progress):
        from .model import load_model
        return load_model(self, asset, progress)

    def animations(self, asset, progress):
        from .animation import list_clips
        return list_clips(self, asset, progress)

    def decode(self, clip, model, decoder, progress):
        from .animation import load_animation
        return load_animation(self, clip, model, decoder, progress)

    def related(self, asset, kind):
        folder = asset.source.split("/")[0]
        pattern = rf"{folder}/{asset.id}(?:_\w+)?\.{kind}(?:\.dcx)?"
        return sorted(path for path in self.files.files if re.fullmatch(pattern, path))


class Ds3Catalog(SoulsCatalog):
    _names = json.loads(Path(__file__).with_name("ds3_names.json").read_text(encoding="utf-8"))
    characters = _names["characters"]
    weapons = WEAPON_NAMES | _names["weapons"]

    def metadata(self):
        from .metadata import ds3_metadata
        try:
            return ds3_metadata(self.files)
        except (OSError, ValueError) as error:
            self.warnings.append(f"Game metadata: {error}")
            return {}, {}


class NightreignCatalog(SoulsCatalog):
    profile = NIGHTREIGN
    characters = json.loads(Path(__file__).with_name("nightreign_names.json").read_text(encoding="utf-8"))
    bosses = {
        "c7500": "Gladius", "c7510": "Adel", "c7511": "Adel · Lightning Fang",
        "c7520": "Gnoster · Moth", "c7521": "Gnoster · Moth", "c7530": "Gnoster · Pest",
        "c7540": "Maris", "c7560": "Libra", "c7561": "Libra", "c7570": "Libra · Shrouded",
        "c7580": "Heolstor", "c7600": "Fulghor", "c7700": "Gaping Dragon",
        "c7710": "Centipede Demon", "c7800": "Duke's Dear Freja", "c7820": "Smelter Demon",
        "c7900": "Nameless King", "c7910": "Nameless King · Mount", "c7920": "Dancer of the Boreal Valley",
    }
    weapons = {}
    executable = "nightreign.exe"
    app_id = 2622380

    def __init__(self, root, reference, progress):
        super().__init__(root, reference, progress)
        from .oodle import Oodle9
        self.model_decoder = reference.parent / "decoder/SekiroMotionDecoder.exe"
        dll = self.files.root / "oo2core_9_win64.dll"
        if dll.is_file():
            self.files.oodle = Oodle9(dll)

    def load(self, asset, progress):
        from .model import load_model
        from .nightreign_model import read_nightreign_flver
        read_flver = partial(read_nightreign_flver, decoder=self.model_decoder)
        return load_model(self, asset, progress, read_flver=read_flver)


ADAPTERS = {"ds3": Ds3Catalog, "nightreign": NightreignCatalog}
