from math import ceil
from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix

from .materials import apply_souls_shader, asset_materials, repair_winding
from .rigging import ROOT_LOCK, compact_bones, set_root_lock


def asset_collection(context):
    obj = context.object
    return obj.get("souls_asset_collection") if obj else None


def tracks(collection):
    return sorted({track.name for obj in collection.objects if obj.animation_data
                   for track in obj.animation_data.nla_tracks if track.strips})


def import_gltf(filepath):
    options = {"filepath": filepath, "bone_heuristic": "TEMPERANCE"}
    if "import_scene_as_collection" in bpy.ops.import_scene.gltf.get_rna_type().properties:
        options["import_scene_as_collection"] = False
    return bpy.ops.import_scene.gltf(**options)


def activate_clip(scene, collection, name):
    frame_ranges = []
    for obj in collection.objects:
        data = obj.animation_data
        if data is None:
            continue
        track = data.nla_tracks.get(name)
        strip = track.strips[0] if track and track.strips else None
        if obj.type == "ARMATURE" and data.action and "souls_pose_asset" in data.action:
            for bone in obj.pose.bones:
                bone.matrix_basis = Matrix.Identity(4)
        data.action = strip.action if strip else None
        if strip:
            if hasattr(strip, "action_slot"):
                data.action_slot = strip.action_slot
            frame_ranges.append(tuple(strip.action.frame_range))
        else:
            obj.matrix_basis = Matrix.Identity(4)
    if frame_ranges:
        first = min(r[0] for r in frame_ranges)
        scene.frame_start = max(0, int(first))
        scene.frame_end = max(scene.frame_start + 1, ceil(max(r[1] for r in frame_ranges)))
        scene.frame_set(scene.frame_start)
    collection["souls_clip"] = name
    if collection.get(ROOT_LOCK):
        set_root_lock(scene, collection, True)


class SAS_OT_import_asset(bpy.types.Operator, ImportHelper):
    bl_idname = "souls_asset_studio.import_asset"
    bl_label = "Import Effigy Asset"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.glb;*.gltf", options={"HIDDEN"})

    def execute(self, context):
        previous = set(bpy.data.objects)
        try:
            result = import_gltf(self.filepath)
        except (OSError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if "FINISHED" not in result:
            return {"CANCELLED"}
        imported = set(bpy.data.objects) - previous
        if not imported:
            self.report({"ERROR"}, "No objects in export")
            return {"CANCELLED"}

        collection = bpy.data.collections.new(Path(self.filepath).stem)
        context.scene.collection.children.link(collection)
        for obj in imported:
            original = tuple(obj.users_collection)
            collection.objects.link(obj)
            for source in original:
                source.objects.unlink(obj)
            obj["souls_asset_collection"] = collection
        repair_winding(collection)
        apply_souls_shader(collection)
        rigs = [obj for obj in collection.objects if obj.type == "ARMATURE"]
        for rig in rigs:
            compact_bones(context, rig, collection.objects)
        clips = tracks(collection)
        if clips:
            activate_clip(context.scene, collection, clips[0])
        if rigs:
            rigs[0].select_set(True)
            context.view_layer.objects.active = rigs[0]
        return {"FINISHED"}


class SAS_OT_activate_clip(bpy.types.Operator):
    bl_idname = "souls_asset_studio.activate_clip"
    bl_label = "Activate Clip"
    bl_options = {"REGISTER", "UNDO"}

    clip: StringProperty()

    @classmethod
    def poll(cls, context):
        return asset_collection(context) is not None

    def execute(self, context):
        collection = asset_collection(context)
        if self.clip not in tracks(collection):
            self.report({"ERROR"}, "Clip unavailable")
            return {"CANCELLED"}
        activate_clip(context.scene, collection, self.clip)
        return {"FINISHED"}


class SAS_OT_apply_souls_shader(bpy.types.Operator):
    bl_idname = "souls_asset_studio.apply_souls_shader"
    bl_label = "Apply Souls Shader"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        collection = asset_collection(context)
        return context.mode in {"OBJECT", "POSE"} and collection is not None and bool(asset_materials(collection))

    def execute(self, context):
        collection = asset_collection(context)
        repaired = repair_winding(collection)
        count = apply_souls_shader(collection, legacy=True)
        if repaired or count:
            self.report({"INFO"}, f"Updated {count} materials and {repaired} meshes")
        return {"FINISHED"}


class SAS_OT_compact_bones(bpy.types.Operator):
    bl_idname = "souls_asset_studio.compact_bones"
    bl_label = "Compact Bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (context.mode == "OBJECT" and obj is not None and obj.type == "ARMATURE"
                and (asset_collection(context) is not None or "attachments" in obj))

    def execute(self, context):
        collection = asset_collection(context)
        objects = collection.objects if collection else context.scene.objects
        compact_bones(context, context.object, objects)
        return {"FINISHED"}


class SAS_OT_toggle_root_lock(bpy.types.Operator):
    bl_idname = "souls_asset_studio.toggle_root_lock"
    bl_label = "Root Lock"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "POSE"} and asset_collection(context) is not None

    def execute(self, context):
        collection = asset_collection(context)
        set_root_lock(context.scene, collection, not collection.get(ROOT_LOCK))
        return {"FINISHED"}
