# Effigy Exporter

Browse, preview, and export models and animations from Dark Souls III and Elden Ring Nightreign.

## Features

- Search bosses, characters, and weapons by name or model ID.
- Preview textured models, materials, and skeletal animations with LOD selection and root lock.
- Export GLB, glTF, or CAST with rigs, selected animations, and PNG or DDS textures.
- Batch models with export presets, or export selected animations on their own.
- Import into Blender with compact bones, editable DS3 materials, saved poses, lighting, and turntables.

## Install

Windows 10 or 11, 64-bit, with OpenGL and an installed copy of a supported game.

Run the Windows installer from [Releases](https://github.com/Prednoxx/Effigy-Exporter/releases/latest). For the portable build, extract the ZIP and open **EffigyExporter.exe** with its **_internal** folder beside it.

Effigy detects Steam installations at startup. Use **Game Folder…** for a manual location.

## Blender

Install the extension ZIP in Blender 4.5 or later via **Preferences → Get Extensions → Install from Disk**. Use **File → Import → Effigy Asset (.glb/.gltf)**. The **Effigy** sidebar contains animation, materials, and studio tools.

**Materials → Apply Souls Shader** repairs reversed face winding and updates legacy Souls imports. Re-export to pick up the new game texture channels. **Studio → Use Preview HDRI** lights the render with the viewport HDRI while preserving the camera background.

Fresh DS3 exports keep authored diffuse and RGB reflectance separate. The Blender add-on combines them in the **Dark Souls III Surface** node group with texture-driven gloss and alpha. Re-export older DS3 models to load both source maps.

Use the separate [CAST importer](https://github.com/dtzxporter/cast) for CAST files.

## Export

**Export Options** controls format, texture copies, LODs, and animation inclusion. GLB embeds PNG textures. glTF and CAST use PNG sidecars. Exported DDS copies preserve the original game texture data. Keep each external export's `_files` folder beside it.

Model and clip names come from the browser. **Export Animation** writes the selected clips with their rig. **Library → Export Selected** or **Export List** batches models with their default mesh groups.

| Shortcut | Action |
| --- | --- |
| Ctrl+F | Search |
| Ctrl+E | Export model |
| Ctrl+Shift+E | Export animation |
| Ctrl+A | Select all rows in the active list |
| F5 | Rescan |
| Space | Play or pause |
| [ / ] | Previous or next frame |
| R | Reset view |
| Ctrl + / Ctrl − / Ctrl 0 | Text size |

## Coverage

- DS3 and Nightreign support Steam detection, BHD5/BDT extraction, available FLVER LODs, HKX playback, and GLB, glTF, and CAST export. Search accepts names and model IDs.
- DS3 and Nightreign show Attack, Projectile, or Throw Attack beside a clip ID when the game's TimeAct event table supports that label. Other clips retain their IDs.
- Material export covers base color, normals, gloss-derived roughness, DS3 reflectance, Nightreign metalness, cutouts, and emission. GLB and glTF approximate the game materials with portable PBR. The viewport displays base color. Phase changes and cloth simulation are outside this build.
- Animation coverage varies by clip. The app reports unsupported additive clips and transforms that cannot be represented reliably in GLB.
- Nightreign reads the installed base-game archives, using the game's Oodle 9 DLL and SoulsFormats for its FLVER models. Nightreign weapon labels and DLC coverage are pending.
- Dark Souls, Dark Souls II, and Elden Ring are reserved for later adapters.

## Build

Use 64-bit Python 3.13, Git, and the .NET 10 SDK. Inno Setup 6 builds the installer.

    .\tools\build_windows.ps1

Release files go to **Releases**. Settings and logs live in `%LOCALAPPDATA%\EffigyExporter`.

## References

The Tk/OpenGL viewport and export writers are adapted from Apex Asset Studio, copyright © 2026 Prednoxx, under AGPL-3.0-or-later. The app follows Traxus's GLB-to-Blender workflow. The Blender extension uses GPL-3.0-or-later.

- [UXM Selective Unpack](https://github.com/Nordgaren/UXM-Selective-Unpack) supplies archive path dictionaries and public keys from an external checkout.
- [SoulsFormatsNEXT](https://github.com/soulsmods/SoulsFormatsNEXT/blob/e25d1a5c3cda83b801fdefe00f4d2903892cc526/SoulsFormats/Formats/BHD5.cs) documents the BHD5 layout and [regulation decryption](https://github.com/soulsmods/SoulsFormatsNEXT/blob/e25d1a5c3cda83b801fdefe00f4d2903892cc526/SoulsFormats/Utilities/Cryptography/RegulationDecryptor.cs).
- [Sekiro Animation Bridge](https://github.com/Beertraps/SekiroAnimationBridge) supplies the HKX decoder and FLVER helpers. [Soulstruct](https://github.com/Grimrukh/soulstruct) parses binders, FLVER, MTD, MATBIN, TPF, and FMG.
- [SoulsAssetPipeline's SoulsFormats](https://github.com/Meowmaritus/SoulsAssetPipeline/tree/d11caf989c917c7a43e2c7559915b1c5af218153/SoulsFormats/Formats/FLVER) reads Nightreign FLVERs. [Smithbox's Nightreign character list](https://github.com/vawser/Smithbox/blob/main/Documentation/Game%20Information/NR/chr_names.txt) supplies character labels under the [MIT license](licenses/Smithbox-MIT.txt).
- [DS Anim Studio](https://github.com/Meowmaritus/DSAnimStudio) documents DS3 NPC and weapon parameter fields. [DS3 Character Model IDs](https://soulsmodding.wikidot.com/reference:ds3-character-model-ids) and [Smithbox](https://github.com/vawser/Smithbox) supply boss model names.
- The DS3 name table adapts the Souls Modding Wiki contributors’ [character list](https://www.soulsmodding.com/doku.php?id=ds3-refmat:character-list) and [parts list](https://www.soulsmodding.com/doku.php?id=ds3-refmat:part-list) under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The table retains installed model IDs, normalizes labels, and adds entries checked against installed FLVERs and [Paramdex equipment labels](https://github.com/soulsmods/Paramdex/blob/master/DS3/Names/EquipParamWeapon.txt). English game text takes precedence for weapons.
- [Soulstruct for Blender](https://github.com/Grimrukh/soulstruct-blender) and [Elden Ring Character Exporter](https://github.com/gvm1229/EldenRing-Exporter) provide reference workflows for Blender actions and rig binding.
- [DS3 renderer analysis](https://www.fig14.com/ds3/assets.html) and [Soulstruct’s Elden Ring material builder](https://github.com/Grimrukh/soulstruct-blender/blob/main/io_soulstruct/soulstruct/blender/flver/material/shaders/eldenring/node_tree_builder.py) document the source material channels.
- [FLVER Editor 2](https://github.com/asasasasasbc/FLVER_Editor) and [WitchyBND](https://github.com/ividyon/WitchyBND) provide format references for later games. ERAnimate's repository was unavailable during inspection.
