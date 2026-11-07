import bpy
from bpy.props import StringProperty

from .clips import SAS_OT_import_clips
from .operators import (
    SAS_OT_activate_clip,
    SAS_OT_apply_souls_shader,
    SAS_OT_compact_bones,
    SAS_OT_import_asset,
    SAS_OT_toggle_root_lock,
)
from .poses import SAS_OT_apply_pose, SAS_OT_bind_pose, SAS_OT_delete_pose, SAS_OT_save_pose
from .preview_world import SAS_OT_restore_world, SAS_OT_use_preview_hdri
from .staging import (
    SAS_OT_frame_camera, SAS_OT_remove_studio, SAS_OT_render_turntable,
    SAS_OT_studio_lighting, SAS_OT_turntable,
)
from .ui import SAS_PT_assets, SAS_PT_materials, SAS_PT_poses, SAS_PT_studio, import_menu


CLASSES = (
    SAS_OT_import_asset,
    SAS_OT_import_clips,
    SAS_OT_activate_clip,
    SAS_OT_apply_souls_shader,
    SAS_OT_compact_bones,
    SAS_OT_toggle_root_lock,
    SAS_OT_apply_pose,
    SAS_OT_bind_pose,
    SAS_OT_delete_pose,
    SAS_OT_save_pose,
    SAS_OT_frame_camera,
    SAS_OT_remove_studio,
    SAS_OT_render_turntable,
    SAS_OT_studio_lighting,
    SAS_OT_turntable,
    SAS_OT_use_preview_hdri,
    SAS_OT_restore_world,
    SAS_PT_assets,
    SAS_PT_poses,
    SAS_PT_materials,
    SAS_PT_studio,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.souls_clip_filter = StringProperty(name="Filter", options={"SKIP_SAVE"})
    bpy.types.TOPBAR_MT_file_import.append(import_menu)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(import_menu)
    del bpy.types.WindowManager.souls_clip_filter
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
