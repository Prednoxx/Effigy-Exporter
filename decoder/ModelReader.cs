using System.Numerics;
using System.Text.Json;
using SoulsFormats;

internal static class ModelReader
{
    private static float[] Vector(Vector3 value) => new[] { value.X, value.Y, value.Z };

    public static int Run(string input, string output)
    {
        try
        {
            var model = FLVER2.Read(input);
            var result = new
            {
                bones = model.Nodes.Select(node => new
                {
                    name = node.Name, parent_bone_index = node.ParentIndex,
                    translate = Vector(node.Translation), rotate = Vector(node.Rotation), scale = Vector(node.Scale),
                }),
                dummies = model.Dummies.Select(dummy => new
                {
                    reference_id = dummy.ReferenceID, parent_bone_index = dummy.ParentBoneIndex,
                    attach_bone_index = dummy.AttachBoneIndex,
                    translate = Vector(dummy.Position), forward = Vector(dummy.Forward), upward = Vector(dummy.Upward),
                }),
                materials = model.Materials.Select(material => new
                {
                    name = material.Name, mat_def_path = material.MTD,
                    textures = material.Textures.Select(texture => new
                    {
                        path = texture.Path, texture_type = texture.ParamName,
                        scale = new[] { texture.TilingScale.X, texture.TilingScale.Y },
                    }),
                }),
                meshes = model.Meshes.Select(mesh =>
                {
                    var faces = mesh.FaceSets.FirstOrDefault(set => set.Flags == 0) ?? mesh.FaceSets.FirstOrDefault();
                    var lodFaces = mesh.FaceSets
                        .Where(set => (set.Flags & FLVER2.FaceSet.FSFlags.MotionBlur) == 0)
                        .Select(set => new
                        {
                            set,
                            level = ((uint)set.Flags >> 24 & 7) switch
                            {
                                0 => 0, 1 => 1, 2 => 2, 4 => 3, _ => -1,
                            },
                        })
                        .Where(item => item.level >= 0)
                        .GroupBy(item => item.level)
                        .Select(group => new
                        {
                            level = group.Key,
                            indices = group.First().set.Triangulate(mesh.Vertices.Count < ushort.MaxValue),
                        });
                    return new
                    {
                        material = mesh.MaterialIndex, is_dynamic = mesh.UseBoneWeights,
                        default_bone_index = mesh.NodeIndex, bone_indices = mesh.BoneIndices,
                        faces = faces?.Triangulate(mesh.Vertices.Count < ushort.MaxValue),
                        lod_faces = lodFaces,
                        positions = mesh.Vertices.Select(vertex => Vector(vertex.Position)),
                        normals = mesh.Vertices.Select(vertex => Vector(vertex.Normal)),
                        normal_w = mesh.Vertices.Select(vertex => vertex.NormalW),
                        uvs = mesh.Vertices.Select(vertex => vertex.UVs.Select(uv => new[] { uv.X, uv.Y })),
                        weights = mesh.UseBoneWeights ? mesh.Vertices.Select(vertex => new[]
                        {
                            vertex.BoneWeights[0], vertex.BoneWeights[1], vertex.BoneWeights[2], vertex.BoneWeights[3],
                        }) : null,
                        joints = mesh.UseBoneWeights ? mesh.Vertices.Select(vertex => new[]
                        {
                            vertex.BoneIndices[0], vertex.BoneIndices[1], vertex.BoneIndices[2], vertex.BoneIndices[3],
                        }) : null,
                    };
                }),
            };
            using var stream = File.Create(output);
            JsonSerializer.Serialize(stream, result);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"FLVER: {error.Message}");
            return 1;
        }
    }
}
