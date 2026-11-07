import bpy

from .operators import asset_collection, tracks
from .ds3_surface import GROUP_VERSION
from .poses import asset_rig, saved_poses
from .rigging import ROOT_LOCK
from .staging import PRESETS, STUDIO


def import_menu(self, _):
    self.layout.operator("souls_asset_studio.import_asset", text="Effigy Asset (.glb/.gltf)")


class SAS_PT_assets(bpy.types.Panel):
    bl_label = "Effigy Exporter"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Effigy"

    def draw(self, context):
        self.layout.operator("souls_asset_studio.import_asset", text="Import Asset")
        if bpy.ops.souls_asset_studio.compact_bones.poll():
            self.layout.operator("souls_asset_studio.compact_bones")
        collection = asset_collection(context)
        if collection:
            if bpy.ops.souls_asset_studio.import_clips.poll():
                self.layout.operator("souls_asset_studio.import_clips", text="Import Animations…")
            clips = tracks(collection)
            if clips:
                locked = bool(collection.get(ROOT_LOCK))
                row = self.layout.row(align=True)
                row.operator("screen.animation_play", text="", icon="PAUSE" if
                             context.screen and context.screen.is_animation_playing else "PLAY")
                row.operator("souls_asset_studio.toggle_root_lock",
                             icon="LOCKED" if locked else "UNLOCKED", depress=locked)
                self.layout.prop(context.window_manager, "souls_clip_filter", text="", icon="VIEWZOOM")
            search = context.window_manager.souls_clip_filter.casefold().strip()
            for name in clips:
                if search not in name.casefold():
                    continue
                active = name == collection.get("souls_clip")
                button = self.layout.operator("souls_asset_studio.activate_clip", text=name, depress=active)
                button.clip = name


class SAS_PT_poses(bpy.types.Panel):
    bl_label = "Poses"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Effigy"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return asset_rig(asset_collection(context)) is not None

    def draw(self, context):
        row = self.layout.row(align=True)
        row.operator("souls_asset_studio.bind_pose")
        row.operator("souls_asset_studio.save_pose")
        for action in saved_poses(asset_collection(context)):
            row = self.layout.row(align=True)
            row.operator("souls_asset_studio.apply_pose", text=action.name).name = action.name
            row.operator("souls_asset_studio.delete_pose", text="", icon="X").name = action.name


class SAS_PT_materials(bpy.types.Panel):
    bl_label = "Materials"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Effigy"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return bpy.ops.souls_asset_studio.apply_souls_shader.poll()

    def draw(self, context):
        self.layout.operator("souls_asset_studio.apply_souls_shader")
        if context.object.type != "MESH" or context.object.active_material is None:
            return
        material = context.object.active_material
        self.layout.label(text=material.name)
        if not material.node_tree:
            return
        for node in material.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                for name in ("Base Color", "Roughness", "Metallic", "Specular IOR Level", "Emission Strength",
                             "Alpha", "Anisotropic", "Subsurface Weight", "Sheen Weight"):
                    socket = node.inputs.get(name)
                    if socket and not socket.is_linked:
                        self.layout.prop(socket, "default_value", text=name)
            elif node.type == "GROUP" and node.node_tree and node.node_tree.get(GROUP_VERSION):
                for name in ("Roughness", "Emission Strength", "Alpha", "Subsurface Weight"):
                    socket = node.inputs[name]
                    if not socket.is_linked:
                        self.layout.prop(socket, "default_value", text=name)
            elif node.type == "NORMAL_MAP":
                self.layout.prop(node.inputs["Strength"], "default_value", text="Normal Strength")


class SAS_PT_studio(bpy.types.Panel):
    bl_label = "Studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Effigy"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return bpy.ops.souls_asset_studio.studio_lighting.poll()

    def draw(self, context):
        row = self.layout.row(align=True)
        row.operator("souls_asset_studio.use_preview_hdri")
        if bpy.ops.souls_asset_studio.restore_world.poll():
            row.operator("souls_asset_studio.restore_world")
        row = self.layout.row(align=True)
        for key, name, _ in PRESETS:
            row.operator("souls_asset_studio.studio_lighting", text=name).preset = key
        row = self.layout.row(align=True)
        row.operator("souls_asset_studio.frame_camera")
        row.operator("souls_asset_studio.turntable", text="Turntable")
        if bpy.ops.souls_asset_studio.render_turntable.poll():
            self.layout.operator("souls_asset_studio.render_turntable", text="Render Turntable…")
        asset = asset_collection(context)
        if asset.get(STUDIO):
            self.layout.operator("souls_asset_studio.remove_studio")
