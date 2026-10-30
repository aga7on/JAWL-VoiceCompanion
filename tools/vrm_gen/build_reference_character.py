"""Build a new, editable reference-inspired VRM; never overwrite existing avatars.

Blender --background --python tools/vrm_gen/build_reference_character.py
Outputs runtime/vrm-models/JawlieReference.vrm and runtime/character-reference/.
This is a procedural interpretation, not an image-to-3D reconstruction.
"""
import math
import sys
from pathlib import Path

import addon_utils
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runtime/character-reference'
VRM = ROOT / 'runtime/vrm-models/JawlieReference.vrm'
OUT.mkdir(parents=True, exist_ok=True)
if VRM.exists() and '--replace-generated' not in sys.argv:
    raise RuntimeError('Refusing to replace existing JawlieReference.vrm')
for mod in addon_utils.modules():
    if 'vrm' in mod.__name__.lower():
        addon_utils.enable(mod.__name__, default_set=False, persistent=False)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)


def material(name, color):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*color, 1)
    m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.8
    return m


skin = material('Warm ivory', (0.84, 0.59, 0.43))
hair = material('Chestnut', (0.27, 0.155, 0.075))
hair_light = material('Chestnut highlights', (0.37, 0.225, 0.12))
teal = material('Petrol bomber', (0.023, 0.080, 0.083))
mint = material('Mint piping', (0.27, 0.74, 0.47))
white = material('Ivory knit', (0.86, 0.88, 0.82))
black = material('Graphite cargo', (0.015, 0.019, 0.025))
sole = material('Rubber', (0.029, 0.032, 0.038))
line = material('Face ink', (0.026, 0.017, 0.014))
green = material('Emerald iris', (0.08, 0.38, 0.16))
pink = material('Lips', (0.32, 0.085, 0.073))
objects = []


def mesh(name, verts, faces, mat, weights):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    data.materials.append(mat)
    for poly in data.polygons:
        poly.use_smooth = True
    for i, v in enumerate(verts):
        groups = weights(v) if callable(weights) else {weights: 1}
        for bone, weight in groups.items():
            if weight > 0:
                vg = obj.vertex_groups.get(bone) or obj.vertex_groups.new(name=bone)
                vg.add([i], weight, 'REPLACE')
    objects.append(obj)
    return obj


def loft(name, rings, mat, weights, n=40):
    # rings: (center x,y,z, horizontal radius, depth radius)
    verts = [(x + rx * math.cos(t * 2 * math.pi / n),
              y + ry * math.sin(t * 2 * math.pi / n), z)
             for x, y, z, rx, ry in rings for t in range(n)]
    faces = [(r*n+t, r*n+(t+1)%n, (r+1)*n+(t+1)%n, (r+1)*n+t)
             for r in range(len(rings)-1) for t in range(n)]
    faces += [tuple(reversed(range(n))), tuple(range((len(rings)-1)*n, len(rings)*n))]
    return mesh(name, verts, faces, mat, weights)


def ellipsoid(name, center, scale, mat, weights):
    rings=[]
    for i in range(25):
        a=math.pi*(0.002+0.996*i/24)
        rings.append((center[0],center[1],center[2]-scale[2]*math.cos(a),
                      scale[0]*math.sin(a),scale[1]*math.sin(a)))
    return loft(name,rings,mat,weights)


def tube(name, points, radii, mat, weights, n=16):
    verts=[]
    for i,p in enumerate(points):
        direction=Vector(points[min(i+1,len(points)-1)])-Vector(points[max(i-1,0)])
        axis=direction.normalized()
        u=axis.cross(Vector((0,1,0))).normalized()
        if u.length < 0.1: u=axis.cross(Vector((1,0,0))).normalized()
        w=axis.cross(u).normalized()
        for j in range(n):
            a=j*math.tau/n
            verts.append(tuple(Vector(p)+radii[i]*(math.cos(a)*u+math.sin(a)*w)))
    faces=[(i*n+j,i*n+(j+1)%n,(i+1)*n+(j+1)%n,(i+1)*n+j)
           for i in range(len(points)-1) for j in range(n)]
    faces += [tuple(reversed(range(n))), tuple(range((len(points)-1)*n,len(points)*n))]
    return mesh(name,verts,faces,mat,weights)


def torso_weight(v):
    z=v[2]
    if z < .98: return {'hips':1}
    if z < 1.12: return {'spine':1}
    return {'chest':1}


