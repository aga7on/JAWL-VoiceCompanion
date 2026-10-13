"""Bake five editable actions and portable VRMA clips for JawlieReference."""
import math
from pathlib import Path
import bpy
import addon_utils

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runtime/character-reference'
bpy.ops.wm.open_mainfile(filepath=str(OUT/'JawlieReference.blend'))
for mod in addon_utils.modules():
    if 'vrm' in mod.__name__.lower():
        addon_utils.enable(mod.__name__,default_set=False,persistent=False)
arm=bpy.data.objects['JawlieReferenceRig']
bpy.context.view_layer.objects.active=arm
arm.select_set(True)
arm.animation_data_create()
scene=bpy.context.scene
scene.render.fps=30
rest={}
for b in arm.pose.bones:
    b.rotation_mode='XYZ';b.rotation_euler=(0,0,0)
for side in ['left','right']:
    b=arm.pose.bones[side+'UpperArm']
    for angle in [-1.05,1.05]:
        b.rotation_euler.x=angle;bpy.context.view_layer.update()
        if arm.pose.bones[side+'Hand'].head.z<1.1: break
for b in arm.pose.bones: rest[b.name]=b.rotation_euler.copy()
for name,seconds in [('idle',4),('listening',4),('speaking',4),('greeting',3),('nod',1.4)]:
    action=bpy.data.actions.new('Jawlie_'+name);action.use_fake_user=True
    arm.animation_data.action=action
    scene.frame_start=1;scene.frame_end=round(seconds*30)+1
    for frame in range(1,scene.frame_end+1):
        scene.frame_set(frame)
        p=(frame-1)/(scene.frame_end-1);t=p*seconds;env=math.sin(math.pi*p)**2
        for b in arm.pose.bones: b.rotation_euler=rest[b.name]
        arm.pose.bones['chest'].rotation_euler.x+=math.sin(p*math.tau)*.015
        if name=='listening': arm.pose.bones['head'].rotation_euler.y+=env*.08
        if name=='speaking':
            arm.pose.bones['head'].rotation_euler.x+=math.sin(p*math.tau*3)*.035
            arm.pose.bones['rightLowerArm'].rotation_euler.z+=env*.12
        if name=='greeting':
            arm.pose.bones['rightUpperArm'].rotation_euler.x-=env*.4
            arm.pose.bones['rightLowerArm'].rotation_euler.z+=env*1.0
            arm.pose.bones['rightHand'].rotation_euler.y+=env*math.sin(p*math.tau*3)*.35
        if name=='nod': arm.pose.bones['head'].rotation_euler.x+=env*.18
        for b in arm.pose.bones: b.keyframe_insert(data_path='rotation_euler',frame=frame,group=b.name)
    result=bpy.ops.export_scene.vrma(filepath=str(OUT/(name+'.vrma')),armature_object_name=arm.name)
    if 'FINISHED' not in result: raise RuntimeError('Animation export failed: '+name)
arm.animation_data.action=bpy.data.actions['Jawlie_idle']
scene.frame_start=1;scene.frame_end=121;scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'JawlieReference-animated.blend'))
print('MOTIONS_OK idle listening speaking greeting nod')
