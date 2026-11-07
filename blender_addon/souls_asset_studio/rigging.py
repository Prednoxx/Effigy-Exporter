from math import floor, isfinite

import bpy
from mathutils import Vector


ROOT_LOCK = "souls_root_lock"
LOCATION_LOCK = "Souls Root Lock Location"
ROTATION_LOCK = "Souls Root Lock Rotation"
ROOT_PATHS = {"location", "rotation_quaternion", "rotation_euler", "rotation_axis_angle"}


def compact_bones(context, rig, objects):
    rig.data.display_type = "STICK"
    inverse = rig.matrix_world.inverted_safe()
    points = []
    for obj in objects:
        if obj.type != "MESH" or not obj.data.vertices:
            continue
        if not any(mod.type == "ARMATURE" and mod.object == rig for mod in obj.modifiers):
            continue
        relative = inverse @ obj.matrix_world
        points.extend(relative @ Vector(corner) for corner in obj.bound_box)
    if not points:
        return

    span = max(max(axis) - min(axis) for axis in zip(*points))
    if not isfinite(span) or span <= 0:
        return
    limit = max(span * 0.04, 0.0001)
    # A connected child's head is tied to its parent's tail.
    connected_parents = {bone.parent for bone in rig.data.bones if bone.use_connect}
    oversized = {bone.name for bone in rig.data.bones
                 if bone.length > limit and bone not in connected_parents}
    if not oversized:
        return

    layer = context.view_layer
    previous = layer.objects.active
    other_rigs = [obj for obj in context.selected_objects if obj != rig and obj.type == "ARMATURE"]
    was_selected = rig.select_get()
    for obj in other_rigs:
        obj.select_set(False)
    rig.select_set(True)
    layer.objects.active = rig
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        for name in oversized:
            rig.data.edit_bones[name].length = limit
    finally:
        if rig.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        layer.objects.active = previous
        rig.select_set(was_selected)
        for obj in other_rigs:
            obj.select_set(True)


def has_root_motion(obj):
    if obj.type not in {"ARMATURE", "EMPTY"}:
        return False
    data = obj.animation_data
    if not data or not data.action or not data.action_slot:
        return False
    for layer in data.action.layers:
        for strip in layer.strips:
            bag = strip.channelbag(data.action_slot)
            if bag and any(curve.data_path in ROOT_PATHS for curve in bag.fcurves):
                return True
    return False


def set_root_lock(scene, collection, enabled):
    for obj in collection.objects:
        for name in (LOCATION_LOCK, ROTATION_LOCK):
            constraint = obj.constraints.get(name)
            if constraint:
                obj.constraints.remove(constraint)
    collection[ROOT_LOCK] = enabled
    if not enabled:
        return

    roots = [obj for obj in collection.objects if has_root_motion(obj)]
    if not roots:
        return

    current, subframe = scene.frame_current, scene.frame_subframe
    first = min(obj.animation_data.action.frame_range[0] for obj in roots)
    try:
        scene.frame_set(floor(first), subframe=first - floor(first))
        for obj in roots:
            location, rotation, _ = obj.matrix_basis.decompose()
            for kind, name, values in (
                ("LIMIT_LOCATION", LOCATION_LOCK, location),
                ("LIMIT_ROTATION", ROTATION_LOCK, rotation.to_euler("XYZ")),
            ):
                constraint = obj.constraints.new(kind)
                constraint.name = name
                # Unparented objects use their animated axes in constraint local space.
                constraint.owner_space = "LOCAL" if obj.parent else "WORLD"
                if kind == "LIMIT_ROTATION":
                    constraint.euler_order = "XYZ"
                for axis, value in zip("xyz", values):
                    setattr(constraint, f"min_{axis}", value)
                    setattr(constraint, f"max_{axis}", value)
                    if kind == "LIMIT_LOCATION":
                        setattr(constraint, f"use_min_{axis}", True)
                        setattr(constraint, f"use_max_{axis}", True)
                    else:
                        setattr(constraint, f"use_limit_{axis}", True)
    finally:
        scene.frame_set(current, subframe=subframe)
