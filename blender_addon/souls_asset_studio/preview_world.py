from pathlib import Path

import bpy


PREVIEW_WORLD = "souls_preview_world"
ORIGINAL_WORLD = "souls_original_world"
ENVIRONMENT = "Souls Preview HDRI"
BACKGROUND = "Souls Preview Strength"


def studio_light(context):
    shading = context.space_data.shading if context.space_data and context.space_data.type == "VIEW_3D" else None
    lights = {light.name: light.path for light in context.preferences.studio_lights if light.type == "WORLD"}
    if shading and shading.studio_light in lights:
        return (lights[shading.studio_light], shading.studiolight_intensity, shading.studiolight_rotate_z)
    return lights.get("forest.exr"), 1.0, 0.0


def apply_preview_world(scene, filepath, strength, angle):
    if not filepath or not Path(filepath).is_file():
        raise ValueError("Preview HDRI unavailable")

    current = scene.world
    cached = scene.get(PREVIEW_WORLD)
    existing = current is not None and current == cached
    tree = current.node_tree if existing else None
    environment = tree.nodes.get(current.get(ENVIRONMENT, ENVIRONMENT)) if tree else None
    fill = tree.nodes.get(current.get(BACKGROUND, BACKGROUND)) if tree else None
    if existing and (environment is None or fill is None):
        raise ValueError("Preview world nodes changed. Restore World first.")
    if environment is None or environment.image is None or environment.image.filepath != filepath:
        image = bpy.data.images.load(filepath, check_existing=True)
        if not image.packed_file:
            image.pack()
    else:
        image = environment.image

    if not existing:
        world = current.copy() if current else bpy.data.worlds.new("Preview Lighting")
        if not world.use_nodes:
            world.use_nodes = True
        tree = world.node_tree
        world.name = "Preview Lighting"
        environment = tree.nodes.new("ShaderNodeTexEnvironment")
        environment.name = ENVIRONMENT
        environment.label = ENVIRONMENT
        environment.location = (-670, 290)
        coordinates = tree.nodes.new("ShaderNodeTexCoord")
        coordinates.location = (-890, 290)
        tree.links.new(coordinates.outputs["Generated"], environment.inputs["Vector"])

        fill = tree.nodes.new("ShaderNodeBackground")
        fill.name = BACKGROUND
        fill.location = (-390, 290)
        tree.links.new(environment.outputs["Color"], fill.inputs["Color"])
        camera_ray = tree.nodes.new("ShaderNodeLightPath")
        camera_ray.location = (-660, -20)
        outputs = [node for node in tree.nodes if node.type == "OUTPUT_WORLD"]
        for output in outputs or [tree.nodes.new("ShaderNodeOutputWorld")]:
            socket = output.inputs["Surface"]
            source = socket.links[0].from_socket if socket.is_linked else None
            if source:
                mix = tree.nodes.new("ShaderNodeMixShader")
                mix.location = (output.location.x - 210, output.location.y + 220)
                tree.links.new(camera_ray.outputs["Is Camera Ray"], mix.inputs[0])
                tree.links.new(fill.outputs[0], mix.inputs[1])
                tree.links.new(source, mix.inputs[2])
                source = mix.outputs[0]
            tree.links.new(source if source else fill.outputs[0], socket)

        world[ENVIRONMENT] = environment.name
        world[BACKGROUND] = fill.name
        scene[PREVIEW_WORLD] = world
        if current:
            scene[ORIGINAL_WORLD] = current
        elif ORIGINAL_WORLD in scene:
            del scene[ORIGINAL_WORLD]
        scene.world = world

    environment.image = image
    environment.texture_mapping.vector_type = "VECTOR"
    environment.texture_mapping.rotation[2] = angle
    fill.inputs["Strength"].default_value = strength


class SAS_OT_use_preview_hdri(bpy.types.Operator):
    bl_idname = "souls_asset_studio.use_preview_hdri"
    bl_label = "Use Preview HDRI"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            apply_preview_world(context.scene, *studio_light(context))
        except (OSError, RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class SAS_OT_restore_world(bpy.types.Operator):
    bl_idname = "souls_asset_studio.restore_world"
    bl_label = "Restore World"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene.world is not None and context.scene.world == context.scene.get(PREVIEW_WORLD)

    def execute(self, context):
        scene = context.scene
        world = scene.world
        scene.world = scene.get(ORIGINAL_WORLD)
        for name in (PREVIEW_WORLD, ORIGINAL_WORLD):
            if name in scene:
                del scene[name]
        if not world.users:
            bpy.data.worlds.remove(world)
        return {"FINISHED"}
