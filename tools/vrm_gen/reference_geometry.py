"""Topology-following clothing and secondary bones for the VRM reference."""

import bmesh
import bpy
from math import cos, pi, sin
from mathutils import Vector


HELPERS = {
    "jawlie_soft_chest_l": ("J_Bip_C_UpperChest", (0.105, 0.005, 1.16), (0.105, -0.005, 1.08)),
    "jawlie_soft_chest_r": ("J_Bip_C_UpperChest", (-0.105, 0.005, 1.16), (-0.105, -0.005, 1.08)),
    "jawlie_soft_hip_l": ("J_Bip_C_Hips", (0.105, 0.0, 0.91), (0.105, 0.0, 0.82)),
    "jawlie_soft_hip_r": ("J_Bip_C_Hips", (-0.105, 0.0, 0.91), (-0.105, 0.0, 0.82)),
    "jawlie_cloth_hem_l": ("J_Bip_C_Spine", (0.14, 0.0, 1.01), (0.14, 0.0, 0.94)),
    "jawlie_cloth_hem_r": ("J_Bip_C_Spine", (-0.14, 0.0, 1.01), (-0.14, 0.0, 0.94)),
}


def add_soft_helper_bones(armature):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (parent_name, head, tail) in HELPERS.items():
        bone = armature.data.edit_bones.get(name) or armature.data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        bone.parent = armature.data.edit_bones[parent_name]
        bone.use_deform = True
        bone.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")


def _weights(body, vertex_index):
    return [(group.name, membership.weight) for membership in body.data.vertices[vertex_index].groups
            for group in [body.vertex_groups[membership.group]]]


def _add_soft_weights(body, top_index, bottom_index):
    groups = {name: body.vertex_groups.get(name) or body.vertex_groups.new(name=name) for name in HELPERS}
    vertex_materials = [set() for _ in body.data.vertices]
    for face in body.data.polygons:
        for index in face.vertices:
            vertex_materials[index].add(face.material_index)
    for vertex in body.data.vertices:
        x, _y, z = vertex.co
        regions = {}
        if top_index in vertex_materials[vertex.index]:
            regions.update({
                "jawlie_soft_chest_l": max(0.0, 1.0 - abs(x - 0.105) / 0.12) * max(0.0, 1.0 - abs(z - 1.11) / 0.13),
                "jawlie_soft_chest_r": max(0.0, 1.0 - abs(x + 0.105) / 0.12) * max(0.0, 1.0 - abs(z - 1.11) / 0.13),
                "jawlie_cloth_hem_l": max(0.0, 1.0 - abs(x - 0.14) / 0.13) * max(0.0, 1.0 - abs(z - 0.97) / 0.07),
                "jawlie_cloth_hem_r": max(0.0, 1.0 - abs(x + 0.14) / 0.13) * max(0.0, 1.0 - abs(z - 0.97) / 0.07),
            })
        elif bottom_index in vertex_materials[vertex.index]:
            regions.update({
                "jawlie_soft_hip_l": max(0.0, 1.0 - abs(x - 0.10) / 0.16) * max(0.0, 1.0 - abs(z - 0.86) / 0.12),
                "jawlie_soft_hip_r": max(0.0, 1.0 - abs(x + 0.10) / 0.16) * max(0.0, 1.0 - abs(z - 0.86) / 0.12),
            })
        if not regions:
            continue
        name, strength = max(regions.items(), key=lambda item: item[1])
        if strength < 0.03:
            continue
        weight = min(0.26, 0.10 + 0.16 * strength)
        for old_name, old_weight in _weights(body, vertex.index):
            if old_name not in HELPERS and old_weight > 0:
                body.vertex_groups[old_name].add([vertex.index], old_weight * (1.0 - weight), "REPLACE")
        groups[name].add([vertex.index], weight, "REPLACE")


def _face_center(mesh, face):
    return sum((mesh.vertices[i].co for i in face.vertices), Vector()) / len(face.vertices)


