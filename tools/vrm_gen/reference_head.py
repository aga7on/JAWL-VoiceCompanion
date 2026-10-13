"""Layered reference hair and morph-safe face tailoring in baked rest space."""
import bpy
from math import cos, exp, pi, sin, sqrt
from mathutils import Matrix, Vector
from uuid import uuid4
from reference_tailoring import mesh_object, weld_surface

def refine_face(face):
    keys=face.data.shape_keys.key_blocks
    signature=[(key.name,len(key.data)) for key in keys]
    iris={i for p in face.data.polygons if any(token in face.data.materials[p.material_index].name
          for token in ('EyeIris','EyeHighlight','EyeExtra')) for i in p.vertices}
    for key in keys:
        for index,point in enumerate(key.data):
            co=point.co
            co.z-=.004*exp(-((co.z-1.335)/.045)**2)
            if index in iris:
                eye_x=.040 if co.x>=0 else -.040
                co.x=eye_x+(co.x-eye_x)*.92
                co.z=1.408+(co.z-1.408)*.92
    face.data.update()
    assert signature==[(key.name,len(key.data)) for key in keys]
    return len(keys)-1


def clean_temple_marking(face):
    """Remap verified maroon scalp UVs; preserve atlas, shader, eye slots and morphs."""
    signature = [(key.name, len(key.data)) for key in face.data.shape_keys.key_blocks]
    skin_slots = {i for i, material in enumerate(face.data.materials) if 'Face_00_SKIN' in material.name}
    if len(skin_slots) != 1:
        raise RuntimeError('Expected exactly one source face-skin slot')
    skin_slot = next(iter(skin_slots))
    uv = face.data.uv_layers.active.data
    protected = {i: tuple(uv[i].uv) for p in face.data.polygons
                 if p.material_index != skin_slot for i in p.loop_indices}
    def smooth(value):
        value = max(0, min(1, value))
        return value * value * (3 - 2 * value)
    affected, changed_loops = [], set()
    for polygon in face.data.polygons:
        if polygon.material_index != skin_slot:
            continue
        changed = False
        for loop in polygon.loop_indices:
            co = face.data.vertices[face.data.loops[loop].vertex_index].co
            amount = (smooth((abs(co.x) - .060) / .014) *
                      smooth((co.y + .075) / .018) * smooth((-co.y - .002) / .007) *
                      smooth((co.z - 1.378) / .025) * smooth((1.53 - co.z) / .01))
            if amount <= .001:
                continue
            original = uv[loop].uv.copy()
            # Spatially continuous remapping across all skin loops avoids the
            # polygon-sized patches made by hard per-triangle selection. The
            # verified lower side-skin band contains no eye/mouth painting.
            target = .30 + (original.y - .4) * .035
            uv[loop].uv.y += (target - original.y) * amount
            changed_loops.add(loop)
            changed = True
        if changed:
            affected.append(polygon.index)
    if not 48 <= len(affected) <= 400:
        raise RuntimeError(f'Temple localization changed unexpectedly: {len(affected)} polygons')
    face['jawlie_temple_uv_polygons'] = len(affected)
    face['jawlie_temple_uv_loops'] = len(changed_loops)
    assert signature == [(key.name, len(key.data)) for key in face.data.shape_keys.key_blocks]
    assert all(tuple(uv[i].uv) == original for i, original in protected.items())
    print('TEMPLE_UV_LOCALIZATION', len(affected), 'polygons', len(changed_loops), 'loops', affected)

def interpolate(t,rows):
    at=t*(len(rows)-1); i=min(len(rows)-2,int(at)); f=at-i
    a,b,c,d=rows[max(0,i-1)],rows[i],rows[i+1],rows[min(len(rows)-1,i+2)]
    return tuple(.5*(2*q+(r-p)*f+(2*p-5*q+4*r-s)*f*f+(-p+3*q-3*r+s)*f**3)
                 for p,q,r,s in zip(a,b,c,d))

def chain_weights(t,names):
    if t<.23:
        amount=max(0,t/.23)
        return {'J_Bip_C_Head':1-amount,names[0]:amount}
    at=min(2.999,max(0,(t-.23)/.77*3)); i=min(2,int(at)); f=at-i
    return {names[i]:1-f,names[i+1]:f} if i<2 else {names[2]:1}

