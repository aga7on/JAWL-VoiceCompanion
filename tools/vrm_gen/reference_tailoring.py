"""Cloth surfaces in baked world/rest coordinates, with normalized skin weights."""
import bmesh
import bpy
from math import cos, pi, sin, sqrt
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HELPERS = {
    'jawlie_soft_chest_l': ('J_Bip_C_UpperChest', (.075,-.035,1.16), (.075,-.075,1.09)),
    'jawlie_soft_chest_r': ('J_Bip_C_UpperChest', (-.075,-.035,1.16), (-.075,-.075,1.09)),
    'jawlie_soft_hip_l': ('J_Bip_C_Hips', (.085,.025,.90), (.085,.030,.83)),
    'jawlie_soft_hip_r': ('J_Bip_C_Hips', (-.085,.025,.90), (-.085,.030,.83)),
    'jawlie_cloth_hem_l': ('J_Bip_C_Spine', (.12,0,1.015), (.12,0,.97)),
    'jawlie_cloth_hem_r': ('J_Bip_C_Spine', (-.12,0,1.015), (-.12,0,.97)),
}

def add_soft_helper_bones(rig):
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True); bpy.context.view_layer.objects.active=rig
    bpy.ops.object.mode_set(mode='EDIT')
    for name,(parent,head,tail) in HELPERS.items():
        bone=rig.data.edit_bones.get(name) or rig.data.edit_bones.new(name)
        bone.head,bone.tail=head,tail; bone.parent=rig.data.edit_bones[parent]
        bone.use_connect,bone.use_deform=False,True
    bpy.ops.object.mode_set(mode='OBJECT')

def normalize(weights):
    values=sorted(((n,w) for n,w in weights.items() if w>1e-6),key=lambda item:item[1],reverse=True)[:4]
    total=sum(w for _,w in values)
    if not total: raise ValueError('Unweighted garment vertex')
    return {n:w/total for n,w in values}

def torso_weights(point,soft=True):
    x,y,z=point
    upper=max(0,min(1,(z-1.14)/.095)); chest=max(0,min(1,(z-1.015)/.10))
    weights={'J_Bip_C_Spine':1-chest,'J_Bip_C_Chest':chest*(1-upper),'J_Bip_C_UpperChest':chest*upper}
    helper,amount=None,0
    if soft and z<1.04:
        helper='jawlie_cloth_hem_l' if x>=0 else 'jawlie_cloth_hem_r'
        amount=.18*max(0,1-abs(z-.987)/.07)
    elif soft and y<-.045 and 1.08<z<1.21:
        helper='jawlie_soft_chest_l' if x>=0 else 'jawlie_soft_chest_r'
        amount=.16*max(0,1-abs(z-1.145)/.08)
    if helper:
        weights={n:w*(1-amount) for n,w in weights.items()}; weights[helper]=amount
    return normalize(weights)

def leg_weights(point,side):
    x,y,z=point
    upper=max(0,min(1,(z-.45)/.09)); hip=max(0,min(.55,(z-.80)/.16))
    prefix='J_Bip_L_' if side>0 else 'J_Bip_R_'
    weights={prefix+'UpperLeg':upper*(1-hip),prefix+'LowerLeg':(1-upper)*(1-hip),'J_Bip_C_Hips':hip}
    if z>.78:
        amount=.16*max(0,min(1,(z-.78)/.10)); weights={n:w*(1-amount) for n,w in weights.items()}
        weights['jawlie_soft_hip_l' if side>0 else 'jawlie_soft_hip_r']=amount
    return normalize(weights)

def mesh_object(name,vertices,faces,material,rig,weights,thickness=0):
    mesh=bpy.data.meshes.new(name+'Mesh'); mesh.from_pydata(vertices,[],faces); mesh.materials.append(material)
    bm=bmesh.new(); bm.from_mesh(mesh); bmesh.ops.recalc_face_normals(bm,faces=bm.faces); bm.to_mesh(mesh); bm.free()
    for poly in mesh.polygons: poly.use_smooth=True
    mesh.update()
    obj=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(obj); obj.parent=rig
    groups={}
    for index,point in enumerate(vertices):
        for bone,weight in normalize(weights(index,point)).items():
            if bone not in rig.data.bones: raise ValueError('Unknown bone: '+bone)
            if bone not in groups: groups[bone]=obj.vertex_groups.new(name=bone)
            groups[bone].add([index],weight,'REPLACE')
    armature=obj.modifiers.new(name+' skin','ARMATURE'); armature.object=rig
    if thickness:
        shell=obj.modifiers.new(name+' thickness','SOLIDIFY'); shell.thickness,shell.offset=thickness,0
    return obj