def _new_mesh(name, vertices, faces, materials, armature, body=None, weights=None, thickness=0.0):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    for material in materials:
        if material is not None:
            mesh.materials.append(material)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    if body:
        for group in body.vertex_groups:
            obj.vertex_groups.new(name=group.name)
        for new_index, old_index in enumerate(weights):
            for group_name, value in _weights(body, old_index):
                if value > 0:
                    obj.vertex_groups[group_name].add([new_index], value, "REPLACE")
    elif weights:
        for name, values in weights.items():
            group = obj.vertex_groups.new(name=name)
            for index, value in values:
                if value > 0:
                    group.add([index], value, "REPLACE")
    modifier = obj.modifiers.new(name + " Armature", "ARMATURE")
    modifier.object = armature
    if thickness:
        solid = obj.modifiers.new(name + " Cloth Thickness", "SOLIDIFY")
        solid.thickness, solid.offset = thickness, 0.0
    return obj


def _copy_cloth_surface(body, faces, name, material, armature, *, center_cut=False, bomber=False):
    used = sorted({index for face in faces for index in face.vertices})
    remap = {old: new for new, old in enumerate(used)}
    verts = []
    for old in used:
        co = body.data.vertices[old].co.copy()
        x, y, z = co
        # Crop the long hoodie body into a ribbed waist length while preserving its shoulders/sleeves.
        torso = max(0.0, min(1.0, (0.34 - abs(x)) / 0.10)) if bomber else 0.0
        lift = min(0.145, max(0.0, 0.965 - z) * 0.92) * torso
        co.z += lift
        co += body.data.vertices[old].normal * 0.008
        verts.append(co)
    polygons = [tuple(remap[i] for i in face.vertices) for face in faces]
    obj = _new_mesh(name, verts, polygons, [material], armature, body, used, thickness=0.006)
    return obj


def _garment_weights(z, side, helpers=True):
    upper = max(0.0, min(1.0, (z - 0.47) / 0.08))
    weights = {
        ("J_Bip_L_UpperLeg" if side > 0 else "J_Bip_R_UpperLeg"): upper,
        ("J_Bip_L_LowerLeg" if side > 0 else "J_Bip_R_LowerLeg"): 1.0 - upper,
    }
    if helpers and z > 0.77:
        hip_name = "jawlie_soft_hip_l" if side > 0 else "jawlie_soft_hip_r"
        influence = min(0.24, 0.10 + (z - 0.77) * 0.65)
        weights = {name: value * (1.0 - influence) for name, value in weights.items()}
        weights[hip_name] = influence
    return weights


def _make_leg_mesh(name, rows, material, armature, side, *, stripe=None, pocket=None):
    segments = 24
    verts, faces, weights = [], [], {}
    for z, rx, ry, center_x in rows:
        for j in range(segments):
            angle = 2 * pi * j / segments
            index = len(verts)
            verts.append((side * center_x + rx * cos(angle), -0.004 + ry * sin(angle), z))
            for bone, value in _garment_weights(z, side).items():
                weights.setdefault(bone, []).append((index, value))
    for ring in range(len(rows) - 1):
        for j in range(segments):
            a = ring * segments + j
            b = ring * segments + (j + 1) % segments
            faces.append((a, b, b + segments, a + segments))
    obj = _new_mesh(name, verts, faces, [material, stripe, pocket], armature, weights=weights, thickness=0.0)
    for poly in obj.data.polygons:
        indices = [i for i in poly.vertices]
        z = sum(obj.data.vertices[i].co.z for i in indices) / len(indices)
        x = sum(obj.data.vertices[i].co.x for i in indices) / len(indices) * side
        y = sum(obj.data.vertices[i].co.y for i in indices) / len(indices)
        if side > 0 and stripe and 0.54 <= z <= 0.585 and x > 0.07 and y < -0.015:
            poly.material_index = 1
        elif side > 0 and pocket and 0.63 <= z <= 0.73 and x > 0.09 and y < 0.015:
            poly.material_index = 2
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def _make_boots(armature, material, sole_material):
    objects = []
    for side in (-1, 1):
        rows = [
            (0.075, 0.043, 0.049, 0.039), (0.09, 0.043, 0.049, 0.039),
            (0.13, 0.042, 0.048, 0.039), (0.18, 0.040, 0.047, 0.039),
            (0.22, 0.040, 0.047, 0.039), (0.235, 0.040, 0.047, 0.039),
        ]
        boots = _make_leg_mesh("JawlieHighTopBoot_L" if side > 0 else "JawlieHighTopBoot_R",
                               rows, material, armature, side)
        objects.append(boots)
    # The VRoid foot shell keeps its authored silhouette; its sole faces use the mint sole material.
    return objects


