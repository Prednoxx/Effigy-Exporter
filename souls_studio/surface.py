"""Translate FLVER character material maps to portable PBR inputs."""
from io import BytesIO
import re

import numpy as np
from PIL import Image


def surface_kind(name, definition):
    words = set(re.findall(r"[a-z]+", f"{name} {definition}".lower()))
    if words & {"hair", "fur"}:
        return "Hair"
    if words & {"skin", "face", "sss"}:
        return "Skin"
    if words & {"cloth", "cape", "cloak", "manteau", "fabric"}:
        return "Cloth"
    return "Surface"


def alpha_cutoff(params):
    values = params.get("g_AlphaRef") or ()
    if isinstance(values, (float, int)):
        values = (values,)
    first = next((value for value in values if value > 0), None)
    if first is None:
        return 0.5
    return min(1.0, first / 255 if isinstance(first, int) or first > 1 else first)


def png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def decode_texture(raw, role, opaque, workflow):
    fourcc = raw[84:88]
    dxgi = int.from_bytes(raw[128:132], "little") if fourcc == b"DX10" else None
    if dxgi in (72, 75, 78):
        raw = raw[:128] + (dxgi - 1).to_bytes(4, "little") + raw[132:]
    with Image.open(BytesIO(raw)) as source:
        if role != "normal":
            return png(source.convert("RGB" if opaque or role in {"metallic", "reflectance"} else "RGBA")), None

        channels = np.array(source.convert("RGB"))
        roughness = None
        if fourcc not in {b"ATI1", b"ATI2", b"BC4U", b"BC4S", b"BC5U", b"BC5S"} and dxgi not in range(79, 85):
            gloss = channels[..., 2].astype(np.float32) / 255
            if workflow == "specular":
                # Match the width of the DS3 specular lobe with perceptual GGX roughness.
                rough = (2 / (2 + np.exp2(13 * gloss))) ** 0.25
            else:
                rough = 1 - gloss ** 2.2
            roughness = png(Image.fromarray(np.rint(np.clip(rough, 0.04, 1) * 255).astype(np.uint8)))

        channels[..., 1] = 255 - channels[..., 1]
        x = channels[..., 0].astype(np.float32) / 127.5 - 1
        y = channels[..., 1].astype(np.float32) / 127.5 - 1
        z = np.sqrt(np.maximum(0, 1 - x * x - y * y))
        channels[..., 2] = np.rint((z + 1) * 127.5).astype(np.uint8)
        return png(Image.fromarray(channels)), roughness


def texture_image(binding, mode):
    with Image.open(BytesIO(binding["image"])) as source:
        return source.convert(mode)


def texture_space(binding):
    return binding["uv"], tuple(binding["scale"])


def generated(binding, role, payload, *keys):
    stem = binding["key"][0]
    return dict(binding, key=(stem, role, *keys), role=role, image=payload)


def material_textures(spec, cache):
    textures = {binding["role"]: binding for binding in spec["textures"]}
    albedo, reflectance = textures.get("albedo"), textures.get("reflectance")
    metallic, roughness = textures.get("metallic"), textures.get("roughness")
    key = tuple((role, binding["key"], texture_space(binding)) for role, binding in sorted(textures.items()))
    if key in cache:
        return cache[key]
    packed = None
    primary = metallic or roughness
    if primary:
        metal = texture_image(metallic, "L") if metallic else None
        rough = texture_image(roughness, "L") if roughness else None
        size = max((image.size for image in (metal, rough) if image), key=lambda shape: shape[0] * shape[1])
        if metal and rough and texture_space(metallic) != texture_space(roughness):
            rough = Image.new("L", (1, 1), rough.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0)))
            size = metal.size
        green = rough.resize(size, Image.Resampling.BILINEAR) if rough else Image.new("L", size, 166)
        blue = metal.resize(size, Image.Resampling.BILINEAR) if metal else Image.new("L", size)
        payload = png(Image.merge("RGB", (Image.new("L", size, 255), green, blue)))
        packed = generated(primary, "metallic_roughness", payload,
                           metallic["key"] if metallic else (), roughness["key"] if roughness else ())

    result = (albedo, textures.get("normal"), textures.get("emissive"), packed, reflectance)
    cache[key] = result
    return result
