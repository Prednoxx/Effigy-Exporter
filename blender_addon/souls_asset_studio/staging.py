from math import radians, tan, tau

import bpy
from bpy.props import EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector

from .operators import asset_collection


STUDIO = "souls_studio_collection"
PREVIOUS_CAMERA = "souls_previous_camera"
TURNTABLE_RANGE = "souls_turntable_range"
PRESETS = (
    ("STUDIO", "Studio", ""),
    ("SOFT", "Soft", ""),
    ("RIM", "Rim", ""),
)
LIGHTS = {
    "STUDIO": (650, 280, 480, 1.1),
    "SOFT": (450, 350, 230, 1.8),
    "RIM": (270, 110, 950, 0.9),
}


def bounds(asset):
    points = [obj.matrix_world @ Vector(corner) for obj in asset.objects if obj.type == "MESH"
              for corner in obj.bound_box]
    if not points:
        return None
    axes = tuple(zip(*points))
    low = Vector(tuple(min(axis) for axis in axes))
    high = Vector(tuple(max(axis) for axis in axes))
    return (low + high) / 2, max((high - low).length, 0.05)


def studio_collection(scene, asset):
    studio = asset.get(STUDIO)
    if studio is None:
        studio = bpy.data.collections.new(f"{asset.name} Studio")
        scene.collection.children.link(studio)
        asset[STUDIO] = studio
    return studio


def remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and not data.users:
        if isinstance(data, bpy.types.Camera):
            bpy.data.cameras.remove(data)
        elif isinstance(data, bpy.types.Light):
            bpy.data.lights.remove(data)


