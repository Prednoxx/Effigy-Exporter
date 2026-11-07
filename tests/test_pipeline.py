import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PIL import Image

from souls_studio.paths import RUNTIME

sys.path.insert(0, str(RUNTIME / "bridge/standalone"))

from souls_studio.animation import map_animation, matching_compendium
from souls_studio.archive import path_hash, read_index
from souls_studio.gltf import write_glb
from souls_studio.model import Bone, Mesh, Model
from souls_studio.surface import png
from souls_studio.tae import event_label, tae_event_types


class ExportTests(unittest.TestCase):
    def test_ds3_exports_authored_diffuse_and_reflectance_separately(self):
        sources = {
            "albedo": png(Image.new("RGB", (2, 2), (19, 22, 25))),
            "reflectance": png(Image.new("RGB", (2, 2), (62, 75, 87))),
            "roughness": png(Image.new("L", (2, 2), 96)),
        }
        bindings = [{"role": role, "key": (role, role), "image": payload, "uv": 0, "scale": [1, 1]}
                    for role, payload in sources.items()]
        mesh = Mesh("triangle", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 1)] * 3,
                    [0, 1, 2], [[(0, 0)], [(1, 0)], [(0, 1)]], [], 0, "")
        material = {"name": "cape", "alpha": False, "textures": bindings,
                    "surface": "Cloth", "workflow": "specular"}
        model = Model("triangle", [], {0: [mesh]}, [material], [], [])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "triangle.gltf"
            write_glb(model, path)
            doc = json.loads(path.read_text(encoding="utf-8"))
            material = doc["materials"][0]
            pbr = material["pbrMetallicRoughness"]
            reflection = material["extensions"]["KHR_materials_specular"]["specularColorTexture"]
            self.assertEqual(pbr["metallicFactor"], 0)
            for role, texture in (("albedo", pbr["baseColorTexture"]), ("reflectance", reflection)):
                image = doc["images"][doc["textures"][texture["index"]]["source"]]
                self.assertEqual((path.parent / image["uri"]).read_bytes(), sources[role])

    def test_export_preserves_winding_after_flver_basis_conversion(self):
        mesh = Mesh("triangle", [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                    [(0, 0, 1)] * 3, [0, 1, 2], [], [], 0, "")
        model = Model("triangle", [], {0: [mesh]}, [{"name": "surface", "alpha": False, "textures": []}], [], [])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "triangle.glb"
            write_glb(model, path)
            glb = path.read_bytes()
        length = struct.unpack_from("<I", glb, 12)[0]
        manifest = json.loads(glb[20:20 + length])
        primitive = manifest["meshes"][0]["primitives"][0]
        accessor = manifest["accessors"][primitive["indices"]]
        view = manifest["bufferViews"][accessor["bufferView"]]
        self.assertEqual(struct.unpack_from("<3I", glb, 28 + length + view["byteOffset"]), (0, 1, 2))


class ArchiveTests(unittest.TestCase):
    def test_zero_unpadded_size_uses_padded_size(self):
        header = bytearray(80)
        header[:5] = b"BHD5\xff"
        struct.pack_into("<II", header, 16, 1, 32)
        struct.pack_into("<II", header, 32, 1, 40)
        path = "chr/c5110.chrbnd.dcx"
        digest = path_hash(path)
        struct.pack_into("<IIQqqq", header, 40, digest, 32, 4096, 0, 0, 0)
        entries = dict(read_index(header, Path("Data3.bdt"), {digest: path}))
        self.assertEqual(entries[path].offset, 4096)
        self.assertEqual(entries[path].size, 32)
        self.assertEqual(digest, path_hash(r"\CHR\C5110.CHRBND.DCX"))


    def test_wide_hash_and_bucket_table(self):
        header = bytearray(112)
        header[:5] = b"BHD5\xff"
        struct.pack_into("<QQ", header, 16, 1, 48)
        struct.pack_into("<IIQ", header, 48, 1, 1, 72)
        path = "chr/c7500.chrbnd.dcx"
        digest = path_hash(path, wide=True)
        struct.pack_into("<QIIQqq", header, 72, digest, 128, 112, 2048, 0, 0)
        entries = dict(read_index(header, Path("Data1.bdt"), {digest: path}, wide_hash=True))
        self.assertEqual((entries[path].offset, entries[path].size), (2048, 112))


class CompendiumTests(unittest.TestCase):
    def test_selects_matching_type_id(self):
        def chunk(magic, payload):
            return struct.pack(">I", len(payload) + 8) + magic + payload

        type_id = b"abcdefgh"
        animation = chunk(b"TAG0", chunk(b"TCRF", type_id))
        wrong = chunk(b"TCM0", chunk(b"TCID", b"notright"))
        right = chunk(b"TCM0", chunk(b"TCID", type_id))
        self.assertEqual(matching_compendium(animation, ({"wrong.compendium": wrong},
                                                         {"right.compendium": right})), right)
        with self.assertRaisesRegex(ValueError, "Missing Havok compendium"):
            matching_compendium(animation, ({"wrong.compendium": wrong},))


class TimeActTests(unittest.TestCase):
    def test_labels_only_recognized_gameplay_events(self):
        data = bytearray(256)
        data[:12] = b"TAE \0\0\0\xff\x0c\0\x01\0"
        struct.pack_into("<IQ", data, 0x54, 1, 0x60)
        struct.pack_into("<QQ", data, 0x60, 3000, 0x70)
        struct.pack_into("<Q", data, 0x70, 0xA0)
        struct.pack_into("<I", data, 0x90, 2)
        struct.pack_into("<Q", data, 0xB0, 0xE0)
        struct.pack_into("<Q", data, 0xC8, 0xF0)
        struct.pack_into("<I", data, 0xE0, 1)
        struct.pack_into("<I", data, 0xF0, 2)
        self.assertEqual(tae_event_types(data), {3000: {1, 2}})
        data[8] = 0x0D
        self.assertEqual(event_label(tae_event_types(data)[3000]), "Projectile")
        self.assertEqual(event_label({128}), "")
        with self.assertRaisesRegex(ValueError, "Invalid TAE event data"):
            tae_event_types(data[:0xF0])


class TransformTests(unittest.TestCase):
    def test_animation_preserves_motion_from_omitted_hkx_parent(self):
        identity = tuple(np.eye(4)[:3].ravel())
        inverse = np.eye(4)
        inverse[0, 3] = -2
        model = Model("asset", [
            Bone("master", -1, (0, 0, 0), (0, 0, 0, 1), (1, 1, 1), identity),
            Bone("deform", 0, (2, 0, 0), (0, 0, 0, 1), (1, 1, 1), tuple(inverse[:3].ravel())),
        ], [[Mesh("mesh", [(2, 0, 0)], [], [], [], [[(1, 1.0)]], 0, "")]], [], [], [])

        def trs(x, z=0):
            return {"translation": [x, 0, z], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}

        motion = {
            "frameCount": 2, "frameRate": 30,
            "skeleton": {"bones": [
                dict(trs(0), name="master", parent=-1),
                dict(trs(1), name="control", parent=0),
                dict(trs(1), name="deform", parent=1),
            ]},
            "trackBoneIndices": [1],
            "frames": [[trs(1)], [trs(1, 3)]],
            "rootMotion": [[0, 0, 0, 0], [0, 0, 2, 0]],
        }
        mapped = map_animation(motion, model, "test")
        np.testing.assert_allclose(mapped["positions"][:, 1], [[2, 0, 0], [2, 0, -3]])
        np.testing.assert_allclose(mapped["root"], [[0, 0, 0], [0, 0, -2]])
        self.assertEqual(mapped["animated"], (0, 1))


if __name__ == "__main__":
    unittest.main()