def surface(name,rows,material,rig,weight_fn,opening=0,wrinkles=0,center_x=0,cap_bottom=False):
    segments=48; vertices,faces=[],[]
    for i,(z,rx,ry,cy) in enumerate(rows):
        cx=center_x(z) if callable(center_x) else center_x
        for j in range(segments+1):
            theta=-pi/2+opening+(2*pi-2*opening)*j/segments
            fold=wrinkles*sin(theta*7+i*.9)*sin(i*pi/max(1,len(rows)-1))
            vertices.append((cx+(rx+fold)*cos(theta),cy+(ry+fold)*sin(theta),z))
    for i in range(len(rows)-1):
        for j in range(segments):
            a=i*(segments+1)+j; b=a+segments+1; faces.append((a,a+1,b+1,b))
    if cap_bottom:
        if opening:
            raise ValueError('Cannot cap an open garment surface')
        faces.append(tuple(reversed(range(segments))))
    obj=mesh_object(name,vertices,faces,material,rig,lambda _,point:weight_fn(point),.003)
    return obj,[vertices[i*(segments+1)] for i in range(len(rows))],[vertices[i*(segments+1)+segments] for i in range(len(rows))]

def tube(name,points,radius,material,rig,weight_fn,sides=8):
    vertices,faces=[],[]
    for i,raw in enumerate(points):
        point=Vector(raw); tangent=Vector(points[min(i+1,len(points)-1)])-Vector(points[max(i-1,0)])
        tangent.normalize(); cross=tangent.cross(Vector((0,1,0)))
        if cross.length<.01: cross=tangent.cross(Vector((1,0,0)))
        cross.normalize(); other=tangent.cross(cross).normalized()
        for j in range(sides): vertices.append(tuple(point+radius*(cos(j*2*pi/sides)*cross+sin(j*2*pi/sides)*other)))
    for i in range(len(points)-1):
        for j in range(sides):
            a=i*sides+j; b=i*sides+(j+1)%sides; faces.append((a,b,b+sides,a+sides))
    return mesh_object(name,vertices,faces,material,rig,lambda _,p:weight_fn(p))

def extract(body,polygons,name,material,rig,offset=.004):
    used=sorted({i for poly in polygons for i in poly.vertices}); remap={old:new for new,old in enumerate(used)}
    vertices=[tuple(body.data.vertices[i].co+body.data.vertices[i].normal*offset) for i in used]
    faces=[tuple(remap[i] for i in poly.vertices) for poly in polygons]
    def weights(index,_): return {body.vertex_groups[g.group].name:g.weight for g in body.data.vertices[used[index]].groups}
    return mesh_object(name,vertices,faces,material,rig,weights,.003)

def center(body,poly):
    return sum((body.data.vertices[i].co for i in poly.vertices),Vector())/len(poly.vertices)

def trim_horizontal(obj,low,high):
    """Cut exact cloth hems, interpolating the inherited deform weights."""
    bm=bmesh.new(); bm.from_mesh(obj.data)
    for z,normal in ((low,(0,0,1)),(high,(0,0,-1))):
        bmesh.ops.bisect_plane(bm,geom=[*bm.verts,*bm.edges,*bm.faces],dist=1e-6,
                              plane_co=(0,0,z),plane_no=normal,clear_inner=True)
    bm.to_mesh(obj.data); bm.free(); obj.data.update()

def weld_surface(obj):
    """Remove UV/material split seams from untextured continuous cloth."""
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.0001)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data); bm.free(); obj.data.update()

