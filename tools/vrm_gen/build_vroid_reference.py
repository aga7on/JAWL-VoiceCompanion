"""Create an editable, geometry-and-palette adaptation of the VRoid sample."""
from pathlib import Path
import sys
import json
import struct

import addon_utils
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_tailoring import add_soft_helper_bones, build_reference_garments
from reference_head import build_layered_hair, refine_face


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/vrm-models/AvatarSample_A.vrm"
OUTPUT = ROOT / "runtime/vrm-models/JawlieRefinedV2.vrm"
EDITABLE = ROOT / "runtime/character-reference/jawlie-refined-v2.blend"
PREVIEW_PREFIX = "jawlie-refined-v2"
SCRIPT_ARGS = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
if '--seam-review' in SCRIPT_ARGS:
    raise ValueError('Source-top experiment rejected: hoodie remnants and shirt clipping; use --fit-review')
INTERFACE_REVIEW = '--interface-review' in SCRIPT_ARGS
HAIR_SCULPT_REVIEW = '--hair-sculpt-review' in SCRIPT_ARGS or INTERFACE_REVIEW
HAIR_REVIEW = '--hair-review' in SCRIPT_ARGS or HAIR_SCULPT_REVIEW
SHOULDER_REVIEW = '--shoulder-review' in SCRIPT_ARGS or HAIR_REVIEW
FIT_REVIEW = '--fit-review' in SCRIPT_ARGS or SHOULDER_REVIEW
BLOCKING = '--blocking' in SCRIPT_ARGS or FIT_REVIEW
if BLOCKING:
    OUTPUT = ROOT / 'runtime/vrm-models/JawlieBlockingV3.vrm'
    EDITABLE = ROOT / 'runtime/character-reference/jawlie-blocking-v3.blend'
    PREVIEW_PREFIX = 'jawlie-blocking-v3'
if FIT_REVIEW:
    OUTPUT = ROOT / 'runtime/vrm-models/JawlieFitV4.vrm'
    EDITABLE = ROOT / 'runtime/character-reference/jawlie-fit-v4.blend'
    PREVIEW_PREFIX = 'jawlie-fit-v4'
if SHOULDER_REVIEW:
    OUTPUT = ROOT / 'runtime/vrm-models/JawlieShoulderV6.vrm'
    EDITABLE = ROOT / 'runtime/character-reference/jawlie-shoulder-v6.blend'
    PREVIEW_PREFIX = 'jawlie-shoulder-v6'
if HAIR_REVIEW:
    OUTPUT = ROOT / 'runtime/vrm-models/JawlieHairV7.vrm'
    EDITABLE = ROOT / 'runtime/character-reference/jawlie-hair-v7.blend'
    PREVIEW_PREFIX = 'jawlie-hair-v7'
if HAIR_SCULPT_REVIEW:
    OUTPUT = ROOT / 'runtime/vrm-models/JawlieHairV8.vrm'
    EDITABLE = ROOT / 'runtime/character-reference/jawlie-hair-v8.blend'
    PREVIEW_PREFIX = 'jawlie-hair-v8'
if INTERFACE_REVIEW:
    OUTPUT = ROOT / 'runtime/vrm-models/JawlieInterfaceV9.vrm'
    EDITABLE = ROOT / 'runtime/character-reference/jawlie-interface-v9.blend'
    PREVIEW_PREFIX = 'jawlie-interface-v9'
LICENSE_URL = "https://vroid.pixiv.help/hc/en-us/articles/4402394424089-VRoidPreset-A-Z"


def read_vrm_document(path):
    blob = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", blob)
    chunk_size, chunk_type = struct.unpack_from("<I4s", blob, 12)
    if magic != b"glTF" or version != 2 or length != len(blob) or chunk_type != b"JSON":
        raise RuntimeError(f"Invalid VRM/GLB container: {path}")
    return json.loads(blob[20:20 + chunk_size])


def enable_vrm_addon():
    modules = [m.__name__ for m in addon_utils.modules() if "vrm" in m.__name__.lower()]
    if not modules:
        raise RuntimeError("Blender VRM add-on is unavailable")
    for module in modules:
        addon_utils.enable(module, default_set=False, persistent=False)


