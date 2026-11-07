import bpy
from bpy.props import StringProperty
from mathutils import Matrix

from .operators import asset_collection
from .rigging import ROOT_LOCK, set_root_lock


POSE_ASSET = "souls_pose_asset"


def asset_rig(collection):
    return next((obj for obj in collection.objects if obj.type == "ARMATURE"), None) if collection else None


def saved_poses(collection):
    return sorted((action for action in bpy.data.actions if action.get(POSE_ASSET) == collection),
                  key=lambda action: action.name.casefold())


def clear_pose(scene, collection):
    for obj in collection.objects:
        if obj.animation_data:
            obj.animation_data.action = None
        if obj.type == "ARMATURE":
            for bone in obj.pose.bones:
                bone.matrix_basis = Matrix.Identity(4)
    collection["souls_clip"] = ""
    if collection.get(ROOT_LOCK):
        set_root_lock(scene, collection, True)
    scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)


class AssetRigOperator:
    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "POSE"} and asset_rig(asset_collection(context)) is not None


class SAS_OT_bind_pose(AssetRigOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.bind_pose"
    bl_label = "Bind Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        clear_pose(context.scene, asset_collection(context))
        return {"FINISHED"}


class SAS_OT_save_pose(AssetRigOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.save_pose"
    bl_label = "Save Pose"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="Pose")

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        collection = asset_collection(context)
        rig = asset_rig(collection)
        action = bpy.data.actions.new(self.name.strip() or "Pose")
        action[POSE_ASSET] = collection
        action.use_fake_user = True
        slot = action.slots.new(id_type="OBJECT", name=rig.name)
        layer = action.layers.new("Pose")
        bag = layer.strips.new(type="KEYFRAME").channelbag(slot, ensure=True)
        for bone in rig.pose.bones:
            rotation = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(
                bone.rotation_mode, "rotation_euler")
            for field in ("location", rotation, "scale"):
                path = bone.path_from_id(field)
                for axis, value in enumerate(getattr(bone, field)):
                    bag.fcurves.new(path, index=axis).keyframe_points.insert(1, value)
        return {"FINISHED"}


class SAS_OT_apply_pose(AssetRigOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.apply_pose"
    bl_label = "Apply Pose"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty()

    def execute(self, context):
        collection = asset_collection(context)
        action = bpy.data.actions.get(self.name)
        if action is None or action.get(POSE_ASSET) != collection:
            return {"CANCELLED"}
        clear_pose(context.scene, collection)
        data = asset_rig(collection).animation_data_create()
        data.action = action
        data.action_slot = action.slots[0]
        context.scene.frame_set(context.scene.frame_current)
        return {"FINISHED"}


class SAS_OT_delete_pose(AssetRigOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.delete_pose"
    bl_label = "Delete Pose"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        collection = asset_collection(context)
        action = bpy.data.actions.get(self.name)
        if action is None or action.get(POSE_ASSET) != collection:
            return {"CANCELLED"}
        rig = asset_rig(collection)
        if rig.animation_data and rig.animation_data.action == action:
            clear_pose(context.scene, collection)
        bpy.data.actions.remove(action)
        return {"FINISHED"}
