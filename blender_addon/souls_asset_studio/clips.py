from math import floor

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from .operators import activate_clip, asset_collection, import_gltf, tracks
from .poses import asset_rig


def compatible(source, target):
    if len(source.data.bones) != len(target.data.bones):
        return False
    for bone in source.data.bones:
        match = target.data.bones.get(bone.name)
        if match is None or any(abs(a - b) > 0.001 for first, second in zip(bone.matrix_local, match.matrix_local)
                                for a, b in zip(first, second)):
            return False
    return True


class SAS_OT_import_clips(bpy.types.Operator, ImportHelper):
    bl_idname = "souls_asset_studio.import_clips"
    bl_label = "Import Animations"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.glb;*.gltf", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and asset_rig(asset_collection(context)) is not None

    def execute(self, context):
        asset = asset_collection(context)
        target = asset_rig(asset)
        active = context.view_layer.objects.active
        selected = tuple(context.selected_objects)
        objects = set(bpy.data.objects)
        datablocks = [(group, set(group)) for group in
                      (bpy.data.meshes, bpy.data.armatures, bpy.data.materials, bpy.data.images, bpy.data.actions)]
        added = []
        try:
            if "FINISHED" not in import_gltf(self.filepath):
                return {"CANCELLED"}
            imported = set(bpy.data.objects) - objects
            source = next((obj for obj in imported if obj.type == "ARMATURE"), None)
            if source is None or not source.animation_data or not compatible(source, target):
                self.report({"ERROR"}, "Animation rig does not match the selected asset")
                return {"CANCELLED"}
            names = set(tracks(asset))
            data = target.animation_data_create()
            for track in source.animation_data.nla_tracks:
                if not track.strips:
                    continue
                original = track.strips[0]
                name = track.name
                number = 2
                while name in names:
                    name = f"{track.name} ({number})"
                    number += 1
                entry = data.nla_tracks.new()
                added.append(entry)
                entry.name = name
                entry.mute = True
                strip = entry.strips.new(name, floor(original.frame_start), original.action)
                strip.action_slot = original.action_slot
                names.add(name)
            if not added:
                self.report({"ERROR"}, "No animations found")
                return {"CANCELLED"}
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            for entry in added:
                target.animation_data.nla_tracks.remove(entry)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            for obj in set(bpy.data.objects) - objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            for group, previous in datablocks:
                for item in set(group) - previous:
                    if isinstance(item, bpy.types.Action) and item.use_fake_user and item.users == 1:
                        item.use_fake_user = False
                    if not item.users:
                        group.remove(item)
            for obj in selected:
                obj.select_set(True)
            context.view_layer.objects.active = active
        activate_clip(context.scene, asset, added[0].name)
        return {"FINISHED"}