def bomber_sleeve(rig,mats,side):
    prefix='J_Bip_L_' if side>0 else 'J_Bip_R_'
    rows=[(.112,.079,.070),(.145,.080,.072),(.19,.077,.073),(.235,.072,.072),
          (.28,.068,.068),(.325,.063,.066),(.37,.065,.069),(.415,.063,.067),
          (.46,.058,.061),(.49,.051,.054),(.52,.039,.039),(.54,.034,.034),(.557,.034,.034)]
    segments=32; vertices,faces=[],[]
    for i,(x,ry,rz) in enumerate(rows):
        for j in range(segments):
            theta=j*2*pi/segments
            fold=.0025*sin(theta*5+i*1.6)*sin(i*pi/(len(rows)-1))
            z=1.247-.012*(x-.112)/.445
            vertices.append((side*x,.004+(.85*ry+fold)*sin(theta),z+(.88*rz+fold)*cos(theta)))
    for i in range(len(rows)-1):
        for j in range(segments):
            a=i*segments+j; b=i*segments+(j+1)%segments
            faces.append((a,b,b+segments,a+segments))
    def weights(_,point):
        x=abs(point[0]); lower=max(0,min(1,(x-.30)/.09)); shoulder=max(0,min(.35,(.18-x)/.12))
        return {prefix+'UpperArm':(1-lower)*(1-shoulder),prefix+'LowerArm':lower*(1-shoulder),
                'J_Bip_C_UpperChest':shoulder}
    sleeve=mesh_object('JawlieBomberSleeve'+str(side),vertices,faces,mats['jacket'],rig,weights,.003)
    sleeve.data.materials.append(mats['rib'])
    for poly in sleeve.data.polygons:
        if abs(center(sleeve,poly).x)>.522: poly.material_index=1
    return sleeve

def trousers(body,skin,rig,mats,relax_seat=False,complete_sections=False):
    # Use continuous pelvis/leg topology: joining independent tubes to a
    # cropped pelvis makes a visible shorts seam and breaks bent-leg poses.
    if complete_sections:
        polygons=[p for p in body.data.polygons if p.material_index==skin
                  and min(body.data.vertices[i].co.z for i in p.vertices)<.995
                  and max(body.data.vertices[i].co.z for i in p.vertices)>.16]
    else:
        polygons=[p for p in body.data.polygons if p.material_index==skin and .16<center(body,p).z<.995]
    pants=extract(body,polygons,'JawlieContinuousCargoTrousers',mats['pants'],rig,0 if complete_sections else .006)
    if complete_sections:
        # Weld source UV splits before the normal offset; offsetting split
        # normals first creates small cracks that cannot be welded afterward.
        weld_surface(pants)
        for vertex in pants.data.vertices:
            vertex.co += vertex.normal*.006
        pants.data.update()
    trim_horizontal(pants,.185,.973)
    weld_surface(pants)
    helper_groups={name:pants.vertex_groups.get(name) or pants.vertex_groups.new(name=name)
                   for name in ('jawlie_soft_hip_l','jawlie_soft_hip_r')}
    for vertex in pants.data.vertices:
        co=vertex.co
        side=1 if co.x>=0 else -1
        if co.z<.86:
            cx=side*(.038+.030*max(0,min(1,(co.z-.18)/.62)))
            ease=(.18+.13*max(0,1-abs(co.z-.25)/.10))*max(0,min(1,(.86-co.z)/.14))
            co.x=cx+(co.x-cx)*(1+ease)
            co.y=.008+(co.y-.008)*(1+ease)
            wrinkle=.004*sin((co.z-.18)*95)*max(0,1-abs(co.z-.50)/.09)
            wrinkle+=.0045*sin((co.z-.185)*120)*max(0,1-abs(co.z-.235)/.055)
            co.y+=wrinkle
        elif co.z<.94:
            amount=.12*max(0,1-abs(co.z-.85)/.10)
            for group in list(vertex.groups):
                pants.vertex_groups[group.group].add([vertex.index],group.weight*(1-amount),'REPLACE')
            helper_groups['jawlie_soft_hip_l' if side>0 else 'jawlie_soft_hip_r'].add([vertex.index],amount,'REPLACE')
        if relax_seat and .795 < co.z < .980:
            # Cloth bridges the body's seat cleft rather than copying skin
            # anatomy. Retain connected pelvis/leg topology and every weight;
            # this is a blocking envelope, not painted folds or final cloth.
            lower=max(0,min(1,(co.z-.795)/.08))
            upper=max(0,min(1,(.980-co.z)/.035))
            lower=lower*lower*(3-2*lower)
            upper=upper*upper*(3-2*upper)
            side_mask=max(0,1-(abs(co.x)/.13)**4)
            blend=.50*lower*upper*side_mask
            section=sqrt(max(0,1-(co.x/.158)**2))
            target=.008+(.119 if co.y>=.008 else -.112)*section
            co.y += (target-co.y)*blend
    pants.data.update()
    return pants

