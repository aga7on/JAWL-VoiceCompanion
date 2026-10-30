"""One open bomber surface: shared armhole vertices, not intersecting tubes."""
from bisect import bisect_right
from math import atan2, cos, pi, sin, sqrt
import bpy
import bmesh

from reference_tailoring import mesh_object, normalize, torso_weights


def build_connected_bomber(rig, mats, interface_body=None):
    rows = [(.985,.131,.108,.008),(1.006,.142,.109,.008),
            (1.035,.156,.112,.009),(1.080,.162,.124,.012),
            (1.130,.172,.138,.017),(1.172,.177,.130,.018),
            (1.202,.175,.117,.017),(1.235,.168,.096,.015),
            (1.261,.148,.072,.011),(1.280,.097,.050,.007),
            (1.290,.054,.044,.006),(1.308,.053,.043,.006)]
    segments, opening = 48, .43
    vertices, faces, arm_influence, wrist_bindings = [], [], {}, {}
    for z, rx, ry, cy in rows:
        for j in range(segments+1):
            theta = -pi/2+opening+(2*pi-2*opening)*j/segments
            vertices.append((rx*cos(theta), cy+ry*sin(theta), z))
    # Rectangular parameter-space holes become elliptical 3D armholes.
    # Each boundary vertex is shared by the torso and sleeve faces.
    holes = [(1,6,14),(-1,34,42)]
    low, high = 5, 9
    for row in range(len(rows)-1):
        for col in range(segments):
            if low <= row < high and any(a <= col < b for _,a,b in holes):
                continue
            i = row*(segments+1)+col
            faces.append((i,i+1,i+segments+2,i+segments+1))

    def section(z):
        index = max(0,min(len(rows)-2,bisect_right([r[0] for r in rows],z)-1))
        a,b = rows[index:index+2]
        t = max(0,min(1,(z-a[0])/(b[0]-a[0])))
        return [a[k]+(b[k]-a[k])*t for k in (1,2,3)]

    for side, left, right in holes:
        loop = ([low*(segments+1)+j for j in range(left,right+1)] +
                [i*(segments+1)+right for i in range(low+1,high+1)] +
                [high*(segments+1)+j for j in range(right-1,left-1,-1)] +
                [i*(segments+1)+left for i in range(high-1,low,-1)])
        angles = []
        for index in loop:
            _,y,z = vertices[index]
            theta = atan2((y-.015)/.060,(z-1.227)/.053)
            angles.append(theta)
            z, y = 1.227+.053*cos(theta), .015+.060*sin(theta)
            rx,ry,cy = section(z)
            x = side*rx*sqrt(max(.01,1-((y-cy)/ry)**2))
            vertices[index] = (x,y,z)
            arm_influence[index]=max(0,(cos(theta)+1)/2)*.28
        previous = loop
        # The two transition rings form the shoulder cap. No duplicate
        # sleeve root or hidden internal torso wall remains at this seam.
        ring_specs = [(.190,.061,.055),(.235,.061,.061),(.280,.058,.060),
                      (.325,.054,.058),(.370,.056,.061),(.415,.054,.058),
                      (.460,.049,.053),(.490,.043,.047),(.520,.033,.034),
                      (.540,.029,.030),(.557,.029,.030)]
        first = [(side*.190,.004+.061*sin(t),1.245+.055*cos(t)) for t in angles]
        root = [vertices[i] for i in loop]
        ring_points = []
        ring_influence=[]
        for fraction in (.33,.67):
            ring_points.append([tuple(a[k]+(b[k]-a[k])*fraction for k in range(3))
                                for a,b in zip(root,first)])
            ring_influence.append([arm_influence[i]+(.85-arm_influence[i])*fraction for i in loop])
        for x,ry,rz in ring_specs:
            center_z = 1.245-.010*(x-.190)/.367
            points = [(side*x,.004+ry*sin(t),center_z+rz*cos(t)) for t in angles]
            if interface_body is not None and x >= .520:
                from reference_interfaces import fitted_section
                skin = next(i for i,m in enumerate(interface_body.data.materials) if 'Body_00_SKIN' in m.name)
                # Reserve 0.7 mm for subdivision interpolation between the
                # sampled contour directions, keeping the shell off the skin.
                fitted = fitted_section(interface_body,0,side*x,[(sin(t),cos(t)) for t in angles],.0023,skin)
                amount = min(1,max(0,(x-.520)/.020))
                amount = amount*amount*(3-2*amount)
                points = [tuple((1-amount)*a+amount*b for a,b in zip(p,q)) for p,q in zip(points,fitted)]
            ring_points.append(points)
            ring_influence.append([.85 if x==.190 else 1.0]*len(loop))
        if interface_body is not None:
            # Return lip meets the skin inside the sleeve, hiding the annulus.
            ring_points.append(fitted_section(interface_body,0,side*.553,[(sin(t),cos(t)) for t in angles],-.0003,skin))
            ring_influence.append([1.0]*len(loop))
        for points,influence in zip(ring_points,ring_influence):
            current = list(range(len(vertices),len(vertices)+len(points)))
            vertices.extend(points)
            arm_influence.update(zip(current,influence))
            if interface_body is not None:
                from reference_interfaces import closest_skin_weights
                for index,point in zip(current,points):
                    if abs(point[0]) >= .540:
                        wrist_bindings[index] = closest_skin_weights(interface_body,point)
            for j in range(len(loop)):
                faces.append((previous[j],previous[(j+1)%len(loop)],
                              current[(j+1)%len(loop)],current[j]))
            previous = current

    # Discard the unused vertices inside the cutouts, not merely their faces.
    used = sorted({i for face in faces for i in face})
    remap = {old:new for new,old in enumerate(used)}
    vertices = [vertices[i] for i in used]
    arm_influence={remap[i]:value for i,value in arm_influence.items() if i in remap}
    wrist_bindings={remap[i]:value for i,value in wrist_bindings.items() if i in remap}
    faces = [tuple(remap[i] for i in face) for face in faces]

    def weights(index, point):
        if index in wrist_bindings:
            return normalize(wrist_bindings[index])
        x,y,z = point
        base = torso_weights(point)
        shoulder=arm_influence.get(index,0)
        if not shoulder:
            return base
        side = 'L' if x>0 else 'R'
        lower = max(0,min(1,(abs(x)-.30)/.09))
        values = {name:value*(1-shoulder) for name,value in base.items()}
        values['J_Bip_'+side+'_UpperArm'] = shoulder*(1-lower)
        values['J_Bip_'+side+'_LowerArm'] = shoulder*lower
        return normalize(values)

    obj = mesh_object('JawlieConnectedPetrolBomber',vertices,faces,mats['jacket'],rig,weights,.003)
    obj.data.materials.append(mats['rib'])
    for poly in obj.data.polygons:
        if all(abs(obj.data.vertices[i].co.x)>.522 for i in poly.vertices):
            poly.material_index = 1
    # Smooth the sparse parameter-space shoulder cap before deformation.
    # Crease only garment boundaries, preserving the open zipper/cuff edges.
    bm=bmesh.new(); bm.from_mesh(obj.data)
    crease=bm.edges.layers.float.get('crease_edge') or bm.edges.layers.float.new('crease_edge')
    for edge in bm.edges: edge[crease]=1.0 if edge.is_boundary else 0.0
    bm.to_mesh(obj.data); bm.free()
    subdiv=obj.modifiers.new('Tailored shoulder surface','SUBSURF'); subdiv.levels=1
    bpy.context.view_layer.objects.active=obj
    while obj.modifiers.find(subdiv.name)>0:
        bpy.ops.object.modifier_move_up(modifier=subdiv.name)
    bpy.ops.object.modifier_apply(modifier=subdiv.name)
    for vertex in obj.data.vertices:
        if interface_body is not None and abs(vertex.co.x) >= .530:
            # Match interpolated source Skin, not the nearest original vertex:
            # nearest-vertex weights form a jump at the hand/forearm transition.
            inherited=normalize(closest_skin_weights(interface_body,vertex.co))
        else:
            inherited=normalize({obj.vertex_groups[g.group].name:g.weight for g in vertex.groups})
        for group in list(vertex.groups): obj.vertex_groups[group.group].remove([vertex.index])
        for name,value in inherited.items(): obj.vertex_groups[name].add([vertex.index],value,'REPLACE')
    left = [vertices[remap[i*(segments+1)]] for i in range(len(rows))]
    right = [vertices[remap[i*(segments+1)+segments]] for i in range(len(rows))]
    return obj,left,right