def _make_mint_zipper(armature, material):
    vertices, faces, weights = [], [], {}
    for side in (-1, 1):
        first = len(vertices)
        for step in range(17):
            t = step / 16
            z = 0.965 + 0.365 * t
            x = side * (0.12 - 0.025 * t)
            for dx in (-0.0035, 0.0035):
                vertices.append((x + dx, -0.132, z))
                index = len(vertices) - 1
                chest_weight = max(0.0, min(1.0, (z - 1.12) / 0.10))
                for name, value in (("J_Bip_C_Chest", 1.0 - chest_weight), ("J_Bip_C_UpperChest", chest_weight)):
                    if value:
                        weights.setdefault(name, []).append((index, value))
                if z < 1.02:
                    helper = "jawlie_cloth_hem_l" if side > 0 else "jawlie_cloth_hem_r"
                    weights.setdefault(helper, []).append((index, 0.16))
        for step in range(16):
            a = first + step * 2
            faces.append((a, a + 1, a + 3, a + 2))
    return _new_mesh("JawlieMintBomberZipper", vertices, faces, [material], armature, weights=weights)


def _remove_faces_by_material(body, material_index):
    bm = bmesh.new()
    bm.from_mesh(body.data)
    doomed = [face for face in bm.faces if face.material_index == material_index]
    bmesh.ops.delete(bm, geom=doomed, context="FACES_ONLY")
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()


def _remove_native_cloth_springs(armature):
    groups = armature.data.vrm_addon_extension.vrm0.secondary_animation.bone_groups
    for index in reversed(range(len(groups))):
        if groups[index].comment in {"Hood", "HoodString"}:
            groups.remove(index)


def _stabilize_native_hair_springs(armature):
    groups = armature.data.vrm_addon_extension.vrm0.secondary_animation.bone_groups
    adjusted = 0
    for group in groups:
        if group.comment:
            continue
        group.hit_radius = min(group.hit_radius, 0.04)
        group.stiffiness = max(group.stiffiness, 0.90)
        group.drag_force = max(group.drag_force, 0.88)
        group.gravity_power = 0.0
        adjusted += 1
    if adjusted < 6:
        raise RuntimeError(f"Expected native VRoid hair spring chains, found {adjusted}")
    print("NATIVE_HAIR_SPRINGS_STABILIZED", adjusted)


def style_hair_part(hair):
    changed = 0
    for vertex in hair.data.vertices:
        co = vertex.co
        # Sweep the right forehead curtain toward the side part without touching face/morph geometry.
        if co.y < -0.025 and 1.34 < co.z < 1.51 and co.x > -0.12:
            mask = max(0.0, min(1.0, (co.x + 0.12) / 0.18)) * max(0.0, min(1.0, (1.51 - co.z) / 0.12))
            co.x += 0.045 * mask
            co.z -= 0.014 * mask
            changed += bool(mask)
    hair.data.update()
    print("SIDE_PART_HAIR_VERTICES", changed)