def erase_covered_body(body,skin_index,clean_cuffs=False,covered_height=1.255):
    bm=bmesh.new(); bm.from_mesh(body.data); doomed=[]
    if clean_cuffs:
        # Interpolated wrist cuts stay inside cuffs, unlike polygon-centroid
        # deletion that leaves staircase-shaped skin edges.
        for x in (-.545,.545):
            bmesh.ops.bisect_plane(bm,geom=[*bm.verts,*bm.edges,*bm.faces],dist=1e-6,
                                  plane_co=(x,0,0),plane_no=(1,0,0))
    for face in bm.faces:
        p=face.calc_center_median()
        wrist_limit=.545 if clean_cuffs else .55
        if face.material_index!=skin_index or (p.z<covered_height and abs(p.x)<wrist_limit): doomed.append(face)
    bmesh.ops.delete(bm,geom=doomed,context='FACES_ONLY')
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
    bm.to_mesh(body.data); bm.free(); body.data.update()

def boots(rig,mats,side,fit_review=False,interface_pants=None):
    prefix='J_Bip_L_' if side>0 else 'J_Bip_R_'; cx=side*.038
    def weight(p):
        if interface_pants is None:
            return {prefix+'Foot':1}
        shin=max(0,min(1,(p[2]-.095)/.075))
        shin=shin*shin*(3-2*shin)
        return {prefix+'Foot':1-shin,prefix+'LowerLeg':shin}
    rows=[(.005,.045,.092,-.029),(.019,.046,.093,-.029),(.026,.044,.091,-.029),(.041,.044,.089,-.030),
          (.060,.043,.086,-.026),(.082,.040,.064,-.003),(.100,.036,.048,.014),(.135,.038,.046,.018),
          (.17,.040,.048,.018),(.195,.041,.049,.018)]
    center_x = cx
    if interface_pants is not None:
        from reference_interfaces import ankle_fit
        (top_cx,top_cy),(rx,ry)=ankle_fit(interface_pants,side)
        rows[-2:] = [(.170,rx+.004,ry+.004,top_cy),(.195,rx+.0035,ry+.0035,top_cy),(.210,rx+.0035,ry+.0035,top_cy)]
        center_x = lambda z: cx+(top_cx-cx)*max(0,min(1,(z-.10)/.07))
    boot,_,_=surface('JawlieCombatBoot'+prefix,rows,mats['boots'],rig,weight,wrinkles=.001,center_x=center_x,cap_bottom=fit_review)
    if interface_pants is not None:
        from reference_interfaces import fitted_section
        directions=[(cos(-pi/2+2*pi*j/48),sin(-pi/2+2*pi*j/48)) for j in range(49)]
        for row,(z,*_) in enumerate(rows):
            if z < .170:
                continue
            # Slice 0.1 mm above the cut plane to avoid coplanar triangulated
            # hem edges; this is below the clearance, not a fitting tolerance.
            fitted=fitted_section(interface_pants,2,max(.1851,z),directions,.0025,side=side)
            for j,point in enumerate(fitted):
                boot.data.vertices[row*49+j].co=(point[0],point[1],z)
        boot.data.update()
    if fit_review:
        weld_surface(boot)
    boot.data.materials.append(mats['sole']); boot.data.materials.append(mats['cargo'])
    for poly in boot.data.polygons:
        p=center(boot,poly)
        if .008<p.z<.026:
            poly.material_index=0 if fit_review else (1 if p.y<-.098 or (abs(p.x-cx)>.034 and -.03<p.y<.01) else 2)
        if fit_review and p.z<.008:
            poly.use_smooth=False
    objects=[boot]
    if fit_review:
        # Curved small inlays replace coarse per-face mint paint. Sole stays
        # black and closed; no material staircase at the toe or arch.
        for label,angle in (('Toe',-pi/2),('Outer',0 if side>0 else pi)):
            span=.22 if label=='Toe' else .16
            corners=[]
            for theta,z in ((angle-span,.008),(angle+span,.008),(angle+span,.023),(angle-span,.023)):
                corners.append((cx+.046*cos(theta),-.029+.093*sin(theta),z))
            objects.append(conform_panel('JawlieMintBoot'+label+prefix,corners,boot,mats['sole'],rig,.0025))
    tongue=[(cx-.023,-.036,.102),(cx+.023,-.036,.102),(cx+.024,-.037,.19),(cx-.024,-.037,.19)]
    if interface_pants is not None:
        objects.append(conform_panel('JawlieBootTongue'+prefix,tongue,boot,mats['cargo'],rig,.0015))
    else:
        objects.append(mesh_object('JawlieBootTongue'+prefix,tongue,[(0,1,2,3)],mats['cargo'],rig,lambda i,p:weight(p),.002))
    lace_tree = BVHTree.FromPolygons([v.co for v in boot.data.vertices],[tuple(p.vertices) for p in boot.data.polygons]) if interface_pants is not None else None
    for i in range(6):
        z=.080+i*.018; y=-.067 if i==0 else -.037
        points=[(cx-.021,y,z),(cx,y-.004,z+.007),(cx+.021,y,z+.014)]
        if lace_tree is not None:
            projected=[]
            for point in points:
                location,normal,_,_=lace_tree.find_nearest(Vector(point))
                projected.append(tuple(location+normal*.0018))
            points=projected
        objects.append(tube('JawlieBootLace'+prefix+str(i),points,.0014,mats['seam'],rig,weight,6))
    return objects

