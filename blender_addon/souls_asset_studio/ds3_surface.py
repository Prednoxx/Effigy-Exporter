import bpy


GROUP = "Dark Souls III Surface"
GROUP_VERSION = "souls_ds3_surface"


def ds3_surface_group():
    existing = next((tree for tree in bpy.data.node_groups if tree.get(GROUP_VERSION) == 1), None)
    if existing is not None:
        return existing

    tree = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
    tree[GROUP_VERSION] = 1
    sockets = (
        ("Diffuse", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0)),
        ("Reflectance", "NodeSocketColor", (0.04, 0.04, 0.04, 1.0)),
        ("Roughness", "NodeSocketFloat", 0.65),
        ("Normal", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Alpha", "NodeSocketFloat", 1.0),
        ("Emission Color", "NodeSocketColor", (0.0, 0.0, 0.0, 1.0)),
        ("Emission Strength", "NodeSocketFloat", 0.0),
        ("Subsurface Weight", "NodeSocketFloat", 0.0),
    )
    for name, socket_type, default in sockets:
        socket = tree.interface.new_socket(name=name, in_out="INPUT", socket_type=socket_type)
        socket.default_value = default
        if name == "Normal":
            socket.hide_value = True
    tree.interface.new_socket(name="Surface", in_out="OUTPUT", socket_type="NodeSocketShader")

    nodes, links = tree.nodes, tree.links
    incoming = nodes.new("NodeGroupInput")
    incoming.location = (-640, 100)
    outgoing = nodes.new("NodeGroupOutput")
    outgoing.location = (670, 100)

    invert = nodes.new("ShaderNodeInvert")
    invert.label = "Diffuse energy after reflection"
    invert.location = (-410, 260)
    links.new(incoming.outputs["Reflectance"], invert.inputs["Color"])
    attenuate = nodes.new("ShaderNodeMixRGB")
    attenuate.blend_type = "MULTIPLY"
    attenuate.inputs[0].default_value = 1
    attenuate.location = (-220, 260)
    links.new(incoming.outputs["Diffuse"], attenuate.inputs[1])
    links.new(invert.outputs["Color"], attenuate.inputs[2])

    diffuse = nodes.new("ShaderNodeBsdfPrincipled")
    diffuse.label = "Diffuse and skin scattering"
    diffuse.location = (0, 275)
    diffuse.inputs["Specular IOR Level"].default_value = 0
    diffuse.inputs["Subsurface Scale"].default_value = 0.008
    links.new(attenuate.outputs["Color"], diffuse.inputs["Base Color"])
    for name in ("Normal", "Emission Color", "Emission Strength", "Subsurface Weight"):
        links.new(incoming.outputs[name], diffuse.inputs[name])

    specular = nodes.new("ShaderNodeBsdfPrincipled")
    specular.label = "Colored reflectance and gloss"
    specular.location = (0, -210)
    specular.inputs["Metallic"].default_value = 1
    links.new(incoming.outputs["Reflectance"], specular.inputs["Base Color"])
    links.new(incoming.outputs["Normal"], specular.inputs["Normal"])
    links.new(incoming.outputs["Roughness"], specular.inputs["Roughness"])

    combined = nodes.new("ShaderNodeAddShader")
    combined.location = (260, 190)
    links.new(diffuse.outputs[0], combined.inputs[0])
    links.new(specular.outputs[0], combined.inputs[1])
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (255, -40)
    cutout = nodes.new("ShaderNodeMixShader")
    cutout.location = (455, 100)
    links.new(incoming.outputs["Alpha"], cutout.inputs[0])
    links.new(transparent.outputs[0], cutout.inputs[1])
    links.new(combined.outputs[0], cutout.inputs[2])
    links.new(cutout.outputs[0], outgoing.inputs[0])
    return tree


def use_ds3_surface(material, principled):
    tree = material.node_tree
    group = tree.nodes.new("ShaderNodeGroup")
    group.node_tree = ds3_surface_group()
    group.label = principled.label
    group.location = principled.location
    group.width = 230
    for name, source_name in (
        ("Diffuse", "Base Color"),
        ("Reflectance", "Specular Tint"),
        ("Roughness", "Roughness"),
        ("Normal", "Normal"),
        ("Alpha", "Alpha"),
        ("Emission Color", "Emission Color"),
        ("Emission Strength", "Emission Strength"),
        ("Subsurface Weight", "Subsurface Weight"),
    ):
        source = principled.inputs[source_name]
        target = group.inputs[name]
        if source.is_linked:
            tree.links.new(source.links[0].from_socket, target)
        elif name != "Normal":
            target.default_value = source.default_value
        else:
            geometry = tree.nodes.new("ShaderNodeNewGeometry")
            geometry.location = (group.location.x - 240, group.location.y - 220)
            tree.links.new(geometry.outputs["Normal"], target)
    destinations = [link.to_socket for link in principled.outputs[0].links]
    tree.nodes.remove(principled)
    for destination in destinations:
        tree.links.new(group.outputs["Surface"], destination)