def tint_materials():
    palette = {
        "F00_000_Hair_00_HAIR_01": (0.32, 0.205, 0.112, 1),
        "F00_000_Hair_00_HAIR_02": (0.275, 0.165, 0.084, 1),
        "F00_000_Hair_00_HAIR_03": (0.24, 0.137, 0.067, 1),
        "F00_000_Hair_00_HAIR_04": (0.285, 0.172, 0.089, 1),
        "F00_000_00_EyeIris_00_EYE": (0.19, 0.62, 0.29, 1),
        "F00_006_01_Tops_01_CLOTH": (0.035, 0.18, 0.17, 1),
        "F00_008_01_Bottoms_01_CLOTH": (0.035, 0.043, 0.052, 1),
        "F00_001_01_Shoes_01_CLOTH": (0.035, 0.043, 0.052, 1),
    }
    changed = set()
    for material in bpy.data.materials:
        if material.name.startswith("MToon Outline"):
            continue
        color = next((rgba for token, rgba in palette.items() if token in material.name), None)
        if color is None:
            continue
        material.vrm_addon_extension.mtoon1.pbr_metallic_roughness.base_color_factor = color
        material.diffuse_color = color
        if any(token in material.name for token in ("Tops", "Bottoms", "Shoes", "HAIR")):
            flatten_material(material, color)
        changed.add(next(token for token in palette if token in material.name))
    missing = set(palette) - changed
    if missing:
        raise RuntimeError(f"Expected source materials were not imported: {sorted(missing)}")


def new_mtoon_material(name, template, color):
    material = template.copy()
    material.name = name
    flatten_material(material, color)
    return material


def flatten_material(material, color):
    material.diffuse_color = color
    material.vrm_addon_extension.mtoon1.pbr_metallic_roughness.base_color_factor = color
    # TextureInfo.image is not an RNA field in the installed VRM addon.
    # Clear its real source pointer so VRM export matches the Blender preview.
    material.vrm_addon_extension.mtoon1.pbr_metallic_roughness.base_color_texture.index.source = None
    material.vrm_addon_extension.mtoon1.normal_texture.index.source = None
    material.vrm_addon_extension.mtoon1.emissive_texture.index.source = None
    toon = material.vrm_addon_extension.mtoon1.extensions.vrmc_materials_mtoon
    toon.shade_multiply_texture.index.source = None
    toon.matcap_texture.index.source = None
    toon.rim_multiply_texture.index.source = None
    toon.outline_width_multiply_texture.index.source = None
    toon.shade_color_factor = tuple(channel * 0.72 for channel in color[:3])
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = 0.78
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])