def conform_panel(name,corners,cloth,material,rig,offset,stitched=False):
    """Project a panel to cloth and interpolate that cloth's skin weights."""
    cloth.data.calc_loop_triangles()
    triangles=[tuple(t.vertices) for t in cloth.data.loop_triangles]
    tree=BVHTree.FromPolygons([v.co for v in cloth.data.vertices],triangles,all_triangles=True)
    vertices,faces,weights=[],[],[]
    a,b,c,d=map(Vector,corners)
    for row in range(6):
        v=row/5
        for column in range(6):
            u=column/5
            raw=a.lerp(b,u).lerp(d.lerp(c,u),v)
            location,normal,index,_=tree.find_nearest(raw)
            if location is None or normal.length<.9:
                raise RuntimeError('Cargo panel projection failed')
            tri=triangles[index]
            p,q,r=(cloth.data.vertices[i].co for i in tri)
            e0,e1,delta=q-p,r-p,location-p
            aa,ab,bb=e0.dot(e0),e0.dot(e1),e1.dot(e1)
            denominator=aa*bb-ab*ab
            if abs(denominator)<1e-12:
                raise RuntimeError('Degenerate cloth triangle under cargo panel')
            wb=(bb*delta.dot(e0)-ab*delta.dot(e1))/denominator
            wc=(aa*delta.dot(e1)-ab*delta.dot(e0))/denominator
            inherited={}
            for vertex_id,factor in zip(tri,(1-wb-wc,wb,wc)):
                for group in cloth.data.vertices[vertex_id].groups:
                    bone=cloth.vertex_groups[group.group].name
                    inherited[bone]=inherited.get(bone,0)+max(0,factor)*group.weight
            weights.append(normalize(inherited))
            # Cloth Solidify extends 1.5 mm outward; panel extends .5 mm
            # inward. A sewn border must meet those shells, not intersect
            # them by projecting only to the cloth's centerline.
            edge=min(u,1-u,v,1-v)
            border=max(.0021,offset-.0005)
            clearance=border+(offset-border)*min(1,edge/.20) if stitched else offset
            vertices.append(tuple(location+normal*clearance))
    for row in range(5):
        for column in range(5):
            i=row*6+column; faces.append((i,i+1,i+7,i+6))
    return mesh_object(name,vertices,faces,material,rig,lambda i,p:weights[i],.001)