# Deliberately model in T pose for stable humanoid retargeting.
arm_data=bpy.data.armatures.new('JawlieReferenceRig')
arm=bpy.data.objects.new('JawlieReferenceRig',arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active=arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
def bone(name, head, tail, parent=None):
    b=arm_data.edit_bones.new(name); b.head=head; b.tail=tail
    if parent: b.parent=arm_data.edit_bones[parent]
bone('hips',(0,0,.89),(0,0,1.0))
bone('spine',(0,0,1.0),(0,0,1.12),'hips')
bone('chest',(0,0,1.12),(0,0,1.31),'spine')
bone('neck',(0,0,1.31),(0,0,1.39),'chest')
bone('head',(0,0,1.39),(0,0,1.61),'neck')
for side,s in [('left',1),('right',-1)]:
    bone(side+'Shoulder',(0,0,1.29),(s*.17,0,1.29),'chest')
    bone(side+'UpperArm',(s*.17,0,1.29),(s*.40,0,1.29),side+'Shoulder')
    bone(side+'LowerArm',(s*.40,0,1.29),(s*.61,0,1.29),side+'UpperArm')
    bone(side+'Hand',(s*.61,0,1.29),(s*.68,0,1.29),side+'LowerArm')
    bone(side+'UpperLeg',(s*.086,0,.89),(s*.086,0,.48),'hips')
    bone(side+'LowerLeg',(s*.086,0,.48),(s*.086,0,.12),side+'UpperLeg')
    bone(side+'Foot',(s*.086,0,.12),(s*.086,-.13,.07),side+'LowerLeg')
    bone(side+'Toes',(s*.086,-.13,.07),(s*.086,-.18,.07),side+'Foot')
bpy.ops.object.mode_set(mode='OBJECT')

loft('Neck',[(0,0,1.29,.043,.037),(0,0,1.40,.040,.039)],skin,'neck')
head=loft('Anime face',[(0,0,1.365,.018,.028),(0,-.005,1.39,.048,.054),
    (0,0,1.43,.079,.075),(0,.002,1.48,.100,.090),(0,.006,1.54,.102,.088),
    (0,.008,1.60,.084,.070),(0,.012,1.635,.045,.043),(0,.01,1.645,.004,.004)],skin,'head',64)
for s in [-1,1]: ellipsoid('Ear',(s*.100,0,1.48),(.013,.022,.032),skin,'head')

# Layered white top and open bomber shell, with an actual open front.
loft('Knit top',[(0,0,.90,.108,.069),(0,0,1.02,.104,.065),
    (0,0,1.16,.140,.077),(0,0,1.27,.152,.067),(0,0,1.31,.056,.043)],white,torso_weight)
rings=[(.91,.13,.086),(.94,.14,.090),(1.05,.133,.086),(1.19,.169,.100),(1.28,.169,.074),(1.32,.060,.049)]
vs=[]; fs=[]; N=48
for z,rx,ry in rings:
    for j in range(N+1):
        a=-math.pi/2+.33+j*(math.tau-.66)/N
        vs.append((rx*math.cos(a),ry*math.sin(a),z))
for r in range(len(rings)-1):
    for j in range(N):
        a=r*(N+1)+j;fs.append((a,a+1,a+N+2,a+N+1))
mesh('Open bomber',vs,fs,teal,torso_weight)
for s in [-1,1]:
    tube('Mint zipper',[(s*rx*math.sin(.33),-ry*math.cos(.33)-.002,z) for z,rx,ry in rings],
         [.004]*len(rings),mint,torso_weight,8)
loft('Belt',[(0,0,.891,.127,.083),(0,0,.924,.127,.083)],black,'hips')
ellipsoid('Buckle',(0,-.087,.907),(.017,.006,.015),sole,'hips')

for side,s in [('left',1),('right',-1)]:
    def aw(v,side=side):
        t=max(0,min(1,(abs(v[0])-.355)/.09))
        return {side+'UpperArm':1-t,side+'LowerArm':t}
    tube(side+' sleeve',[(s*x,0,1.29) for x in [.16,.21,.32,.40,.49,.57,.61]],
         [.058,.066,.062,.055,.055,.044,.036],teal,aw,24)
    tube(side+' cuff',[(s*.585,0,1.29),(s*.616,0,1.29)],[.039,.038],black,side+'LowerArm',24)
    ellipsoid(side+' palm',(s*.651,-.005,1.29),(.046,.031,.015),skin,side+'Hand')
    for j in range(4):
        y=-.029+j*.018
        length=[.052,.065,.060,.047][j]
        tube(side+' finger '+str(j),[(s*.676,y,1.29),(s*(.676+length*.55),y,1.287),(s*(.676+length),y,1.28)],
             [.007,.007,.0045],skin,side+'Hand',10)
    tube(side+' thumb',[(s*.640,-.023,1.286),(s*.660,-.054,1.282),(s*.685,-.065,1.278)],
         [.011,.008,.005],skin,side+'Hand',12)
    if side=='right': ellipsoid('Fingerless glove',(s*.648,-.002,1.29),(.036,.033,.017),sole,side+'Hand')
    def lw(v,side=side):
        t=max(0,min(1,(v[2]-.435)/.09))
        return {side+'UpperLeg':t,side+'LowerLeg':1-t}
    loft(side+' cargo',[(s*.086,0,.125,.041,.045),(s*.086,0,.25,.045,.049),
        (s*.086,-.006,.46,.050,.056),(s*.086,0,.64,.065,.068),
        (s*.073,0,.83,.075,.082),(s*.063,0,.905,.073,.078)],black,lw)
    ellipsoid(side+' boot',(s*.086,-.046,.075),(.055,.122,.068),black,side+'Foot')
    loft(side+' boot collar',[(s*.086,.003,.09,.053,.061),(s*.086,.003,.20,.047,.052)],black,side+'Foot')
    ellipsoid(side+' sole',(s*.086,-.046,.025),(.057,.123,.024),sole,side+'Foot')
    ellipsoid(side+' mint toe',(s*.086,-.152,.025),(.029,.016,.016),mint,side+'Foot')
    for i in range(5):
        tube(side+' lace '+str(i),[(s*.086-.024,-.068+i*.006,.088+i*.014),
                                  (s*.086+.024,-.068+i*.006,.091+i*.014)], [.002,.002],sole,side+'Foot',6)
    if side=='right':
        tube('Thigh mint stripe',[(s*.086-.05,-.066,.72),(s*.086+.05,-.066,.72)], [.009,.009],mint,side+'UpperLeg',8)

# Almond eye surfaces sit in front of the face rather than inside the skull.
eye_meshes=[]
for s in [-1,1]:
    cx=s*.040; z=1.511
    verts=[(cx,-.091,z)]
    for i in range(48):
        a=i*math.tau/48
        verts.append((cx+.027*math.cos(a),-.090+.010*abs(math.cos(a)),z+.017*math.sin(a)+s*.10*.027*math.cos(a)))
    eye=mesh('Eye white',verts,[(0,1+i,1+(i+1)%48) for i in range(48)],white,'head')
    eye_meshes.append(eye)
    for nm,cy,sc,mat in [('Iris',-.094,(.013,.004,.016),green),('Pupil',-.098,(.005,.002,.011),line),('Eye sparkle',-.101,(.003,.001,.004),white)]:
        eye_meshes.append(ellipsoid(nm,(cx-(.004 if nm=='Eye sparkle' else 0),cy,z+.005*(nm=='Eye sparkle')),sc,mat,'head'))
    tube('Upper lash',[(cx+.027*math.cos(a),-.093+.010*abs(math.cos(a)),z+.017*math.sin(a)+s*.0027*math.cos(a)) for a in [math.pi*i/12 for i in range(13)]],[.0022]*13,line,'head',6)
    tube('Brow',[(cx-.023,-.079,1.548),(cx,-.085,1.553),(cx+.023,-.079,1.55)], [.002,.003,.0015],hair,'head',8)
ellipsoid('Nose',(0,-.078,1.468),(.008,.014,.011),skin,'head')
mouth=tube('Smile',[(-.014,-.081,1.43),(0,-.083,1.427),(.014,-.081,1.43)], [.0017,.002,.0017],pink,'head',8)

# Open hair cap (not a sphere over the face), tapered layered back locks.
verts=[];faces=[];rows=18;cols=64
for i in range(rows+1):
    for j in range(cols):
        a=math.tau*j/cols
        front=max(0,-math.sin(a))
        theta=(.01+(1.82-.80*front)*i/rows)
        verts.append((.111*math.sin(theta)*math.cos(a),.009+.099*math.sin(theta)*math.sin(a),1.527+.131*math.cos(theta)))
for i in range(rows):
    for j in range(cols):
        faces.append((i*cols+j,i*cols+(j+1)%cols,(i+1)*cols+(j+1)%cols,(i+1)*cols+j))
mesh('Hair crown',verts,faces,hair,'head')
for i in range(17):
    a=.05+(math.pi-.1)*i/16
    x=.10*math.cos(a); y=.01+.08*math.sin(a)
    end=.97+.09*abs(math.cos(a))+.022*math.sin(i*2)
    pts=[(x,y,1.55),(x*1.09,y+.015,1.43),(x*1.19,y+.03,1.28),
         (x*1.18,y+.035,1.12),(x*.99,y+.015,end)]
    tube('Layered back lock '+str(i),pts,[.026,.025,.023,.019,.001],hair_light if i%4==0 else hair,'head',12)
for s in [-1,1]:
    for i in range(3):
        tube('Face framing lock',[(s*(.06+i*.012),-.062,1.62),(s*(.09+i*.013),-.065,1.52),
            (s*(.093+i*.014),-.054,1.36),(s*(.105+i*.014),-.056,1.19)],
            [.016,.018,.017,.001],hair,'head',12)
tube('Side swept fringe',[(.045,-.071,1.64),(-.015,-.093,1.62),(-.062,-.092,1.55),(-.083,-.081,1.43)],
     [.024,.026,.018,.001],hair_light,'head',16)

# Explicit humanoid and expression bindings; shape key names alone are insufficient.
ext=arm.data.vrm_addon_extension
ext.spec_version='1.0'
for name,hb in ext.vrm1.humanoid.human_bones.human_bone_name_to_human_bone().items():
    n=name.value if hasattr(name,'value') else str(name)
    if arm_data.bones.get(n): hb.node.bone_name=n
ext.vrm1.meta.vrm_name='Jawlie Reference'
ext.vrm1.meta.version='0.1'
ext.vrm1.meta.authors.add().value='ARTEM / JAWL Companion'
def expression(obj,name,transform):
    if not obj.data.shape_keys: obj.shape_key_add(name='Basis')
    key=obj.shape_key_add(name=name)
    for v in key.data: v.co=transform(v.co.copy())
    preset=getattr(ext.vrm1.expressions.preset,name)
    bind=preset.morph_target_binds.add()
    bind.node.mesh_object_name=obj.name;bind.index=name;bind.weight=1
for eye in eye_meshes:
    expression(eye,'blink',lambda v:Vector((v.x,v.y,1.511+(v.z-1.511)*.04)))
expression(mouth,'aa',lambda v:Vector((v.x*1.2,v.y,1.427+(v.z-1.427)*5)))
expression(mouth,'happy',lambda v:Vector((v.x*1.12,v.y,v.z+.18*abs(v.x))))
expression(mouth,'sad',lambda v:Vector((v.x,v.y,v.z-.28*abs(v.x))))
for obj in objects:
    obj.parent=arm
    mod=obj.modifiers.new('Humanoid skin','ARMATURE');mod.object=arm
bpy.ops.object.select_all(action='DESELECT')
arm.select_set(True)
for obj in objects: obj.select_set(True)
bpy.context.view_layer.objects.active=arm
result=bpy.ops.export_scene.vrm(filepath=str(VRM),armature_object_name=arm.name,export_only_selections=True)
if 'FINISHED' not in result or not VRM.exists(): raise RuntimeError('VRM export failed')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'JawlieReference.blend'))