def render_previews(armature):
    from mathutils import Vector, Quaternion

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 900, 1100
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.035, 0.045, 0.055)

    def area(name, location, energy, size):
        lamp_data = bpy.data.lights.new(name, "AREA")
        lamp_data.energy, lamp_data.shape, lamp_data.size = energy, "DISK", size
        lamp = bpy.data.objects.new(name, lamp_data)
        scene.collection.objects.link(lamp)
        lamp.location = location
        lamp.rotation_euler = (Vector((0, 0, 0.82)) - lamp.location).to_track_quat("-Z", "Y").to_euler()

    area("Reference Key", (-2.2, -3.0, 3.2), 120, 3.0)
    area("Reference Fill", (2.4, -2.5, 1.8), 55, 2.5)
    area("Reference Rim", (0.0, 1.8, 2.8), 90, 2.2)
    camera_data = bpy.data.cameras.new("Reference Camera")
    camera = bpy.data.objects.new("Reference Camera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type, camera_data.ortho_scale = "ORTHO", 1.92
    scene.camera = camera
    target = Vector((0, 0, 0.79))
    camera_data.lens = 52
    out_dir = ROOT / "runtime/character-reference"
    out_dir.mkdir(parents=True, exist_ok=True)
    views = (
        ("front", (0, -4.0, 0.92)),
        ("three-quarter", (-2.5, -3.7, 0.92)),
        ("back", (0, 4.0, 0.92)),
        ("profile", (-4.0, 0, 0.92)),
    )
    def capture(name, location, look_at=target, scale=1.92):
        camera.location = location
        camera_data.ortho_scale = scale
        camera.rotation_euler = (look_at - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out_dir / f"{PREVIEW_PREFIX}-{name}.png")
        bpy.ops.render.render(write_still=True)
    if '--preview-fast' not in SCRIPT_ARGS:
        for name, location in views:
            capture(name, location)
    # A relaxed pose exposes garment fit that a T-pose can hide. Preview only:
    # restore all pose bases before saving/export, never bake a bent rest rig.
    bases={bone.name:bone.matrix_basis.copy() for bone in armature.pose.bones}
    try:
        for side,angle in (("L",1.27),("R",-1.27)):
            bone=armature.pose.bones['J_Bip_'+side+'_UpperArm']
            axis=bone.bone.matrix_local.to_quaternion().inverted() @ Vector((0,1,0))
            bone.rotation_mode='QUATERNION'; bone.rotation_quaternion=Quaternion(axis,angle)
        bpy.context.view_layer.update()
        for name,location in views:
            capture("rest-"+name,location)
        for name,location,focus,scale in (
            ('face',(0,-3,1.43),(0,0,1.43),.40),
            ('face-profile',(-3,0,1.43),(0,0,1.43),.40),
            ('face-quarter',(-2,-3,1.43),(0,0,1.43),.40),
            ('crown-back',(0,3,1.47),(0,0,1.47),.35),
            ('collar-front',(0,-3,1.245),(0,0,1.245),.51),
            ('collar-back',(0,3,1.245),(0,0,1.245),.51),
            ('shoulder',(-2,-3,1.24),(-.14,0,1.24),.32),
            ('waist-front',(0,-3,.95),(0,0,.95),.44),
            ('waist-back',(0,3,.94),(0,0,.94),.44),
            ('pocket',(-3,-3,.70),(-.105,0,.70),.30),
            ('knees',(0,-3,.47),(0,0,.47),.49),
            ('boots-front',(0,-3,.13),(0,0,.13),.34),
            ('boots-quarter',(-3,-3,.13),(0,0,.13),.34),
            ('boots-back',(0,3,.13),(0,0,.13),.34),
        ):
            quick_names = ('boots-front', 'boots-quarter', 'boots-back') if INTERFACE_REVIEW else ('face', 'face-profile', 'face-quarter', 'crown-back')
            if '--preview-fast' in SCRIPT_ARGS and name not in quick_names:
                continue
            if BLOCKING and not FIT_REVIEW and name not in ('face', 'face-profile', 'face-quarter', 'crown-back'):
                continue
            capture(name,location,Vector(focus),scale)
        if (not BLOCKING or FIT_REVIEW) and ('--preview-fast' not in SCRIPT_ARGS or INTERFACE_REVIEW):
            hand=armature.pose.bones['J_Bip_R_Hand'].matrix.translation.copy()
            hand.z-=.02
            capture('hand-front',(hand.x,-3,hand.z),hand,.25)
            capture('hand-back',(hand.x,3,hand.z),hand,.25)
        if FIT_REVIEW and '--preview-fast' not in SCRIPT_ARGS:
            capture('boots-underside',(-1.5,-1.0,-2.0),Vector((0,-.03,.06)),.34)
    finally:
        for bone in armature.pose.bones: bone.matrix_basis=bases[bone.name]
        bpy.context.view_layer.update()


def preserve_vroid_attribution(armature):
    extension = armature.data.vrm_addon_extension
    legacy_meta = extension.vrm0.meta
    legacy_meta.author = "VRoid"
    legacy_meta.license_name = "Other"
    legacy_meta.other_license_url = LICENSE_URL
    meta = extension.vrm1.meta
    meta.vrm_name = "Jawlie Hair V8 — primary volumes and clean temples" if HAIR_SCULPT_REVIEW else ("Jawlie Hair V7 — asymmetric silhouette review" if HAIR_REVIEW else ("Jawlie Shoulder V6 — connected garment review" if SHOULDER_REVIEW else ("Jawlie Fit V4 — geometry defect review" if FIT_REVIEW else ("Jawlie Blocking V3 — silhouette review" if BLOCKING else "Jawlie Refined V2 — reference work in progress"))))
    if INTERFACE_REVIEW:
        meta.vrm_name = "Jawlie Interface V9 — fitted wrist and ankle contacts"
    meta.modification = "allowModification"
    meta.other_license_url = LICENSE_URL
    meta.credit_notation = "required"
    while meta.authors:
        meta.authors.remove(0)
    meta.authors.add().value = "VRoid"
    extension.spec_version = "0.0"


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    enable_vrm_addon()

    # Blender's startup cube is not part of the source VRM.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    result = bpy.ops.import_scene.vrm(filepath=str(SOURCE))
    if "FINISHED" not in result:
        raise RuntimeError(f"VRM import failed: {result}")

    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if len(armatures) != 1 or not {"Face", "Body", "Hair001"}.issubset({o.name for o in meshes}):
        raise RuntimeError("Imported sample is missing its expected face, body, hair, or rig")
    armature = armatures[0]
    # The VRM0 importer keeps a 180-degree mesh rotation, while its armature
    # is identity. New meshes must share WORLD/rest coordinates and weights.
    # Bake it on ALL morph keys too; do not copy local vertices onto identity
    # objects and accidentally bind the right sleeve to the left shoulder.
    bpy.ops.object.select_all(action='DESELECT')
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    face = next(obj for obj in meshes if obj.name == "Face")
    if not face.data.shape_keys or len(face.data.shape_keys.key_blocks) < 50:
        raise RuntimeError("Imported face expression morphs are incomplete")
    humanoid_count = len(armature.data.vrm_addon_extension.vrm1.humanoid.human_bones.human_bone_name_to_human_bone())
    if humanoid_count < 50:
        raise RuntimeError("Imported humanoid bone map is incomplete")
    body = next(obj for obj in meshes if obj.name == "Body")
    top_template = next(m for m in body.data.materials if "Tops" in m.name)
    bottom_template = next(m for m in body.data.materials if "Bottoms" in m.name)
    garment_materials = {
        "pants": new_mtoon_material("Jawlie Cargo Twill", bottom_template, (0.035, 0.043, 0.052, 1)),
        "cargo": new_mtoon_material("Jawlie Cargo Pocket", bottom_template, (0.065, 0.078, 0.085, 1)),
        "mint": new_mtoon_material("Jawlie Mint Trim", top_template, (0.30, 0.65, 0.44, 1)),
        "jacket": new_mtoon_material("Jawlie Petrol Bomber", top_template, (0.032, 0.095, 0.111, 1)),
        "shirt": new_mtoon_material("Jawlie White Crew Shirt", top_template, (0.88, 0.90, 0.86, 1)),
        "boots": new_mtoon_material("Jawlie Black Boot Leather", bottom_template, (0.025, 0.03, 0.036, 1)),
        "sole": new_mtoon_material("Jawlie Mint Boot Sole", top_template, (0.30, 0.65, 0.44, 1)),
        "rib": new_mtoon_material("Jawlie Bomber Rib Knit", top_template, (0.019, 0.064, 0.074, 1)),
        "seam": new_mtoon_material("Jawlie Seam and Laces", top_template, (0.075, 0.095, 0.105, 1)),
        "metal": new_mtoon_material("Jawlie Brushed Buckle", top_template, (0.18, 0.21, 0.22, 1)),
    }
    add_soft_helper_bones(armature)
    meshes.extend(build_reference_garments(body, armature, garment_materials, blocking=BLOCKING,fit_review=FIT_REVIEW,shoulder_review=SHOULDER_REVIEW,interface_review=INTERFACE_REVIEW))
    # The sample's Body skin atlas paints a short maroon undercut behind the
    # ears. Remove that inherited scalp marking via a separate material slot;
    # retain the original face, hand UVs and nail material without image edits.
    skin_template=next(m for m in body.data.materials if 'Body_00_SKIN' in m.name)
    clean_skin=new_mtoon_material('Jawlie Clean Neck Skin',skin_template,(.94,.63,.44,1))
    body.data.materials.append(clean_skin)
    for polygon in body.data.polygons:
        if sum(body.data.vertices[i].co.z for i in polygon.vertices)/len(polygon.vertices)>1.27:
            polygon.material_index=len(body.data.materials)-1
    if HAIR_SCULPT_REVIEW:
        from reference_head import clean_temple_marking
        # Localized UV remap, preserving the face shader and licensed atlas.
        clean_temple_marking(face)
    tint_materials()
    hair=next(obj for obj in meshes if obj.name == 'Hair001')
    meshes.remove(hair)
    if BLOCKING:
        from reference_hair_blocking import build_blocking_hair
        meshes.extend(build_blocking_hair(hair,armature,refined=HAIR_REVIEW,sculpted=HAIR_SCULPT_REVIEW))
    else:
        meshes.extend(build_layered_hair(hair,armature))
    assert refine_face(face)==56
    mesh_signature=sorted((obj.name,len(obj.data.vertices),len(obj.data.polygons),
        len(obj.data.shape_keys.key_blocks) if obj.data.shape_keys else 0) for obj in meshes)
    preserve_vroid_attribution(armature)
    render_previews(armature)
    EDITABLE.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(EDITABLE))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in [*meshes, armature]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    result = bpy.ops.export_scene.vrm(
        filepath=str(OUTPUT),
        armature_object_name=armature.name,
        export_only_selections=True,
    )
    if "FINISHED" not in result or not OUTPUT.is_file() or OUTPUT.stat().st_size < 1_000_000:
        raise RuntimeError(f"VRM export failed or produced an incomplete file: {result}")

    document = read_vrm_document(OUTPUT)
    vrm = document.get("extensions", {}).get("VRM") or document.get("extensions", {}).get("VRMC_vrm")
    if not vrm:
        raise RuntimeError("Exported GLB has no VRM extension")
    human_bones = vrm.get("humanoid", {}).get("humanBones", {})
    humanoid_count = len(human_bones) if isinstance(human_bones, (dict, list)) else 0
    skin_bones = max((len(skin.get("joints", [])) for skin in document.get("skins", [])), default=0)
    morph_targets = sum(
        len(primitive.get("targets", []))
        for mesh in document.get("meshes", [])
        for primitive in mesh.get("primitives", [])
    )
    meta = vrm.get("meta", {})
    author = meta.get("author") or meta.get("authors", [])
    license_name = meta.get("licenseName") or meta.get("license")
    license_url = meta.get("otherLicenseUrl") or meta.get("other_license_url")
    if len(document.get("meshes", [])) != len(mesh_signature) or skin_bones < len(armature.data.bones):
        raise RuntimeError("Exported VRM mesh or skeleton structure is incomplete")
    if humanoid_count < 50 or morph_targets < 50:
        raise RuntimeError("Exported humanoid mapping or face morph targets are incomplete")
    if any('Glove' in mesh['name'] for mesh in document['meshes']):
        raise RuntimeError('Owner-requested bare hands did not survive export')
    secondary=vrm.get('secondaryAnimation',{})
    hair_springs=next(g for g in secondary.get('boneGroups',[]) if g.get('comment')=='Reference layered hair')
    if len(hair_springs['bones'])!=13 or len(hair_springs['colliderGroups'])!=2:
        raise RuntimeError('Native hair chains/collider references did not survive export')
    if any(len(g.get('colliders',[]))!=3 for g in secondary.get('colliderGroups',[])):
        raise RuntimeError('Expected interior head/upper-body collider proxies')
    if author != "VRoid" or license_name != "Other" or license_url != LICENSE_URL:
        raise RuntimeError("VRoid author/license attribution did not survive export")
    flat_material_indices = [i for i, m in enumerate(document.get('materials', []))
                             if m.get('name', '').startswith('Jawlie ') or 'HAIR' in m.get('name', '')]
    material_properties = vrm.get('materialProperties', [])
    for index in flat_material_indices:
        material = document['materials'][index]
        if material.get('pbrMetallicRoughness', {}).get('baseColorTexture') or material.get('normalTexture'):
            raise RuntimeError('Flat material retained an inherited texture: ' + material['name'])
        if index < len(material_properties) and material_properties[index].get('textureProperties'):
            raise RuntimeError('MToon flat material retained a texture: ' + material['name'])
    print('FLAT_MATERIAL_EXPORT_CHECK', len(flat_material_indices), 'texture-free materials')
    print("VROID_REFERENCE_SMOKE_OK", OUTPUT, OUTPUT.stat().st_size,
          "meshes", len(document["meshes"]), "skeleton", skin_bones,
          "humanoid", humanoid_count, "morph_targets", morph_targets,
          "blend", EDITABLE)


if __name__ == "__main__":
    main()
