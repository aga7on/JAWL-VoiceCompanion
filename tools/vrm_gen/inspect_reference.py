"""Blender-side structural diagnostics; never accepts an asset licence dialog."""
from pathlib import Path
import sys
import json
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_vroid_reference import enable_vrm_addon, SOURCE, EDITABLE

if '--source' in sys.argv:
    enable_vrm_addon()
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    if 'FINISHED' not in bpy.ops.import_scene.vrm(filepath=str(SOURCE)):
        raise RuntimeError('Original asset import did not finish')
else:
    bpy.ops.wm.open_mainfile(filepath=str(EDITABLE))

for obj in bpy.data.objects:
    if obj.type not in ('MESH', 'ARMATURE'):
        continue
    out = {'name':obj.name, 'type':obj.type, 'parent':obj.parent.name if obj.parent else None,
           'world': [list(row) for row in obj.matrix_world],
           'modifiers': [(m.type, getattr(getattr(m,'object',None),'name',None)) for m in obj.modifiers]}
    if obj.type == 'MESH':
        out['bounds'] = [[round(min(v.co[a] for v in obj.data.vertices),4), round(max(v.co[a] for v in obj.data.vertices),4)] for a in range(3)]
        out['materials'] = [(i,m.name) for i,m in enumerate(obj.data.materials)]
        out['groups'] = len(obj.vertex_groups)
        out['morphs'] = len(obj.data.shape_keys.key_blocks) if obj.data.shape_keys else 0
        for i, mat in enumerate(obj.data.materials):
            verts = {index for face in obj.data.polygons if face.material_index==i for index in face.vertices}
            if verts:
                print('MAT_BOUNDS', obj.name, mat.name, len(verts),
                    [[round(min(obj.data.vertices[v].co[a] for v in verts),4),round(max(obj.data.vertices[v].co[a] for v in verts),4)] for a in range(3)])
                if '--top-weights' in sys.argv and 'Tops' in mat.name:
                    groups={}
                    for index in verts:
                        for group in obj.data.vertices[index].groups:
                            name=obj.vertex_groups[group.group].name
                            groups[name]=round(groups.get(name,0)+group.weight,3)
                    print('TOP_WEIGHT_GROUPS',json.dumps(groups))
        sample = sorted(obj.data.vertices, key=lambda v: abs(v.co.x-.50)+abs(v.co.z-1.22))[0]
        out['arm_vertex'] = {'co':list(sample.co),'weights':[(obj.vertex_groups[g.group].name,round(g.weight,4)) for g in sample.groups]}
    else:
        out['bones'] = {b.name:{'head':list(b.head_local),'tail':list(b.tail_local)} for b in obj.data.bones if b.name in ('J_Bip_C_Head','J_Bip_C_Hips','J_Bip_L_UpperArm','J_Bip_R_UpperArm','J_Bip_L_Hand','J_Bip_L_UpperLeg','J_Bip_L_Foot')}
    print('OBJECT_DIAGNOSTIC', json.dumps(out))