def look_at(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def frame_camera(scene, asset, center, span):
    studio = studio_collection(scene, asset)
    camera = next((obj for obj in studio.objects if obj.get("souls_camera")), None)
    if camera is None:
        camera = bpy.data.objects.new("Studio Camera", bpy.data.cameras.new("Studio Camera"))
        camera["souls_camera"] = True
        studio.objects.link(camera)
        if scene.camera:
            studio[PREVIOUS_CAMERA] = scene.camera
    camera.data.lens = 50
    camera.data.clip_start = max(0.001, span * 0.002)
    camera.data.clip_end = max(100, span * 20)
    field = min(camera.data.angle_x, camera.data.angle_y)
    distance = span * 0.6 / tan(field / 2)
    if camera.parent:
        camera.parent = None
    camera.location = center + Vector((0.65, -1, 0.32)).normalized() * distance
    look_at(camera, center)
    scene.camera = camera
    return camera


def restore_range(scene, studio):
    span = studio.get(TURNTABLE_RANGE)
    if span is not None:
        if scene.frame_end == span[1]:
            scene.frame_end = span[0]
        del studio[TURNTABLE_RANGE]


class StudioOperator:
    @classmethod
    def poll(cls, context):
        asset = asset_collection(context)
        return asset is not None and any(obj.type == "MESH" for obj in asset.objects)


class SAS_OT_studio_lighting(StudioOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.studio_lighting"
    bl_label = "Apply Lighting"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(name="Preset", items=PRESETS)

    def execute(self, context):
        asset = asset_collection(context)
        center, span = bounds(asset)
        studio = studio_collection(context.scene, asset)
        for obj in tuple(studio.objects):
            if obj.get("souls_light"):
                remove_object(obj)
        key, fill, rim, softness = LIGHTS[self.preset]
        for name, direction, energy, color in (
                ("Key", (-0.6, -0.7, 1), key, (1, 0.93, 0.85)),
                ("Fill", (0.8, -0.35, 0.4), fill, (0.75, 0.85, 1)),
                ("Rim", (0.25, 0.8, 0.85), rim, (0.87, 0.92, 1))):
            light = bpy.data.lights.new(name, "AREA")
            light.energy = energy * (span / 3) ** 2
            light.size = span * softness * 0.45
            light.color = color
            obj = bpy.data.objects.new(name, light)
            obj["souls_light"] = True
            studio.objects.link(obj)
            obj.location = center + Vector(direction).normalized() * span
            look_at(obj, center)
        return {"FINISHED"}


class SAS_OT_frame_camera(StudioOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.frame_camera"
    bl_label = "Frame Camera"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        asset = asset_collection(context)
        studio = asset.get(STUDIO)
        if studio:
            restore_range(context.scene, studio)
            for obj in tuple(studio.objects):
                if obj.get("souls_orbit"):
                    for child in obj.children:
                        child.parent = None
                    remove_object(obj)
        frame_camera(context.scene, asset, *bounds(asset))
        return {"FINISHED"}


class SAS_OT_turntable(StudioOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.turntable"
    bl_label = "Make Turntable"
    bl_options = {"REGISTER", "UNDO"}

    seconds: FloatProperty(name="Seconds", default=8, min=1, max=60)

    def execute(self, context):
        scene = context.scene
        asset = asset_collection(context)
        center, span = bounds(asset)
        camera = frame_camera(scene, asset, center, span)
        studio = asset[STUDIO]
        restore_range(scene, studio)
        orbit = next((obj for obj in studio.objects if obj.get("souls_orbit")), None)
        if orbit is None:
            orbit = bpy.data.objects.new("Camera Orbit", None)
            orbit["souls_orbit"] = True
            studio.objects.link(orbit)
        orbit.animation_data_clear()
        orbit.location = center
        orbit.rotation_euler.z = 0
        camera.parent = orbit
        camera.matrix_parent_inverse.identity()
        camera.location -= center
        first = scene.frame_start
        last = first + max(2, round(self.seconds * scene.render.fps / scene.render.fps_base))
        for frame, angle in ((first, 0), (last, tau)):
            orbit.rotation_euler.z = angle
            orbit.keyframe_insert("rotation_euler", index=2, frame=frame)
        data = orbit.animation_data
        bag = data.action.layers[0].strips[0].channelbag(data.action_slot)
        for key in bag.fcurves[0].keyframe_points:
            key.interpolation = "LINEAR"
        studio[TURNTABLE_RANGE] = [scene.frame_end, last - 1]
        scene.frame_end = last - 1
        scene.frame_set(first)
        return {"FINISHED"}


class SAS_OT_remove_studio(StudioOperator, bpy.types.Operator):
    bl_idname = "souls_asset_studio.remove_studio"
    bl_label = "Remove Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        asset = asset_collection(context)
        studio = asset.get(STUDIO)
        if studio is None:
            return {"CANCELLED"}
        restore_range(context.scene, studio)
        if context.scene.camera in studio.objects[:]:
            context.scene.camera = studio.get(PREVIOUS_CAMERA)
        for obj in tuple(studio.objects):
            if obj.get("souls_camera") or obj.get("souls_orbit") or obj.get("souls_light"):
                remove_object(obj)
        if not studio.objects and not studio.children:
            bpy.data.collections.remove(studio)
            del asset[STUDIO]
        return {"FINISHED"}


class SAS_OT_render_turntable(bpy.types.Operator, ExportHelper):
    bl_idname = "souls_asset_studio.render_turntable"
    bl_label = "Render Turntable"

    filename_ext = ".mp4"
    filter_glob: StringProperty(default="*.mp4", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        asset = asset_collection(context)
        studio = asset.get(STUDIO) if asset else None
        return (bpy.app.build_options.codec_ffmpeg and studio is not None
                and TURNTABLE_RANGE in studio and context.scene.camera in studio.objects[:])

    def execute(self, context):
        from pathlib import Path
        render = context.scene.render
        # Blender appends the extension to the animation path.
        render.filepath = str(Path(self.filepath).with_suffix(""))
        render.use_file_extension = True
        if hasattr(render.image_settings, "media_type"):
            render.image_settings.media_type = "VIDEO"
        else:
            render.image_settings.file_format = "FFMPEG"
        render.ffmpeg.format = "MPEG4"
        render.ffmpeg.codec = "H264"
        bpy.ops.render.render("INVOKE_DEFAULT", animation=True)
        return {"FINISHED"}