def build_reference_garments(body, armature, materials):
    """Build an open jacket/shirt shell, fitted trouser legs, and one glove."""
    tops_index = next(i for i, mat in enumerate(body.data.materials) if "Tops" in mat.name)
    bottoms_index = next(i for i, mat in enumerate(body.data.materials) if "Bottoms" in mat.name)
    skin_index = next(i for i, mat in enumerate(body.data.materials) if "Body_00_SKIN" in mat.name)
    shoes_index = next(i for i, mat in enumerate(body.data.materials) if "Shoes" in mat.name)
    _add_soft_weights(body, tops_index, bottoms_index)

    top_faces = [face for face in body.data.polygons if face.material_index == tops_index]
    shirt_faces, jacket_faces, glove_faces = [], [], []
    for face in top_faces:
        center = _face_center(body.data, face)
        if abs(center.x) < 0.13 and center.y < 0.015 and 0.98 < center.z < 1.27:
            shirt_faces.append(face)
        elif center.z > 1.27 and abs(center.x) < 0.28:
            # The sample hood occupies this neck-height island; omit it and its native spring chain.
            continue
        elif abs(center.x) < 0.10 and 1.02 < center.z < 1.22 and center.y < -0.035:
            # Remove the molded hoodie cords and toggles from the open shirt placket.
            continue
        elif abs(center.x) < 0.13 and center.y < 0.015 and 0.98 < center.z < 1.27:
            # Leave a real open front instead of laying the bomber over its crew shirt.
            continue
        else:
            jacket_faces.append(face)
    shirt_faces = []
    for face in body.data.polygons:
        if face.material_index != skin_index:
            continue
        center = _face_center(body.data, face)
        if abs(center.x) < 0.13 and center.y < -0.02 and 0.98 < center.z < 1.27:
            shirt_faces.append(face)
        elif 0.43 < center.x < 0.59 and 1.17 < center.z < 1.27:
            glove_faces.append(face)
    if min(len(jacket_faces), len(shirt_faces), len(glove_faces)) < 30:
        raise RuntimeError(f"Source clothing regions are incomplete: jacket={len(jacket_faces)} shirt={len(shirt_faces)} glove={len(glove_faces)}")

    jacket = _copy_cloth_surface(body, jacket_faces, "JawlieOpenBomber", materials["jacket"], armature, bomber=True)
    shirt = _copy_cloth_surface(body, shirt_faces, "JawlieCrewShirt", materials["shirt"], armature, bomber=True)
    glove = _copy_cloth_surface(body, glove_faces, "JawlieFingerlessGlove", materials["glove"], armature)
    _remove_faces_by_material(body, tops_index)

    # Reuse the licensed body surface for the fitted trouser yoke; remove the source shorts by material.
    yoke_faces = []
    for face in body.data.polygons:
        if face.material_index != skin_index:
            continue
        center = _face_center(body.data, face)
        if 0.75 < center.z < 0.965 and abs(center.x) < 0.23:
            yoke_faces.append(face)
    yoke = _copy_cloth_surface(body, yoke_faces, "JawlieCargoYoke", materials["pants"], armature)
    _remove_faces_by_material(body, bottoms_index)
    sole_index = len(body.data.materials)
    body.data.materials.append(materials["sole"])
    for face in body.data.polygons:
        center = _face_center(body.data, face)
        if face.material_index == shoes_index and center.z < 0.014:
            face.material_index = sole_index

    trouser_rows = [
        (0.205, 0.038, 0.046, 0.039), (0.23, 0.040, 0.048, 0.039),
        (0.29, 0.043, 0.055, 0.040), (0.36, 0.046, 0.060, 0.042),
        (0.43, 0.049, 0.064, 0.045), (0.49, 0.052, 0.068, 0.048),
        (0.54, 0.056, 0.074, 0.051), (0.60, 0.061, 0.079, 0.055),
        (0.68, 0.067, 0.084, 0.059), (0.75, 0.073, 0.091, 0.064),
        (0.82, 0.078, 0.096, 0.067),
    ]
    legs = []
    for side in (-1, 1):
        legs.append(_make_leg_mesh("JawlieCargoTrousers_R" if side < 0 else "JawlieCargoTrousers_L",
                                   trouser_rows, materials["pants"], armature, side,
                                   stripe=materials["mint"], pocket=materials["cargo"]))
    boots = _make_boots(armature, materials["boots"], materials["sole"])
    zipper = _make_mint_zipper(armature, materials["mint"])
    _remove_native_cloth_springs(armature)
    _stabilize_native_hair_springs(armature)
    print("REFERENCE_GARMENT_FACE_COUNTS", {"jacket": len(jacket_faces), "shirt": len(shirt_faces),
          "glove": len(glove_faces), "trouser_legs": sum(len(obj.data.polygons) for obj in legs),
          "boots": sum(len(obj.data.polygons) for obj in boots)})
    return [jacket, shirt, glove, yoke, *legs, *boots, zipper]
