"""Read-only Blender checks for the fit candidate's specific geometry fixes."""
import hashlib
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import bmesh
import bpy
from mathutils.bvhtree import BVHTree
from mathutils import Vector, Quaternion

ROOT=Path(__file__).resolve().parents[2]
args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
parser=argparse.ArgumentParser()
parser.add_argument('--candidate',choices=('fit-v4','shoulder-v6','hair-v7','hair-v8','interface-v9'),default='fit-v4')
candidate=parser.parse_args(args).candidate
model_name={'fit-v4':'JawlieFitV4','shoulder-v6':'JawlieShoulderV6','hair-v7':'JawlieHairV7','hair-v8':'JawlieHairV8','interface-v9':'JawlieInterfaceV9'}[candidate]
bpy.ops.wm.open_mainfile(filepath=str(ROOT/f'runtime/character-reference/jawlie-{candidate}.blend'))
report={'run_id':uuid4().hex,'started_utc':datetime.now(timezone.utc).isoformat(),
        'profile':'blender_fit_geometry_no_capture','status':'failed','checks':{},
        'limitations':'Rest mesh checks only, not all-pose collisions, likeness or hardware performance.'}
failures=[]
depsgraph=bpy.context.evaluated_depsgraph_get()
for obj in bpy.data.objects:
    if obj.type!='MESH' or not obj.name.startswith('JawlieCombatBoot'):
        continue
    evaluated=obj.evaluated_get(depsgraph)
    mesh=evaluated.to_mesh()
    bm=bmesh.new()
    try:
        bm.from_mesh(mesh)
        boundaries=sum(edge.is_boundary for edge in bm.edges)
        nonmanifold=sum(not edge.is_manifold for edge in bm.edges)
        bottom_faces=sum(face.calc_center_median().z<.006 for face in bm.faces)
        report['checks'][obj.name]={'boundary_edges':boundaries,'nonmanifold_edges':nonmanifold,
                                   'bottom_faces':bottom_faces}
        if boundaries or nonmanifold or not bottom_faces:
            failures.append(obj.name+' must have a closed manifold sole')
    finally:
        bm.free(); evaluated.to_mesh_clear()
if len(report['checks'])!=2:
    failures.append('Expected exactly two combat boots, not an empty geometry pass')
cloth=bpy.data.objects['JawlieContinuousCargoTrousers']
tree=BVHTree.FromPolygons([v.co for v in cloth.data.vertices],
                         [tuple(p.vertices) for p in cloth.data.polygons])
for name in ('JawlieCargoPocket','JawlieCargoPocketFlap','JawlieMintThighBar'):
    obj=bpy.data.objects[name]
    distances=[tree.find_nearest(v.co)[3] for v in obj.data.vertices]
    sums=[sum(group.weight for group in v.groups) for v in obj.data.vertices]
    report['checks'][name]={'surface_clearance_min':min(distances),'surface_clearance_max':max(distances),
                           'weight_sum_min':min(sums),'weight_sum_max':max(sums)}
    lo,hi=(.0019,.0036) if candidate=='fit-v4' else (.00208,.00385)
    if min(distances)<lo or max(distances)>hi or any(abs(value-1)>.00001 for value in sums):
        failures.append(name+' clearance/weights outside contract')
missing=[v.index for v in bpy.data.objects['Body'].data.vertices if not v.groups]
report['checks']['bare_hands_have_weights']={'unweighted_vertices':len(missing)}
if missing:
    failures.append('Wrist cuts lost skin weights')