def add_chains(rig,paths):
    springs=rig.data.vrm_addon_extension.vrm0.secondary_animation.bone_groups
    springs.clear()
    bpy.ops.object.select_all(action='DESELECT'); rig.select_set(True)
    bpy.context.view_layer.objects.active=rig; bpy.ops.object.mode_set(mode='EDIT')
    for bone in list(rig.data.edit_bones):
        if bone.name.startswith('HairJoint'): rig.data.edit_bones.remove(bone)
    chains=[]
    for index,path in enumerate(paths):
        parent=rig.data.edit_bones['J_Bip_C_Head']; names=[]
        for level,(a,b) in enumerate(zip(path,path[1:])):
            name=f'HairRef_{index:02}_{level}'
            bone=rig.data.edit_bones.new(name); bone.head,bone.tail=a,b
            bone.parent=parent; bone.use_connect=False; bone.use_deform=True
            parent=bone; names.append(name)
        chains.append(names)
    bpy.ops.object.mode_set(mode='OBJECT')
    group=springs.add(); group.comment='Reference layered hair'
    group.stiffiness=4.0; group.drag_force=.90; group.gravity_power=0
    # A head-space center cancels the very head-turn inertia we want to see.
    group.hit_radius=.018; group.center.bone_name='J_Bip_C_Hips'
    for names in chains: group.bones.add().bone_name=names[0]
    add_hair_colliders(rig,group)
    return chains

def add_hair_colliders(rig,spring):
    """Interior proxies for native hair, not mesh/cloth collision simulation."""
    groups=rig.data.vrm_addon_extension.vrm0.secondary_animation.collider_groups
    groups.clear()
    proxies={
        'J_Bip_C_Head': [((0,.013,1.439),.084),((0,.010,1.487),.065),((0,.015,1.380),.072)],
        'J_Bip_C_UpperChest': [((0,.055,1.200),.075),((-.160,.014,1.230),.040),((.160,.014,1.230),.040)],
    }
    for bone,values in proxies.items():
        group=groups.add(); group.node.bone_name=bone; group.uuid=uuid4().hex
        for index,(location,radius) in enumerate(values):
            obj=bpy.data.objects.new(f'JawlieHairCollider_{bone}_{index}',None)
            bpy.context.collection.objects.link(obj)
            obj.empty_display_type='SPHERE'; obj.empty_display_size=radius; obj.hide_render=True
            collider=group.colliders.add(); collider.bpy_object=obj; collider.fixup(rig,bone)
            bpy.context.view_layer.update()
            obj.matrix_world=Matrix.Translation(Vector(location))
        spring.collider_groups.add().collider_group_uuid=group.uuid
    bpy.context.view_layer.update()

def front_clearance(point,gap=.003):
    """Fit upper front locks to the cap instead of floating centimetres away."""
    if point.z>1.403:
        radius=1-(point.x/.112)**2-((point.z-1.433)/.132)**2
        if radius>0:
            blend=max(0,min(1,(point.z-1.403)/.08)); blend=blend*blend*(3-2*blend)
            point.y+=(.005-.128*sqrt(radius)-gap-point.y)*blend
    return point