# Preview relaxed pose; rest geometry in exported VRM remains retargetable T pose.
for side in ['left','right']:
    pb=arm.pose.bones[side+'UpperArm'];pb.rotation_mode='XYZ'
    for angle in [-1.05,1.05]:
        pb.rotation_euler.x=angle
        bpy.context.view_layer.update()
        if arm.pose.bones[side+'Hand'].head.z < 1.1: break
scene=bpy.context.scene
scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.device='CPU'
scene.render.resolution_x=650;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.world.color=(.18,.18,.18)
scene.view_settings.view_transform='Standard'
for name,pos,power,size in [('Key',(2,-3,4),350,4),('Fill',(-2,-1,2),180,3)]:
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size
    o=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(o);o.location=pos
    o.rotation_euler=(Vector((0,0,1))-o.location).to_track_quat('-Z','Y').to_euler()
cam_data=bpy.data.cameras.new('Preview');cam=bpy.data.objects.new('Preview',cam_data)
bpy.context.collection.objects.link(cam);scene.camera=cam;cam_data.type='ORTHO'
for name,pos,target,scale in [('front',(0,-4,1),(0,0,.84),1.90),('three-quarter',(2,-4,1.4),(0,0,.84),1.90),('face',(0,-3,1.53),(0,0,1.51),.40)]:
    cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler();cam_data.ortho_scale=scale
    scene.render.filepath=str(OUT/(name+'.png'));bpy.ops.render.render(write_still=True)
print('REFERENCE_BUILD_OK',VRM)
