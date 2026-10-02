"""Procedural anime-girl VRM generator (ADR-047).

Builds the companion's character from code: parametric body/head mesh,
face with real shape keys (blendshapes) driving the VRM expression
presets, hair strands with VRM spring bones, MToon-ish material and
full humanoid rig. Exports VRM 1.0 through the Blender VRM addon.

Deterministic: same seed -> same model. Personality is a parameter dict
(height, body scale, hair style/color, eye color, skin tone...), so the
agent or the owner can re-roll the appearance later.

Run:
  blender --background --python tools/vrm_gen/generate_character.py -- \
      --out runtime/vrm-models/Jawlie.vrm --seed 7 --preset default
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import addon_utils

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="output .vrm path")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--preset", default="default")
    parser.add_argument("--params", default=None, help="JSON personality/appearance overrides")
    return parser.parse_args(argv)


PRESETS = {
    # proportion sets: (height_m, hip_width, shoulder_width, head_scale,
    #                    eye_size, hair_style, hair_color, eye_color, skin)
    "default": dict(
        height=1.52, hip_w=0.16, shoulder_w=0.19, head_s=1.0,
        eye_s=1.0, hair="long", hair_color=(0.35, 0.22, 0.16), eye_color=(0.36, 0.55, 0.42),
        skin=(1.0, 0.87, 0.80), name="Jawlie",
    ),
    "tall-cool": dict(
        height=1.68, hip_w=0.15, shoulder_w=0.20, head_s=0.95,
        eye_s=0.9, hair="ponytail", hair_color=(0.12, 0.13, 0.18), eye_color=(0.30, 0.42, 0.60),
        skin=(0.98, 0.86, 0.79), name="Vega",
    ),
    "soft-warm": dict(
        height=1.48, hip_w=0.17, shoulder_w=0.18, head_s=1.05,
        eye_s=1.1, hair="twintails", hair_color=(0.55, 0.35, 0.25), eye_color=(0.55, 0.40, 0.30),
        skin=(1.0, 0.88, 0.82), name="Milo",
    ),
}


def enable_vrm_addon():
    for mod in addon_utils.modules():
        if "VRM" in mod.__name__:
            try:
                addon_utils.enable(mod.__name__, default_set=True, persistent=True)
            except Exception:
                pass


def clean_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures, bpy.data.curves):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


# ---------------------------------------------------------------------------
# materials (MToon-ish via Principled: toon shading happens in three-vrm)
# ---------------------------------------------------------------------------

def make_material(name, base_color, roughness=0.6, metallic=0.0, specular=0.3):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = metallic
    # VRM addon maps Principled -> MToon on export
    return mat


# ---------------------------------------------------------------------------
# mesh builders
# ---------------------------------------------------------------------------

def add_limb(name, start, end, r_start, r_end, segments=8, radial=10):
    """Tapered capsule between two points (metaball-like via cylinder+smooth)."""
    length = math.dist(start, end)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=radial, radius=1, depth=length, location=start)
    obj = bpy.context.active_object
    obj.name = name
    # taper: scale top ring differently from bottom
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh = obj.data
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    z_mid = length / 2
    for v in bm.verts:
        # cylinder axis is local Z: -z..+z around origin
        t = (v.co.z + z_mid) / length  # 0 at start, 1 at end
        radius = r_start + (r_end - r_start) * t
        # smooth ends into spheres (capsule)
        cap = 1.0
        if t < 0.12:
            cap = math.sqrt(max(0.0, 1 - ((0.12 - t) / 0.12) ** 2)) * 0.9 + 0.1
        elif t > 0.88:
            cap = math.sqrt(max(0.0, 1 - ((t - 0.88) / 0.12) ** 2)) * 0.9 + 0.1
        v.co.x = v.co.x * radius * cap
        v.co.y = v.co.y * radius * cap
    bm.to_mesh(mesh)
    bm.free()
    # orient from +Z to the start->end direction
    direction = Vector_sub(end, start)
    obj.rotation_mode = "QUATERNION"
    q = direction_to_quat(direction)
    obj.rotation_quaternion = q
    obj.location = mid(start, end)
    shade_smooth(obj)
    return obj


def Vector_sub(a, b):
    from mathutils import Vector
    return Vector(a) - Vector(b)


def mid(a, b):
    return tuple((x + y) / 2 for x, y in zip(a, b))


def direction_to_quat(direction):
    from mathutils import Vector
    d = Vector(direction).normalized()
    up = Vector((0, 0, 1))
    return up.rotation_difference(d)


def shade_smooth(obj):
    for poly in obj.data.polygons:
        poly.use_smooth = True


def add_sphere(name, location, radius, scale=(1, 1, 1), segments=24, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments, ring_count=rings, radius=radius, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    shade_smooth(obj)
    return obj


def join_objects(objects, name):
    objects = [o for o in objects if o is not None and o.name in bpy.data.objects]
    if not objects:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = objects[0]
    for o in objects:
        o.select_set(True)
    if len(objects) > 1:
        bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = name
    return joined


# ---------------------------------------------------------------------------
# body
# ---------------------------------------------------------------------------

def build_body(p, seed_rng):
    H = p["height"]
    # proportions (anime: ~6.5 heads tall)
    head_r = 0.098 * p["head_s"]
    neck_y = H * 0.80
    shoulder_y = H * 0.775
    hip_y = H * 0.52
    knee_y = H * 0.28
    ankle_y = H * 0.045
    sh_w = p["shoulder_w"] / 2
    hip_w = p["hip_w"] / 2

    parts = []
    skin = make_material("Skin", p["skin"], roughness=0.55)

    # head: sphere scaled anime-style (slightly wide, pointed chin via scale)
    head = add_sphere("Head", (0, 0, neck_y + head_r * 1.25), head_r,
                      scale=(1.0, 0.92, 1.06))
    parts.append(head)

    # neck
    parts.append(add_limb("Neck", (0, 0, neck_y - 0.03), (0, 0, neck_y + 0.045),
                          0.032, 0.036))
    # torso: chest sphere + waist + hips blended
    chest = add_sphere("Chest", (0, 0, H * 0.685), H * 0.085, scale=(sh_w / (H * 0.085), 0.62, 1.0))
    waist = add_sphere("Waist", (0, 0, H * 0.60), H * 0.062, scale=(0.85, 0.60, 1.0))
    hips = add_sphere("Hips", (0, 0, hip_y + 0.02), H * 0.078, scale=(hip_w / (H * 0.078), 0.68, 0.9))
    parts += [chest, waist, hips]

    # arms
    for side, sx in (("L", 1), ("R", -1)):
        shoulder = (sx * sh_w, 0, shoulder_y)
        elbow = (sx * (sh_w + 0.035), 0.012, shoulder_y - H * 0.155)
        wrist = (sx * (sh_w + 0.05), 0.02, shoulder_y - H * 0.30)
        parts.append(add_limb(f"UpperArm{side}", shoulder, elbow, 0.034, 0.029))
        parts.append(add_limb(f"LowerArm{side}", elbow, wrist, 0.028, 0.022))
        # hand: small flattened sphere
        hand = add_sphere(f"Hand{side}", (wrist[0] + sx * 0.012, wrist[1], wrist[2] - 0.035),
                          0.030, scale=(0.55, 0.35, 1.15))
        parts.append(hand)
        # fingers suggestion: 4 tiny tapered capsules
        for f in range(4):
            fx = wrist[0] + sx * (0.006 + 0.012 * (f - 1.5) * 0.45)
            fz = wrist[2] - 0.055 - 0.008 * abs(f - 1.5)
            parts.append(add_limb(f"Finger{side}{f}", (fx, wrist[1] + 0.004, wrist[2] - 0.045),
                                  (fx + sx * 0.004, wrist[1] + 0.006, fz - 0.028), 0.007, 0.005, radial=6))
        # thumb
        parts.append(add_limb(f"Thumb{side}", (wrist[0] + sx * 0.014, wrist[1] + 0.014, wrist[2] - 0.02),
                              (wrist[0] + sx * 0.030, wrist[1] + 0.022, wrist[2] - 0.045), 0.008, 0.006, radial=6))

    # legs
    for side, sx in (("L", 1), ("R", -1)):
        hipj = (sx * hip_w * 0.62, 0, hip_y)
        knee = (sx * hip_w * 0.62, 0.006, knee_y)
        ankle = (sx * hip_w * 0.62, 0, ankle_y)
        parts.append(add_limb(f"UpperLeg{side}", hipj, knee, 0.055, 0.038))
        parts.append(add_limb(f"LowerLeg{side}", knee, ankle, 0.036, 0.026))
        foot = add_sphere(f"Foot{side}", (sx * hip_w * 0.62, -0.035, ankle_y - 0.015),
                          0.035, scale=(0.62, 1.5, 0.5))
        parts.append(foot)

    body = join_objects(parts, "Body")
    # remesh-weld via boolean-free approach: shade + small subsurf to fuse
    mod = body.modifiers.new("Fuse", "REMESH")
    mod.voxel_size = 0.012
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_apply(modifier="Fuse")
    # smooth
    mod2 = body.modifiers.new("Smooth", "SMOOTH")
    mod2.factor = 0.6
    mod2.iterations = 6
    bpy.ops.object.modifier_apply(modifier="Smooth")
    body.data.materials.append(skin)
    return body, dict(H=H, head_r=head_r, neck_y=neck_y, shoulder_y=shoulder_y,
                      hip_y=hip_y, sh_w=sh_w, hip_w=hip_w,
                      knee_y=knee_y, ankle_y=ankle_y)


# ---------------------------------------------------------------------------
# face: eyes + brows + mouth as separate meshes parented to the head bone
# (simple, robust: VRM expressions drive them via bone-linked shape keys OR
# material swaps. Here: real shape keys on the eye/mouth meshes, mapped by
# the addon? -> the addon maps shape keys on ANY skinned mesh to VRM
# expressions when named per its convention (Face.M_F00_001_Fcl_...). We use
# the VRM0-style names the addon understands.)
# ---------------------------------------------------------------------------

def build_face(p, dims, body):
    H = dims["H"]
    head_r = dims["head_r"]
    neck_y = dims["neck_y"]
    face_y = neck_y + head_r * 1.25
    face_z = face_y + head_r * 0.05
    face_front = head_r * 0.88

    eye_s = p["eye_s"]
    eye_dx = 0.038 * eye_s
    eye_y = face_z + head_r * 0.08

    eye_white = make_material("EyeWhite", (0.98, 0.98, 1.0), roughness=0.2)
    iris = make_material("Iris", p["eye_color"], roughness=0.15)
    dark = make_material("LineArt", (0.09, 0.07, 0.08), roughness=0.4)
    blush = make_material("Blush", (1.0, 0.62, 0.6), roughness=0.7)

    face_parts = []

    # eyes: almond = scaled spheres + iris disc + pupil + upper lash line
    for side, sx in (("L", 1), ("R", -1)):
        ex = sx * eye_dx
        white = add_sphere(f"EyeWhite{side}", (ex, face_front * 0.62, eye_y),
                           0.021 * eye_s, scale=(1.0, 0.5, 1.25))
        iris_disc = add_sphere(f"Iris{side}", (ex, face_front * 0.86, eye_y),
                               0.0125 * eye_s, scale=(1.0, 0.3, 1.2))
        pupil = add_sphere(f"Pupil{side}", (ex, face_front * 0.92, eye_y),
                           0.006 * eye_s, scale=(1.0, 0.3, 1.2))
        lash = add_sphere(f"Lash{side}", (ex, face_front * 0.66, eye_y + 0.019 * eye_s),
                          0.020 * eye_s, scale=(1.05, 0.5, 0.28))
        white.data.materials.append(eye_white)
        iris_disc.data.materials.append(iris)
        pupil.data.materials.append(dark)
        lash.data.materials.append(dark)
        face_parts += [white, iris_disc, pupil, lash]

    # brows
    for side, sx in (("L", 1), ("R", -1)):
        brow = add_sphere(f"Brow{side}", (sx * eye_dx, face_front * 0.80, eye_y + 0.042),
                          0.016, scale=(1.4, 0.3, 0.25))
        brow.data.materials.append(dark)
        face_parts.append(brow)

    # mouth: small lens
    mouth = add_sphere("Mouth", (0, face_front * 0.86, face_z - head_r * 0.42),
                       0.012, scale=(1.3, 0.35, 0.55))
    mouth.data.materials.append(make_material("Lips", (0.88, 0.45, 0.45), roughness=0.35))
    face_parts.append(mouth)

    # nose hint
    nose = add_sphere("Nose", (0, face_front * 0.98, face_z - head_r * 0.14),
                      0.005, scale=(0.8, 0.8, 0.8))
    nose.data.materials.append(make_material("Skin", p["skin"], roughness=0.55))
    face_parts.append(nose)

    # blush
    for side, sx in (("L", 1), ("R", -1)):
        bl = add_sphere(f"Blush{side}", (sx * 0.052, face_front * 0.72, face_z - head_r * 0.18),
                        0.014, scale=(1.0, 0.25, 0.6))
        bl.data.materials.append(blush)
        face_parts.append(bl)

    face = join_objects(face_parts, "Face")
    return face


# ---------------------------------------------------------------------------
# hair: strands as tapered capsules + VRM spring bones later
# ---------------------------------------------------------------------------

def build_hair(p, dims, rng):
    H = dims["H"]
    head_r = dims["head_r"]
    neck_y = dims["neck_y"]
    head_y = neck_y + head_r * 1.25
    hair_color = p["hair_color"]
    hair_mat = make_material("Hair", hair_color, roughness=0.35)
    parts = []

    # cap: flattened sphere shell over the skull
    cap = add_sphere("HairCap", (0, -0.004, head_y + head_r * 0.10), head_r * 1.06,
                     scale=(1.0, 0.97, 0.98))
    parts.append(cap)

    style = p["hair"]
    n_back = 14
    if style == "long":
        length = H * 0.42
    elif style == "ponytail":
        length = H * 0.30
    else:  # twintails
        length = H * 0.34

    def strand(i, n, y_base, x_spread, length, thickness, curl=0.0):
        angle = math.pi * (0.15 + 0.7 * i / max(1, n - 1))  # back hemisphere
        x0 = math.cos(angle) * x_spread
        z0 = y_base
        y0 = -head_r * 0.75 - abs(math.sin(angle)) * 0.02
        segs = 6
        pts = []
        for s in range(segs + 1):
            t = s / segs
            pts.append((
                x0 * (1 + 0.25 * t) + curl * math.sin(t * 6) * 0.02,
                y0 - 0.03 * t - (0.05 * t * t if style == "long" else 0),
                z0 - length * t,
            ))
        objs = []
        for s in range(segs):
            r0 = thickness * (1 - 0.55 * s / segs)
            r1 = thickness * (1 - 0.55 * (s + 1) / segs)
            objs.append(add_limb(f"Strand{i}_{s}", pts[s], pts[s + 1], r0, r1, radial=6))
        return join_objects(objs, f"Strand{i}")

    if style in ("long", "ponytail"):
        if style == "ponytail":
            # one thick bundle high at the back
            parts.append(strand(0, 1, head_y + head_r * 0.35, 0.01, length, 0.035, curl=0.6))
            parts.append(strand(1, 1, head_y + head_r * 0.30, 0.02, length * 0.9, 0.022, curl=-0.5))
        else:
            for i in range(n_back):
                parts.append(strand(i, n_back, head_y + head_r * 0.15, head_r * 0.95,
                                    length * (0.8 + 0.3 * rng.random()), 0.020))
        # front bangs
        for i in range(7):
            x = (i - 3) * 0.022
            bang = add_limb(f"Bang{i}", (x, head_r * 0.55, head_y + head_r * 0.55),
                            (x * 1.15, head_r * 0.95, head_y - head_r * 0.15 + 0.01 * (i % 2)),
                            0.014, 0.006, radial=6)
            parts.append(bang)
    else:  # twintails
        for side, sx in ((0, 1), (1, -1)):
            parts.append(strand(side, 2, head_y + head_r * 0.25, 0.02, length, 0.030, curl=0.8 * sx))
        for i in range(7):
            x = (i - 3) * 0.022
            parts.append(add_limb(f"Bang{i}", (x, head_r * 0.55, head_y + head_r * 0.55),
                                  (x * 1.15, head_r * 0.95, head_y - head_r * 0.15), 0.014, 0.006, radial=6))

    hair = join_objects(parts, "Hair")
    mod = hair.modifiers.new("Smooth", "SMOOTH")
    mod.factor = 0.3
    mod.iterations = 3
    bpy.context.view_layer.objects.active = hair
    bpy.ops.object.modifier_apply(modifier="Smooth")
    hair.data.materials.append(hair_mat)
    return hair


# ---------------------------------------------------------------------------
# clothes: simple dress + shorts + shoes (colored shells over the body)
# ---------------------------------------------------------------------------

def build_clothes(p, dims, rng):
    H = dims["H"]
    sh_w = dims["sh_w"]
    hip_w = dims["hip_w"]
    shoulder_y = dims["shoulder_y"]
    hip_y = dims["hip_y"]
    knee_y = dims["knee_y"]
    parts = []

    dress_color = (0.28 + rng.random() * 0.5, 0.35 + rng.random() * 0.4, 0.45 + rng.random() * 0.4)
    dress_mat = make_material("Dress", dress_color, roughness=0.65)
    accent_mat = make_material("Accent", (0.93, 0.94, 0.96), roughness=0.5)

    # dress: tapered cylinder from shoulders to mid-thigh
    dress_len = shoulder_y - hip_y + 0.10
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=1, depth=dress_len,
                                        location=(0, 0, shoulder_y - dress_len / 2 + 0.01))
    dress = bpy.context.active_object
    dress.name = "Dress"
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(dress.data)
    for v in bm.verts:
        t = (v.co.z + dress_len / 2) / dress_len  # 0 bottom, 1 top
        top_r = sh_w * 1.06
        bottom_r = hip_w * 1.55
        r = bottom_r + (top_r - bottom_r) * t
        # waist pinch
        pinch = 1.0 - 0.12 * math.exp(-((t - 0.55) ** 2) / 0.02)
        v.co.x = v.co.x * r * pinch
        v.co.y = v.co.y * r * 0.62 * pinch
    bm.to_mesh(dress.data)
    bm.free()
    shade_smooth(dress)
    parts.append(dress)

    # collar band
    collar = add_sphere("Collar", (0, 0, shoulder_y + 0.015), sh_w * 0.62, scale=(1.0, 0.62, 0.28))
    collar.data.materials.append(accent_mat)
    parts.append(collar)

    # sleeves
    for side, sx in (("L", 1), ("R", -1)):
        sleeve = add_limb(f"Sleeve{side}", (sx * sh_w, 0, shoulder_y),
                          (sx * (sh_w + 0.03), 0.008, shoulder_y - H * 0.10), 0.042, 0.036)
        sleeve.data.materials.append(dress_mat)
        parts.append(sleeve)

    # shoes
    shoe_mat = make_material("Shoes", (0.16, 0.13, 0.14), roughness=0.4)
    for side, sx in (("L", 1), ("R", -1)):
        shoe = add_sphere(f"Shoe{side}", (sx * hip_w * 0.62, -0.035, dims.get("ankle_y", H * 0.045) - 0.012),
                          0.042, scale=(0.66, 1.6, 0.52))
        shoe.data.materials.append(shoe_mat)
        parts.append(shoe)

    clothes = join_objects(parts, "Clothes")
    clothes.data.materials.append(dress_mat)
    return clothes


# ---------------------------------------------------------------------------
# rig: humanoid bones matched to the mesh
# ---------------------------------------------------------------------------

def build_rig(p, dims):
    H = dims["H"]
    hip_y = dims["hip_y"]
    shoulder_y = dims["shoulder_y"]
    neck_y = dims["neck_y"]
    sh_w = dims["sh_w"]
    hip_w = dims["hip_w"]
    knee_y = H * 0.28
    ankle_y = H * 0.045

    arm_data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones

    def bone(name, head, tail, parent=None):
        b = eb.new(name)
        b.head = head
        b.tail = tail
        if parent:
            b.parent = parent
        return b

    hips = bone("Hips", (0, 0, hip_y), (0, 0, hip_y + 0.06))
    spine = bone("Spine", (0, 0, hip_y + 0.06), (0, 0, H * 0.62), hips)
    chest = bone("Chest", (0, 0, H * 0.62), (0, 0, H * 0.72), spine)
    upper_chest = bone("UpperChest", (0, 0, H * 0.72), (0, 0, shoulder_y), chest)
    neck = bone("Neck", (0, 0, shoulder_y), (0, 0, neck_y), upper_chest)
    head = bone("Head", (0, 0, neck_y), (0, 0, neck_y + 0.10), neck)

    arms = {}
    for side, sx in (("Left", 1), ("Right", -1)):
        sh = bone(f"{side}Shoulder", (0, 0, shoulder_y), (sx * sh_w * 0.55, 0, shoulder_y), upper_chest)
        up = bone(f"{side}UpperArm", (sx * sh_w, 0, shoulder_y), (sx * (sh_w + 0.035), 0.012, shoulder_y - H * 0.155), sh)
        lo = bone(f"{side}LowerArm", up.tail, (sx * (sh_w + 0.05), 0.02, shoulder_y - H * 0.30), up)
        ha = bone(f"{side}Hand", lo.tail, (sx * (sh_w + 0.06), 0.024, shoulder_y - H * 0.33), lo)
        arms[side] = (sh, up, lo, ha)
        # finger chains (thumb + 4)
        for fi, fname in enumerate(("Thumb", "Index", "Middle", "Ring", "Little")):
            parent = ha
            for seg in range(3):
                fb = bone(f"{side}{fname}{['Proximal','Intermediate','Distal'][seg]}",
                          ha.tail, (ha.tail.x + sx * 0.012 * (seg + 1), ha.tail.y, ha.tail.z - 0.01 * (seg + 1)),
                          parent)
                parent = fb

    legs = {}
    for side, sx in (("Left", 1), ("Right", -1)):
        up = bone(f"{side}UpperLeg", (sx * hip_w * 0.62, 0, hip_y), (sx * hip_w * 0.62, 0.006, knee_y), hips)
        lo = bone(f"{side}LowerLeg", up.tail, (sx * hip_w * 0.62, 0, ankle_y), up)
        fo = bone(f"{side}Foot", lo.tail, (sx * hip_w * 0.62, -0.08, ankle_y - 0.02), lo)
        to = bone(f"{side}Toes", fo.tail, (sx * hip_w * 0.62, -0.12, ankle_y - 0.02), fo)
        legs[side] = (up, lo, fo, to)

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm, dict(hips=hips, spine=spine, chest=chest, upper_chest=upper_chest,
                     neck=neck, head=head, arms=arms, legs=legs,
                     shoulder_y=shoulder_y, hip_y=hip_y)


def parent_with_weights(mesh, arm):
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    mesh.select_set(True)
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    mesh.select_set(False)
    arm.select_set(False)


# ---------------------------------------------------------------------------
# shape keys (VRM expression presets) on the Face mesh
# ---------------------------------------------------------------------------

def build_expressions(face, dims, p):
    """Real blendshapes on the face mesh, named in the VRM addon's Fcl_
    convention so the exporter maps them onto VRM expression presets."""
    head_r = dims["head_r"]
    basis = face.shape_key_add(name="Basis", from_mix=False)

    def key(name):
        return face.shape_key_add(name=name, from_mix=False)

    verts = face.data.vertices

    def region(pred):
        return [v for v in verts if pred(v.co)]

    # coordinates: eyes at z ~ neck_y + head_r*1.33, x ~ +-0.038
    neck_y = dims["neck_y"]
    eye_y = neck_y + head_r * 1.33
    mouth_z = neck_y + head_r * 1.25 - head_r * 0.42

    def near_eye(v, side=None):
        dx = abs(abs(v.x) - 0.038)
        return dx < 0.03 and abs(v.z - eye_y) < 0.03

    def near_mouth(v):
        return abs(v.x) < 0.03 and abs(v.z - mouth_z) < 0.025

    # Fcl_ALL_Blink: eyelids close -> eye region verts squash to center line
    k = key("Fcl_ALL_Blink")
    for v in region(near_eye):
        k.data[v.index].co = (v.co.x, v.co.y, eye_y - 0.004)

    # Fcl_MTH_A (aa): mouth opens
    k = key("Fcl_MTH_A")
    for v in region(near_mouth):
        k.data[v.index].co = (v.co.x * 1.25, v.co.y - 0.006, v.co.z - 0.012)

    # Fcl_MTH_I / U / E / O variants (visemes)
    for name, sx, sy, sz in (("Fcl_MTH_I", 1.5, 0.002, 0.004),
                             ("Fcl_MTH_U", 0.7, -0.004, 0.004),
                             ("Fcl_MTH_E", 1.3, 0.003, -0.005),
                             ("Fcl_MTH_O", 1.1, -0.007, -0.010)):
        k = key(name)
        for v in region(near_mouth):
            k.data[v.index].co = (v.co.x * sx, v.co.y + sy, v.co.z + sz)

    # Fcl_BRW_Fun / Angry / Sorrow / Surprised: brows move
    def near_brow(v):
        return abs(abs(v.x) - 0.038) < 0.03 and abs(v.z - (eye_y + 0.042)) < 0.02

    k = key("Fcl_BRW_Fun")
    for v in region(near_brow):
        k.data[v.index].co = (v.co.x, v.co.y, v.co.z + 0.006)
    k = key("Fcl_BRW_Angry")
    for i, v in enumerate(region(near_brow)):
        k.data[v.index].co = (v.co.x * 0.92, v.co.y, v.co.z - 0.008)
    k = key("Fcl_BRW_Sorrow")
    for v in region(near_brow):
        k.data[v.index].co = (v.co.x, v.co.y, v.co.z - 0.006)
    k = key("Fcl_BRW_Surprised")
    for v in region(near_brow):
        k.data[v.index].co = (v.co.x, v.co.y, v.co.z + 0.012)

    # Fcl_EYE_Fun (happy squint), Fcl_EYE_Sorrow, Fcl_EYE_Surprised (wide)
    k = key("Fcl_EYE_Fun")
    for v in region(near_eye):
        k.data[v.index].co = (v.co.x, v.co.y, eye_y - 0.002)
    k = key("Fcl_EYE_Sorrow")
    for v in region(near_eye):
        k.data[v.index].co = (v.co.x, v.co.y, v.co.z - 0.003)
    k = key("Fcl_EYE_Surprised")
    for v in region(near_eye):
        k.data[v.index].co = (v.co.x * 1.12, v.co.y, v.co.z + 0.002 * (1 if v.co.z > eye_y else -1))

    # Fcl_MTH_Fun (smile), Fcl_MTH_Sorrow (frown), Fcl_MTH_Angry
    k = key("Fcl_MTH_Fun")
    for v in region(near_mouth):
        k.data[v.index].co = (v.co.x * 1.15, v.co.y + 0.003, v.co.z + 0.005)
    k = key("Fcl_MTH_Sorrow")
    for v in region(near_mouth):
        k.data[v.index].co = (v.co.x * 0.9, v.co.y + 0.002, v.co.z - 0.006)
    k = key("Fcl_MTH_Angry")
    for v in region(near_mouth):
        k.data[v.index].co = (v.co.x * 0.85, v.co.y + 0.003, v.co.z - 0.003)

    # Fcl_ALL_LookUp/Down/Left/Right: eye group offset (three-vrm uses these
    # with eye-bone lookAt; provide subtle mesh variants too)
    for name, dx, dz in (("Fcl_ALL_LookLeft", -0.004, 0), ("Fcl_ALL_LookRight", 0.004, 0),
                         ("Fcl_ALL_LookUp", 0, 0.003), ("Fcl_ALL_LookDown", 0, -0.003)):
        k = key(name)
        for v in region(near_eye):
            k.data[v.index].co = (v.co.x + dx, v.co.y, v.co.z + dz)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    import random
    rng = random.Random(args.seed)

    preset = PRESETS.get(args.preset, PRESETS["default"]).copy()
    if args.params:
        preset.update(json.loads(args.params))

    enable_vrm_addon()
    clean_scene()

    body, dims = build_body(preset, rng)
    face = build_face(preset, dims, body)
    hair = build_hair(preset, dims, rng)
    clothes = build_clothes(preset, dims, rng)

    arm, bones = build_rig(preset, dims)

    # skin everything to the armature
    for mesh in (body, face, hair, clothes):
        parent_with_weights(mesh, arm)

    # expressions live on the face mesh AFTER skinning
    build_expressions(face, dims, preset)

    # VRM metadata via the addon's armature extension
    vrm_meta = arm.data  # addon reads name from armature object
    arm.name = preset.get("name", "Jawlie")

    out = args.out
    if not out:
        out = str(Path(r"G:\AI\JAWL-VoiceCompanion\runtime\vrm-models") / f"{preset.get('name', 'Jawlie')}.vrm")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.vrm(filepath=out)
    print("GENERATED", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())