if candidate in ('shoulder-v6','hair-v7','hair-v8','interface-v9'):
    jacket=bpy.data.objects['JawlieConnectedPetrolBomber']
    bm=bmesh.new(); bm.from_mesh(jacket.data)
    try:
        remaining=set(bm.verts); components=0
        while remaining:
            stack=[remaining.pop()]; components+=1
            while stack:
                vertex=stack.pop()
                for edge in vertex.link_edges:
                    other=edge.other_vert(vertex)
                    if other in remaining:
                        remaining.remove(other); stack.append(other)
        loose=sum(not vertex.link_faces for vertex in bm.verts)
        branched=sum(sum(edge.is_boundary for edge in vertex.link_edges) not in (0,2) for vertex in bm.verts)
        oversubscribed=sum(len(edge.link_faces)>2 for edge in bm.edges)
        report['checks']['connected_bomber']={'components':components,'loose_vertices':loose,
                                             'branched_boundary_vertices':branched,'oversubscribed_edges':oversubscribed}
        if components!=1 or loose or branched or oversubscribed:
            failures.append('Bomber torso/armholes/sleeves must be one valid connected surface')
    finally:
        bm.free()
    evaluated=jacket.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh=evaluated.to_mesh()
    bm=bmesh.new()
    try:
        bm.from_mesh(mesh)
        bad_edges=sum(not edge.is_manifold for edge in bm.edges)
        report['checks']['bomber_shell']={'nonmanifold_edges':bad_edges}
        if bad_edges: failures.append('Evaluated bomber shell has open/nonmanifold seams')
    finally:
        bm.free(); evaluated.to_mesh_clear()
    # Verify the very same panel/cloth skinning under leg flexion, not only
    # unposed proximity. Exclude shell offsets to compare surface centerlines.
    names=['JawlieContinuousCargoTrousers','JawlieCargoPocket','JawlieCargoPocketFlap','JawlieMintThighBar']
    shell_states=[]
    for name in names:
        for modifier in bpy.data.objects[name].modifiers:
            if modifier.type=='SOLIDIFY':
                shell_states.append((modifier,modifier.show_viewport)); modifier.show_viewport=False
    rig=next(obj for obj in bpy.data.objects if obj.type=='ARMATURE')
    bone=rig.pose.bones['J_Bip_R_UpperLeg']; basis=bone.matrix_basis.copy()
    try:
        for angle in (-.55,.65):
            axis=bone.bone.matrix_local.to_quaternion().inverted() @ Vector((1,0,0))
            bone.rotation_mode='QUATERNION'; bone.rotation_quaternion=Quaternion(axis,angle)
            bpy.context.view_layer.update(); depsgraph=bpy.context.evaluated_depsgraph_get()
            evaluated=cloth.evaluated_get(depsgraph); mesh=evaluated.to_mesh()
            try:
                mesh.calc_loop_triangles()
                tree=BVHTree.FromPolygons([cloth.matrix_world @ v.co for v in mesh.vertices],
                                         [tuple(t.vertices) for t in mesh.loop_triangles],all_triangles=True)
                for name in names[1:]:
                    obj=bpy.data.objects[name]; posed=obj.evaluated_get(depsgraph); panel=posed.to_mesh()
                    try:
                        distances,signed=[],[]
                        for vertex in panel.vertices:
                            point=obj.matrix_world @ vertex.co
                            nearest,normal,_,distance=tree.find_nearest(point)
                            distances.append(distance); signed.append((point-nearest).dot(normal))
                        report['checks'][name+'_flex_'+str(angle)]={'max_clearance':max(distances),'min_signed_clearance':min(signed)}
                        if max(distances)>.0045 or min(signed)<.0017:
                            failures.append(name+' detaches/penetrates under test leg flexion')
                    finally:
                        posed.to_mesh_clear()
            finally:
                evaluated.to_mesh_clear()
    finally:
        bone.matrix_basis=basis
        for modifier,state in shell_states: modifier.show_viewport=state
        bpy.context.view_layer.update()
    # Match the owner's side-on pocket inspection, without changing the
    # packed source or active avatar. Reuse its saved camera/lights.
    scene=bpy.context.scene
    scene.camera.location=(-3,0,.70)
    scene.camera.rotation_euler=(Vector((-.105,0,.70))-scene.camera.location).to_track_quat('-Z','Y').to_euler()
    scene.camera.data.ortho_scale=.28
    scene.render.filepath=str(ROOT/f'runtime/character-reference/jawlie-{candidate}-pocket-profile.png')
    bpy.ops.render.render(write_still=True)
report['failures']=failures
if candidate in ('hair-v8','interface-v9'):
    face = bpy.data.objects['Face']
    temple_polygons = int(face.get('jawlie_temple_uv_polygons', 0))
    temple_loops = int(face.get('jawlie_temple_uv_loops', 0))
    report['checks']['localized_temple_uv'] = {
        'polygons': temple_polygons, 'loops': temple_loops,
        'face_morphs': len(face.data.shape_keys.key_blocks) - 1,
        'original_skin_material_preserved': any('Face_00_SKIN' in m.name for m in face.data.materials),
    }
    if not 48 <= temple_polygons <= 400 or temple_loops < 100 or len(face.data.shape_keys.key_blocks) != 57:
        failures.append('Temple localization or face morph signature changed unexpectedly')
    trees = {}
    for name in ('Face', 'JawlieBlockingContinuousHair', 'JawlieBlockingFrontMass0', 'JawlieBlockingFrontMass1'):
        obj = bpy.data.objects[name]
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            trees[name] = BVHTree.FromPolygons([obj.matrix_world @ v.co for v in mesh.vertices],
                                             [tuple(p.vertices) for p in mesh.polygons])
        finally:
            evaluated.to_mesh_clear()
    report['checks']['rest_hair_face_surface_overlaps'] = {
        name: len(trees['Face'].overlap(tree)) for name, tree in trees.items() if name != 'Face'
    }
    # Diagnostic surface-pair counts include scalp/eyelash surfaces and do not
    # establish all-pose collision acceptance. Never hide a nonzero result.
if candidate in ('shoulder-v6','hair-v7','hair-v8','interface-v9'):
    report['limitations']='Rest topology plus two isolated leg-flexion centerline checks; not all-pose shell collisions, likeness or hardware performance.'
report['status']='passed' if not failures else 'failed'
model=ROOT/f'runtime/vrm-models/{model_name}.vrm'
report['model_sha256']=hashlib.sha256(model.read_bytes()).hexdigest()
(ROOT/f'runtime/character-reference/{candidate}-geometry.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('FIT_GEOMETRY_REPORT',json.dumps(report))
if failures:
    raise RuntimeError('; '.join(failures))