def build_layered_hair(source,rig):
    materials=list(source.data.materials)
    # Complete cap instead of a jagged polygon-centre crop of the old bob.
    vertices,faces=[],[]; around,vertical=64,16
    for i in range(vertical+1):
        for j in range(around):
            theta=2*pi*j/around
            # Arched forehead/temple line, not a straight helmet rim.
            limit=1.80+.01*max(0,sin(theta))-.73*max(0,-sin(theta))**1.6
            phi=limit*i/vertical
            vertices.append((.112*sin(phi)*cos(theta),.005+.128*sin(phi)*sin(theta),1.433+.132*cos(phi)))
    for i in range(vertical):
        for j in range(around):
            a=i*around+j; b=i*around+(j+1)%around; faces.append((a,b,b+around,a+around))
    cap=mesh_object('JawlieCrownCap',vertices,faces,materials[0],rig,lambda i,p:{'J_Bip_C_Head':1},.001)
    weld_surface(cap)
    bpy.data.objects.remove(source,do_unlink=True)
    rows=[(1.548,.040,.064,.018),(1.505,.081,.079,.022),(1.452,.101,.087,.035),
          (1.385,.114,.091,.051),(1.310,.132,.090,.080),(1.230,.150,.072,.103),
          (1.150,.157,.059,.118),(1.080,.132,.046,.137),(1.015,.080,.030,.145)]
    count=11; paths=[]
    def back_point(t,theta):
        z,rx,ry,cy=interpolate(t,rows)
        z+=.066*abs(cos(theta))*t**3
        y=cy+ry*sin(theta)
        if z>1.405:
            radius=sqrt(max(0,1-((z-1.433)/.132)**2))
            rx=max(rx,.112*radius+.0015)
            y=max(y,.005+.128*radius*sin(theta)+.0015)
        return Vector((rx*cos(theta),y,z))
    for index in range(count):
        theta=(index+.5)*pi/count
        paths.append([back_point(t,theta) for t in (.23,.49,.75,1)])
    # Asymmetric side part: the left fall frames the eye/cheek, while the
    # right section sweeps towards the ear. No horizontal fringe band.
    locks=[[(.016,-.064,1.550),(-.050,-.125,1.468),(-.093,-.082,1.315),(-.126,-.042,1.178)],
           [(.021,-.057,1.547),(.105,-.077,1.510),(.113,.025,1.350),(.130,.070,1.270)]]
    paths.extend([[Vector(p) for p in path] for path in locks])
    chains=add_chains(rig,paths); objects=[cap]
    vertices,faces,ts,bones=[],[],[],[]; longitudinal,cross=24,6
    for index in range(count):
        start=len(vertices); middle=(index+.5)*pi/count; half=pi/count*.57
        for i in range(longitudinal+1):
            t=i/longitudinal; taper=1 if t<.92 else max(.03,(1-t)/.08)
            for j in range(cross+1):
                u=j/cross*2-1; p=back_point(t,middle+u*half*taper)
                p.y+=.0035*(1-u*u)*sin(t*pi)+.0009*sin(t*9*pi+index)*sin(t*pi)
                vertices.append(tuple(p)); ts.append(t); bones.append(index)
        for i in range(longitudinal):
            for j in range(cross):
                a=start+i*(cross+1)+j; faces.append((a,a+1,a+cross+2,a+cross+1))
    # Shorter underlay closes gaps between lock tips and during small motions.
    start=len(vertices); segments=66
    for i in range(longitudinal+1):
        t=i/longitudinal
        for j in range(segments+1):
            theta=pi*j/segments; p=back_point(t,theta); p.y-=.005; p.z+=.022*t**8
            vertices.append(tuple(p)); ts.append(t); bones.append(min(count-1,int(theta/pi*count)))
    for i in range(longitudinal):
        for j in range(segments):
            a=start+i*(segments+1)+j; faces.append((a,a+1,a+segments+2,a+segments+1))
    objects.append(mesh_object('JawlieLayeredBackHair',vertices,faces,materials[0],rig,
                               lambda i,p:chain_weights(ts[i],chains[bones[i]]),.0015))
    def ribbon(name,control,widths,material,chain=None):
        vertices,faces,ts=[],[],[]; cross=12; steps=36; control=[Vector(p) for p in control]
        def point_at(t):
            return front_clearance((1-t)**3*control[0]+3*(1-t)**2*t*control[1]+3*(1-t)*t*t*control[2]+t**3*control[3])
        for i in range(steps+1):
            t=i/steps
            p=point_at(t)
            tangent=point_at(min(1,t+.001))-point_at(max(0,t-.001))
            normal=Vector((p.x,p.y-.005,0)).normalized()
            across=normal.cross(tangent).normalized()
            normal=tangent.normalized().cross(across).normalized()
            root=min(1,t/.13); root=root*root*(3-2*root)
            width=.0003+interpolate(t,[(w,) for w in widths])[0]*root
            depth=min(.005,width*.26)
            for j in range(cross):
                angle=j/cross*2*pi
                point=p+across*(width*cos(angle))+normal*(depth*sin(angle))
                # Surface-conformed broad locks keep their upper roots joined.
                fitted=front_clearance(point.copy())
                point.y=fitted.y+normal.y*depth*sin(angle)
                vertices.append(tuple(point)); ts.append(t)
        for i in range(steps):
            for j in range(cross):
                a=i*cross+j; b=i*cross+(j+1)%cross; faces.append((a,b,b+cross,a+cross))
        faces.extend([tuple(reversed(range(cross))),tuple(steps*cross+j for j in range(cross))])
        return mesh_object(name,vertices,faces,material,rig,
                           lambda i,p:chain_weights(ts[i],chain) if chain else {'J_Bip_C_Head':1})
    for index,control in enumerate(locks):
        objects.append(ribbon('JawlieSideLock'+str(index),control,[.015,.018,.014,.0007],materials[index],chains[count+index]))
    for index,shift in enumerate((.005,)):
        control=[(.016+shift,-.064,1.550),(-.037+shift,-.124,1.474),
                 (-.061+shift,-.118,1.411),(-.083+shift,-.093,1.369+index*.038)]
        objects.append(ribbon('JawlieSweptFringe'+str(index),control,[.002,.006,.004,.0003],materials[index]))
    print('REFERENCE_HAIR_CHAINS',len(chains),'BONES',sum(map(len,chains)))
    return objects