def build_reference_garments(body,rig,mats,blocking=False,fit_review=False,shoulder_review=False,interface_review=False):
    if not all(abs(body.matrix_world[i][j]-(1 if i==j else 0))<1e-5 for i in range(4) for j in range(4)):
        raise RuntimeError('Bake source transforms before tailoring')
    skin=next(i for i,m in enumerate(body.data.materials) if 'Body_00_SKIN' in m.name)
    objects=[] if shoulder_review else [bomber_sleeve(rig,mats,side) for side in (-1,1)]
    # Owner override: both hands remain bare, despite the turnaround glove.
    shirt_rows=[(.974,.121,.089,.004),(.99,.126,.096,.004),(1.04,.134,.102,.004),(1.09,.142,.107,.005),
                (1.14,.150,.116,.009),(1.19,.153,.107,.010),(1.225,.151,.083,.012),(1.25,.145,.065,.005),(1.279,.044,.038,.004)]
    if shoulder_review:
        shirt_rows[-3:]=[(1.225,.136,.075,.012),(1.25,.120,.056,.005),(1.279,.044,.038,.004)]
    shirt,_,_=surface('JawlieCottonCrewShirt',shirt_rows,mats['shirt'],rig,torso_weights,wrinkles=.0012); weld_surface(shirt); objects.append(shirt)
    jacket_rows=[(.985,.131,.108,.008),(1.006,.142,.109,.008),(1.035,.156,.112,.009),(1.08,.162,.124,.012),
                 (1.13,.172,.138,.017),(1.18,.179,.127,.018),(1.22,.170,.108,.017),(1.266,.166,.071,.013),(1.29,.062,.045,.006)]
    if fit_review:
        jacket_rows[-1:]=[(1.277,.062,.046,.006),(1.288,.054,.044,.006),(1.308,.053,.043,.006)]
    if shoulder_review:
        from reference_bomber_connected import build_connected_bomber
        jacket,left,right=build_connected_bomber(rig,mats,interface_body=body if interface_review else None)
    else:
        jacket,left,right=surface('JawlieOpenPetrolBomber',jacket_rows,mats['jacket'],rig,torso_weights,opening=.43,wrinkles=.0015)
    objects.append(jacket)
    for side,points in enumerate((left,right)):
        objects.append(tube('JawlieMintZipper'+str(side),points,.0027,mats['mint'],rig,torso_weights))
        seam=[(x+(.004 if side==0 else -.004),y-.001,z) for x,y,z in points]
        objects.append(tube('JawlieZipperBinding'+str(side),seam,.0011,mats['seam'],rig,torso_weights,6))
    hem,_,_=surface('JawlieBomberRibbedHem',[(.970,.132,.107,.009),(.982,.133,.110,.009),(1.003,.139,.111,.009)],mats['rib'],rig,torso_weights,opening=.43,wrinkles=.001); objects.append(hem)
    if not fit_review:
        collar,_,_=surface('JawlieBomberStandCollar',[(1.25,.064,.050,.009),(1.27,.052,.044,.006),(1.308,.049,.043,.006)],mats['jacket'],rig,torso_weights,opening=.72); objects.append(collar)
    pants=trousers(body,skin,rig,mats,relax_seat=blocking,complete_sections=interface_review); objects.append(pants)
    for side in (-1,1):
        if side<0:
            pocket=[(-.142,-.024,.645),(-.091,-.079,.645),(-.097,-.089,.757),(-.149,-.027,.757)]
            flap=[(-.148,-.029,.738),(-.096,-.091,.738),(-.098,-.093,.757),(-.151,-.030,.757)]
            strip=[(-.145,-.029,.651),(-.094,-.084,.651),(-.094,-.084,.666),(-.145,-.029,.666)]
            for name,vertices,key in [('JawlieCargoPocket',pocket,'cargo'),('JawlieCargoPocketFlap',flap,'pants'),('JawlieMintThighBar',strip,'mint')]:
                objects.append(conform_panel(name,vertices,pants,mats[key],rig,
                                             (.0026 if key=='cargo' else .0038) if shoulder_review else (.002 if key=='cargo' else .0035),
                                             stitched=shoulder_review)
                               if fit_review else mesh_object(name,vertices,[(0,1,2,3)],mats[key],rig,lambda i,p:leg_weights(p,-1),.002))
        objects.extend(boots(rig,mats,side,fit_review=fit_review,interface_pants=pants if interface_review else None))
    belt,_,_=surface('JawlieBlackBelt',[(.952,.134,.119,.006),(.975,.134,.119,.006)],mats['boots'],rig,lambda p:{'J_Bip_C_Hips':1}); objects.append(belt)
    buckle=[(-.016,-.116,.954),(.016,-.116,.954),(.016,-.116,.972),(-.016,-.116,.972),
            (-.010,-.118,.958),(.010,-.118,.958),(.010,-.118,.968),(-.010,-.118,.968)]
    objects.append(mesh_object('JawlieBeltBuckle',buckle,[(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)],mats['metal'],rig,lambda i,p:{'J_Bip_C_Hips':1}))
    erase_covered_body(body,skin,clean_cuffs=fit_review,covered_height=1.275 if shoulder_review else 1.255)
    springs=rig.data.vrm_addon_extension.vrm0.secondary_animation.bone_groups
    for i in reversed(range(len(springs))):
        if springs[i].comment in ('Hood','HoodString'): springs.remove(i)
        else:
            springs[i].hit_radius=min(.035,springs[i].hit_radius); springs[i].drag_force=max(.75,springs[i].drag_force); springs[i].gravity_power=0
    return objects

def style_hair_part(hair):
    for vertex in hair.data.vertices:
        co=vertex.co
        if co.y<-.045 and 1.36<co.z<1.49:
            mask=max(0,1-abs(co.x-.015)/.115)*max(0,min(1,(1.49-co.z)/.11)); co.x-=.033*mask
    hair.data.update()
