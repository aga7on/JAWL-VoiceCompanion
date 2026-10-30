"""Read-only evaluated seam-coverage acceptance for Interface V9."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import bmesh
import bpy
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parents[2]
BLEND = ROOT / "runtime/character-reference/jawlie-interface-v9.blend"
MODEL = ROOT / "runtime/vrm-models/JawlieInterfaceV9.vrm"
REPORT_PATH = ROOT / "runtime/character-reference/interface-v9-joints.json"

# Maximum outward-ray travel before the covering garment must occlude a seam
# sample. The cuff uses a 2.3 mm reserve outside the source wrist section; the boot
# shaft is fitted 2.5 mm outside the trouser section. The margins allow for
# Solidify thickness and modest evaluated-pose movement, while rejecting a
# visible millimeter-scale uncovered arc.
WRIST_MAX_GAP_M = 0.005
ANKLE_MAX_GAP_M = 0.006
DIAGNOSTIC_RAY_CAP_M = 0.030
MIN_CONTACT_SAMPLES = 8


def evaluated_mesh(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh is None or len(mesh.vertices) == 0:
        if mesh is not None:
            evaluated.to_mesh_clear()
        raise RuntimeError(f"No evaluated surface for {obj.name}")
    mesh.calc_loop_triangles()
    points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    if not points or not triangles:
        evaluated.to_mesh_clear()
        raise RuntimeError(f"Evaluated surface has no triangles: {obj.name}")
    tree = BVHTree.FromPolygons(points, triangles, all_triangles=True)
    if tree is None:
        evaluated.to_mesh_clear()
        raise RuntimeError(f"Could not build evaluated surface tree: {obj.name}")
    return evaluated, mesh, points, tree


def assert_evaluated_topology_matches(obj, mesh):
    """Only index source seams when evaluated vertex/edge indices are stable."""
    source_edges = {tuple(sorted(edge.vertices)) for edge in obj.data.edges}
    evaluated_edges = {tuple(sorted(edge.vertices)) for edge in mesh.edges}
    if len(mesh.vertices) != len(obj.data.vertices) or evaluated_edges != source_edges:
        raise RuntimeError(
            f"Evaluated topology changed on {obj.name}; source seam indices cannot be reused safely"
        )


def armature_only_points(obj, rig, depsgraph, indices):
    """Evaluate seam vertices through the real rig while omitting shell topology modifiers."""
    states = [(modifier, modifier.show_viewport) for modifier in obj.modifiers]
    evaluated = None
    try:
        for modifier in obj.modifiers:
            modifier.show_viewport = modifier.type == "ARMATURE" and modifier.object == rig
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated, mesh, points, _tree = evaluated_mesh(obj, depsgraph)
        assert_evaluated_topology_matches(obj, mesh)
        if any(index < 0 or index >= len(points) for index in indices):
            raise RuntimeError(f"Seam vertex index is outside evaluated topology: {obj.name}")
        return {index: points[index] for index in indices}
    finally:
        if evaluated is not None:
            evaluated.to_mesh_clear()
        for modifier, state in states:
            modifier.show_viewport = state
        bpy.context.view_layer.update()


def boundary_indices(obj, axis, coordinate, side=None, material_index=None):
    """Find mesh boundary vertices at a seam on the undeformed source mesh."""
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        indices = set()
        for edge in bm.edges:
            if not edge.is_boundary:
                continue
            if material_index is not None and not any(
                face.material_index == material_index for face in edge.link_faces
            ):
                continue
            for vertex in edge.verts:
                point = vertex.co
                if abs(point[axis] - coordinate) > 0.0015:
                    continue
                if side is not None and point.x * side <= 0:
                    continue
                indices.add(vertex.index)
        return sorted(indices)
    finally:
        bm.free()


def section_edge_samples(obj, axis, coordinate, material_index, side):
    """Describe source skin-surface intersections with a fitted section plane."""
    edge_keys = set()
    for polygon in obj.data.polygons:
        if polygon.material_index != material_index:
            continue
        vertices = tuple(polygon.vertices)
        for offset, first in enumerate(vertices):
            second = vertices[(offset + 1) % len(vertices)]
            edge_keys.add(tuple(sorted((first, second))))
    records = []
    needed = set()
    for first, second in edge_keys:
        a, b = obj.data.vertices[first].co, obj.data.vertices[second].co
        if side * a[0] <= 0 or side * b[0] <= 0:
            continue
        da, db = a[axis] - coordinate, b[axis] - coordinate
        if abs(da) <= 1e-6:
            records.append((first, first, 0.0)); needed.add(first)
        if abs(db) <= 1e-6:
            records.append((second, second, 0.0)); needed.add(second)
        if da * db < 0:
            factor = -da / (db - da)
            records.append((first, second, factor)); needed.update((first, second))
    if len(records) < MIN_CONTACT_SAMPLES:
        raise RuntimeError(
            f"{obj.name} section at {coordinate:.3f} has only {len(records)} samples"
        )
    return records, needed


def interpolate_section(records, evaluated_points):
    samples = []
    seen = set()
    for first, second, factor in records:
        point = evaluated_points[first].lerp(evaluated_points[second], factor)
        key = tuple(round(component, 6) for component in point)
        if key not in seen:
            seen.add(key)
            samples.append(point)
    return samples


def section_report(obj, axis, coordinate, side, material_index=None):
    points = []
    for polygon in obj.data.polygons:
        if material_index is not None and polygon.material_index != material_index:
            continue
        vertices = tuple(polygon.vertices)
        for offset, first in enumerate(vertices):
            second = vertices[(offset + 1) % len(vertices)]
            p, q = obj.data.vertices[first].co, obj.data.vertices[second].co
            if side is not None and (p.x + q.x) * side <= 0:
                continue
            dp, dq = p[axis] - coordinate, q[axis] - coordinate
            if abs(dp) <= 1e-6 and abs(dq) <= 1e-6:
                points.extend((p.copy(), q.copy()))
            elif abs(dp) <= 1e-6:
                points.append(p.copy())
            elif abs(dq) <= 1e-6:
                points.append(q.copy())
            elif dp * dq < 0:
                points.append(p.lerp(q, -dp / (dq - dp)))
    unique = {}
    for point in points:
        unique[tuple(round(float(value), 6) for value in point)] = point
    points = list(unique.values())
    if len(points) < MIN_CONTACT_SAMPLES:
        return {
            "status": "unavailable",
            "axis": "xyz"[axis],
            "coordinate_m": coordinate,
            "sample_vertices": len(points),
            "reason": "fewer than 8 source contour samples at this exact plane",
        }
    other = [i for i in range(3) if i != axis]
    low = [min(point[i] for point in points) for i in other]
    high = [max(point[i] for point in points) for i in other]
    center = [(a + b) / 2 for a, b in zip(low, high)]
    radii = [(b - a) / 2 for a, b in zip(low, high)]
    return {
        "status": "measured",
        "axis": "xyz"[axis],
        "coordinate_m": coordinate,
        "sample_vertices": len(points),
        "center_other_axes_m": [float(value) for value in center],
        "radii_other_axes_m": [float(value) for value in radii],
    }


def distance_summary(label, sample_points, target_tree, max_gap):
    distances = []
    for point in sample_points:
        nearest = target_tree.find_nearest(point)
        if nearest is None:
            raise RuntimeError(f"No nearest point found for {label}")
        distances.append(float(nearest[3]))
    distances.sort()
    count = len(distances)
    p95 = distances[min(count - 1, math.ceil(0.95 * count) - 1)]
    result = {
        "samples": count,
        "nearest_distance_max_m": max(distances),
        "nearest_distance_p95_m": p95,
        "max_gap_threshold_m": max_gap,
        "status": "passed" if max(distances) <= max_gap else "failed",
    }
    return result


def radial_occlusion_summary(label, sample_points, target_tree, max_ray, plane_axes,
                             include_samples=False):
    """Cast outward from the seam loop; every ray must meet its garment shell."""
    center = Vector((0.0, 0.0, 0.0))
    for axis in plane_axes:
        low = min(point[axis] for point in sample_points)
        high = max(point[axis] for point in sample_points)
        center[axis] = (low + high) / 2
    distances = []
    sample_diagnostics = []
    signed_bins = {}
    for axis in plane_axes:
        label_axis = "xyz"[axis]
        for sign in ("-", "+"):
            signed_bins[label_axis + sign] = {"samples": 0, "within_threshold": 0,
                                              "over_threshold": 0, "no_hit_within_0_03m": 0}
    angles = []
    for point in sample_points:
        direction = Vector((0.0, 0.0, 0.0))
        for axis in plane_axes:
            direction[axis] = point[axis] - center[axis]
        if direction.length < 1e-8:
            sample_diagnostics.append({"xyz_m": [float(value) for value in point],
                                       "ray_hit_m": None, "result": "degenerate_direction"})
            continue
        direction.normalize()
        angles.append(math.atan2(direction[plane_axes[1]], direction[plane_axes[0]]) % (2 * math.pi))
        dominant_axis = max(plane_axes, key=lambda axis: abs(direction[axis]))
        sign = "+" if direction[dominant_axis] >= 0 else "-"
        bin_key = "xyz"[dominant_axis] + sign
        bin_metrics = signed_bins[bin_key]
        bin_metrics["samples"] += 1
        origin = point + direction * 0.00005
        hit = target_tree.ray_cast(origin, direction, DIAGNOSTIC_RAY_CAP_M)
        if hit is None or hit[0] is None:
            bin_metrics["no_hit_within_0_03m"] += 1
            sample_diagnostics.append({"xyz_m": [float(value) for value in point],
                                       "radial_direction_in_plane": {
                                           "xyz"[axis]: float(direction[axis]) for axis in plane_axes
                                       },
                                       "ray_hit_m": None, "result": "no_hit_within_0.03m"})
            continue
        distance = float((hit[0] - origin).length)
        distances.append(distance)
        result_name = "within_threshold" if distance <= max_ray else "over_threshold"
        bin_metrics[result_name] += 1
        sample_diagnostics.append({"xyz_m": [float(value) for value in point],
                                   "radial_direction_in_plane": {
                                       "xyz"[axis]: float(direction[axis]) for axis in plane_axes
                                   },
                                   "ray_hit_m": distance,
                                   "result": result_name})
    count = len(sample_points)
    hits = len(distances)
    within = sum(distance <= max_ray for distance in distances)
    over = hits - within
    no_hit = count - hits
    worst = max(distances) if distances else None
    distances.sort()
    p95 = distances[min(hits - 1, math.ceil(0.95 * hits) - 1)] if hits else None
    passed = within == count
    angles.sort()
    angular_gaps = [angles[index + 1] - angles[index] for index in range(len(angles) - 1)]
    if angles:
        angular_gaps.append(angles[0] + 2 * math.pi - angles[-1])
    max_angular_gap = math.degrees(max(angular_gaps)) if angular_gaps else None
    result = {
        "samples": count,
        "within_threshold_samples": within,
        "over_threshold_samples_with_hit_within_0_03m": over,
        "no_hit_within_0_03m_samples": no_hit,
        "outward_ray_max_hit_m_within_0_03m_cap": worst,
        "outward_ray_p95_hit_m_within_0_03m_cap": p95,
        "max_gap_threshold_m": max_ray,
        "diagnostic_ray_cap_m": DIAGNOSTIC_RAY_CAP_M,
        "coverage_fraction_within_threshold": within / count if count else 0.0,
        "radial_center_m": [float(center[axis]) for axis in plane_axes],
        "max_angular_sample_gap_deg": max_angular_gap,
        "signed_dominant_axis_coverage": signed_bins,
        "status": "passed" if passed else "failed",
        "criterion": "every sampled seam vertex ray is occluded by the evaluated garment shell within the threshold; this discrete check does not certify points between samples",
    }
    if include_samples:
        result["sample_diagnostics"] = sample_diagnostics
    return result


def require_armature_modifier(obj, rig):
    modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE"]
    if not any(modifier.object == rig and modifier.show_viewport for modifier in modifiers):
        raise RuntimeError(f"{obj.name} has no enabled Armature modifier for {rig.name}")


def pose_local_axis(bone, world_axis):
    # Convert the tested global limb axis into this bone's local rest frame.
    local = bone.bone.matrix_local.to_quaternion().inverted() @ Vector(world_axis)
    if local.length < 1e-8:
        raise RuntimeError(f"Degenerate local pose axis for {bone.name}")
    return local.normalized()


def seam_check(seam_obj, target_obj, seam_points, target_tree,
               label, max_gap, plane_axes, include_samples=False):
    unique_points = {}
    for point in seam_points:
        unique_points[tuple(round(float(value), 6) for value in point)] = point
    seam_points = list(unique_points.values())
    if len(seam_points) < MIN_CONTACT_SAMPLES:
        raise RuntimeError(
            f"{label}: only {len(seam_points)} boundary samples; "
            f"need at least {MIN_CONTACT_SAMPLES}"
        )
    result = radial_occlusion_summary(label, seam_points, target_tree, max_gap,
                                      plane_axes, include_samples=include_samples)
    nearest = distance_summary(label, seam_points, target_tree, max_gap)
    result["seam_object"] = seam_obj.name
    result["covering_object"] = target_obj.name
    result["nearest_surface_diagnostic"] = {
        "max_m": nearest["nearest_distance_max_m"],
        "p95_m": nearest["nearest_distance_p95_m"],
    }
    return result


def render_evidence(rig, saved_bases):
    """Render one representative flex close-up per interface and side."""
    scene = bpy.context.scene
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        return {"status": "unavailable", "reason": "candidate scene has no active camera", "images": []}

    camera_state = (camera.location.copy(), camera.rotation_euler.copy(),
                    camera.data.type, camera.data.ortho_scale)
    render_state = (scene.render.filepath, scene.render.resolution_x,
                    scene.render.resolution_y, scene.render.resolution_percentage,
                    scene.render.image_settings.file_format, scene.render.use_file_extension)
    images = []
    try:
        scene.render.resolution_x = scene.render.resolution_y = 720
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.use_file_extension = True
        camera.data.type = "ORTHO"

        for side, side_name in ((1, "left"), (-1, "right")):
            for interface in ("wrist", "ankle"):
                for bone, basis, mode in saved_bases.values():
                    bone.matrix_basis = basis
                    bone.rotation_mode = mode
                if interface == "wrist":
                    bone_name = f"J_Bip_{'L' if side > 0 else 'R'}_Hand"
                    world_axis, angle = (0, 1, 0), 0.35
                    target = Vector((side * 0.548, 0.0, 1.245))
                    camera.location = Vector((side * 1.12, -0.25, 1.245))
                    camera.data.ortho_scale = 0.18
                    suffix = "flex-y-plus"
                else:
                    bone_name = f"J_Bip_{'L' if side > 0 else 'R'}_Foot"
                    world_axis, angle = (1, 0, 0), 0.40
                    target = Vector((side * 0.04, -0.005, 0.185))
                    camera.location = Vector((side * 0.04, -0.82, 0.22))
                    camera.data.ortho_scale = 0.085
                    suffix = "flex-x-plus"
                bone = rig.pose.bones.get(bone_name)
                if bone is None:
                    raise RuntimeError(f"Evidence pose bone is missing: {bone_name}")
                bone.rotation_mode = "QUATERNION"
                local_axis = pose_local_axis(bone, world_axis)
                bone.rotation_quaternion = Quaternion(local_axis, angle)
                bpy.context.view_layer.update()

                camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
                scene.render.filepath = str(
                    REPORT_PATH.parent / f"interface-v9-{interface}-{side_name}-{suffix}"
                )
                bpy.ops.render.render(write_still=True)
                image_path = REPORT_PATH.parent / f"interface-v9-{interface}-{side_name}-{suffix}.png"
                images.append(str(image_path.relative_to(ROOT)).replace("\\", "/"))
        return {"status": "rendered", "images": images}
    except Exception as exc:
        return {"status": "partial_or_unavailable", "images": images,
                "diagnostic": f"{type(exc).__name__}: {exc}"}
    finally:
        for bone, basis, mode in saved_bases.values():
            bone.matrix_basis = basis
            bone.rotation_mode = mode
        camera.location, camera.rotation_euler, camera.data.type, camera.data.ortho_scale = camera_state
        (scene.render.filepath, scene.render.resolution_x,
         scene.render.resolution_y, scene.render.resolution_percentage,
         scene.render.image_settings.file_format, scene.render.use_file_extension) = render_state
        bpy.context.view_layer.update()


def main():
    if not BLEND.is_file():
        raise FileNotFoundError(f"Required candidate blend is missing: {BLEND}")
    if not MODEL.is_file():
        raise FileNotFoundError(f"Required exported candidate is missing: {MODEL}")
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))

    report = {
        "run_id": uuid4().hex,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "profile": "blender_interface_v9_evaluated_seams",
        "model_title": "InterfaceV9",
        "weighting_scope": "Skin-only",
        "candidate_blend": str(BLEND.relative_to(ROOT)).replace("\\", "/"),
        "candidate_vrm": str(MODEL.relative_to(ROOT)).replace("\\", "/"),
        "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
        "status": "failed",
        "checks": {},
        "threshold_rationale": {
            "wrist_max_gap_m": WRIST_MAX_GAP_M,
            "ankle_max_gap_m": ANKLE_MAX_GAP_M,
            "wrist_fitted_contour_reserve_m": 0.0023,
            "boot_fitted_contour_clearance_m": 0.0025,
            "minimum_samples_per_side_and_state": MIN_CONTACT_SAMPLES,
            "meaning": "every radial outward ray from an evaluated seam boundary must hit the evaluated covering shell within the threshold; thresholds include garment shell thickness and fitted clearance",
        },
        "limitations": "Sampled seam coverage in Blender evaluated meshes only; not full surface collision detection, cloth simulation, runtime VRM deformation, or visual review.",
        "failures": [],
    }
    failures = report["failures"]
    evaluated_refs = []
    saved_bases = {}

    try:
        required = (
            "Body", "JawlieConnectedPetrolBomber", "JawlieContinuousCargoTrousers",
            "JawlieCombatBootJ_Bip_L_", "JawlieCombatBootJ_Bip_R_",
        )
        objects = {name: bpy.data.objects.get(name) for name in required}
        missing = [name for name, obj in objects.items() if obj is None]
        if missing:
            raise RuntimeError("Candidate is missing required seam meshes: " + ", ".join(missing))
        body, jacket, pants = (objects[name] for name in required[:3])
        boots = {1: objects[required[3]], -1: objects[required[4]]}
        rigs = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
        if len(rigs) != 1:
            raise RuntimeError(f"Expected one armature, found {len(rigs)}")
        rig = rigs[0]

        for obj in (body, jacket, pants, *boots.values()):
            require_armature_modifier(obj, rig)

        skin_index = next(
            (i for i, material in enumerate(body.data.materials)
             if material and "Body_00_SKIN" in material.name),
            None,
        )
        if skin_index is None:
            raise RuntimeError("Body_00_SKIN material section was not found on Body")

        section_data = {}
        for side_name, side in (("L", 1), ("R", -1)):
            section_data[side_name] = {
                "body_skin_x_0.545": section_report(body, 0, side * 0.545, side, skin_index),
                "body_skin_x_0.557": section_report(body, 0, side * 0.557, side, skin_index),
                "jacket_x_0.545": section_report(jacket, 0, side * 0.545, side),
                "jacket_x_0.557": section_report(jacket, 0, side * 0.557, side),
                "trouser_z_0.185": section_report(pants, 2, 0.185, side),
                "trouser_z_0.1851": section_report(pants, 2, 0.1851, side),
                "trouser_z_0.205": section_report(pants, 2, 0.205, side),
                "boot_z_0.185": section_report(boots[side], 2, 0.185, side),
                "boot_z_0.1851": section_report(boots[side], 2, 0.1851, side),
                "boot_z_0.205": section_report(boots[side], 2, 0.205, side),
            }
        report["rest_section_bounds"] = section_data

        seam_indices = {}
        for side, side_name in ((1, "L"), (-1, "R")):
            seam_indices[f"wrist_{side_name}"] = boundary_indices(
                body, 0, side * 0.545, side=side, material_index=skin_index
            )
            seam_indices[f"ankle_{side_name}"] = boundary_indices(
                pants, 2, 0.185, side=side
            )
            for seam_key, indices in seam_indices.items():
                if seam_key.endswith(side_name) and len(indices) < MIN_CONTACT_SAMPLES:
                    raise RuntimeError(
                        f"{seam_key}: source seam has {len(indices)} boundary samples; "
                        f"need at least {MIN_CONTACT_SAMPLES}"
                    )

        pose_specs = [("rest", None, None, 0.0)]
        for side, side_name in ((1, "L"), (-1, "R")):
            pose_specs.extend(
                (f"wrist_{side_name}_{axis}_{angle:+.2f}rad",
                 f"J_Bip_{side_name}_Hand", axis, angle)
                for axis in ("Y", "Z") for angle in (-0.35, 0.35)
            )
            pose_specs.extend(
                (f"ankle_{side_name}_{axis}_{angle:+.2f}rad",
                 f"J_Bip_{side_name}_Foot", axis, angle)
                for axis in ("X", "Y") for angle in (-0.40, 0.40)
            )

        for bone in rig.pose.bones:
            saved_bases[bone.name] = (bone, bone.matrix_basis.copy(), bone.rotation_mode)

        for state, bone_name, axis_name, angle in pose_specs:
            for bone, basis, rotation_mode in saved_bases.values():
                bone.matrix_basis = basis
                bone.rotation_mode = rotation_mode
            if bone_name is not None:
                bone = rig.pose.bones.get(bone_name)
                if bone is None:
                    raise RuntimeError(f"Required humanoid pose bone is missing: {bone_name}")
                bone.rotation_mode = "QUATERNION"
                world_axes = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0),
                              "Z": (0.0, 0.0, 1.0)}
                axis = pose_local_axis(bone, world_axes[axis_name])
                bone.rotation_quaternion = Quaternion(axis, angle)
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()

            evaluated_refs.clear()
            jacket_eval, jacket_mesh, _, jacket_tree = evaluated_mesh(jacket, depsgraph)
            evaluated_refs.append((jacket_eval, jacket_mesh))
            wrist_ids = sorted(set(seam_indices["wrist_L"] + seam_indices["wrist_R"]))
            ankle_ids = sorted(set(seam_indices["ankle_L"] + seam_indices["ankle_R"]))
            body_points = armature_only_points(body, rig, depsgraph, wrist_ids)
            pants_points = armature_only_points(pants, rig, depsgraph, ankle_ids)

            for side, side_name in ((1, "L"), (-1, "R")):
                wrist_result = seam_check(
                    body, jacket,
                    [body_points[index] for index in seam_indices[f"wrist_{side_name}"]],
                    jacket_tree,
                    f"{state}/wrist_{side_name}", WRIST_MAX_GAP_M,
                    (1, 2), include_samples=(state == "rest"),
                )
                if wrist_result["status"] != "passed":
                    failures.append(
                        f"{state} {side_name} wrist seam exceeds {WRIST_MAX_GAP_M:.3f} m"
                    )

                boot = boots[side]
                boot_eval, boot_mesh, _, boot_tree = evaluated_mesh(boot, depsgraph)
                evaluated_refs.append((boot_eval, boot_mesh))
                ankle_result = seam_check(
                    pants, boot,
                    [pants_points[index] for index in seam_indices[f"ankle_{side_name}"]],
                    boot_tree,
                    f"{state}/ankle_{side_name}", ANKLE_MAX_GAP_M,
                    (0, 1), include_samples=(state == "rest"),
                )
                if ankle_result["status"] != "passed":
                    failures.append(
                        f"{state} {side_name} ankle seam exceeds {ANKLE_MAX_GAP_M:.3f} m"
                    )
                report["checks"][f"{state}/{side_name}"] = {
                    "wrist": wrist_result,
                    "ankle": ankle_result,
                }
                boot_eval.to_mesh_clear()
                evaluated_refs.pop()

            for evaluated, _mesh in evaluated_refs:
                evaluated.to_mesh_clear()
            evaluated_refs.clear()

        report["status"] = "passed" if not failures else "failed"
        report["posed_render_evidence"] = render_evidence(rig, saved_bases)
    except Exception as exc:
        failures.append(f"diagnostic: {type(exc).__name__}: {exc}")
        report["status"] = "failed"
    finally:
        for bone, basis, rotation_mode in saved_bases.values():
            bone.matrix_basis = basis
            bone.rotation_mode = rotation_mode
        for evaluated, _mesh in evaluated_refs:
            evaluated.to_mesh_clear()
        if saved_bases:
            bpy.context.view_layer.update()
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("INTERFACE_V9_JOINTS", json.dumps(report, separators=(",", ":")))
    if report["status"] != "passed":
        raise RuntimeError("Interface V9 seam acceptance failed; see " + str(REPORT_PATH))


main()
