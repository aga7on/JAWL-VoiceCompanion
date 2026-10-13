"""Continuous primary hair mass for silhouette review, not final strand detail."""
import bpy
from math import cos, exp, pi, sin
from mathutils import Vector
from reference_tailoring import mesh_object, normalize, weld_surface
from reference_head import add_chains, chain_weights, interpolate


def smooth(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def build_blocking_hair(source, rig, refined=False, sculpted=False):
    materials = list(source.data.materials)
    # ONE connected scalp-to-tail surface. There is no cap/panel seam and no
    # identical raised strips. The outer fall is shorter than the centre.
    rows = [(1.565, .001, .001, .005), (1.555, .045, .059, .005),
            (1.522, .086, .104, .005), (1.472, .110, .129, .005),
            (1.405, .114, .122, .019), (1.330, .121, .103, .052),
            (1.240, .130, .079, .092), (1.145, .129, .051, .120),
            (1.045, .106, .028, .139), (.962, .077, .004, .145)]
    if refined:
        # Broader shoulder-level mass and a softer lower taper. The former
        # deep symmetric valleys made the back look like a three-pronged fin.
        rows = [(1.565,.001,.001,.005),(1.555,.045,.059,.005),
                (1.522,.086,.104,.005),(1.472,.110,.129,.005),
                (1.405,.116,.122,.019),(1.330,.128,.103,.052),
                (1.240,.144,.082,.088),(1.145,.146,.055,.117),
                (1.045,.116,.030,.139),(.968,.054,.005,.148)]

    def rear(t, theta):
        if sculpted:
            # Broad masses follow unequal curved flow; no duplicated ribbons.
            theta += .13 * sin(t * pi)
        z, rx, ry, cy = interpolate(t, rows)
        z += (.100 if refined else .147) * abs(cos(theta)) ** 1.4 * t ** 4
        # Central waist-length fall plus two shorter, unequal side masses.
        # The valleys belong to the silhouette; no repeated strand plates.
        valley_width = .20 if refined else .16
        other_width = .23 if refined else .19
        z += (.026 if refined else .110)*(exp(-((theta-.98)/valley_width)**2)+
                    .8*exp(-((theta-2.14)/other_width)**2))*t**9
        broad_fold = (.008*exp(-((theta-.68)/.30)**2)
                      + .012*exp(-((theta-1.65)/.38)**2)
                      + .006*exp(-((theta-2.48)/.25)**2))
        depth = broad_fold * smooth((t-.25)/.45) * (1-smooth((t-.90)/.10))
        if refined:
            # Unequal broad ridges rather than repeated separate strip meshes.
            depth += .005*sin(theta*3+.8)*sin(t*pi)**2
        if sculpted:
            depth += sin(t*pi)**.8 * (
                .015*exp(-((theta-(.66+.10*t))/.38)**2) +
                .022*exp(-((theta-(1.64-.15*t))/.30)**2) +
                .010*exp(-((theta-2.52)/.34)**2) -
                .009*exp(-((theta-1.08)/.16)**2) -
                .008*exp(-((theta-2.07)/.20)**2))
            z += (.020*exp(-((theta-.95)/.22)**2) +
                  .032*exp(-((theta-2.14)/.29)**2) +
                  .007*sin(theta*5+.4)) * t**8
        return Vector((rx*cos(theta), cy + ry*sin(theta) + depth, z))

    def point(t, theta):
        # Crown and an arched forehead line blend continuously into the long
        # back. Roots remain outside the same scalp proxy as the front locks.
        front = max(0, -sin(theta))
        phi = (1.81 - .75*front**1.6 + (.10*cos(theta)*front if refined else 0)) * t
        crown = Vector((.114*sin(phi)*cos(theta),
                        .005+.131*sin(phi)*sin(theta),
                        1.433+.133*cos(phi)))
        if sculpted:
            # A shallow flow valley runs from the side part into the back.
            # Continuous positional relief, not a separate raised cap strip.
            relief = .0035*sin(phi)**2 * (
                .8*exp(-((theta-1.4-.17*t)/.4)**2) -
                .7*exp(-((theta-2.0)/.18)**2))
            crown.x += relief*cos(theta)
            crown.y += relief*sin(theta)
        blend = smooth(sin(theta)/.42)
        return crown.lerp(rear(t, theta), blend)

    count = 11
    paths = [[rear(t, (i+.5)*pi/count) for t in (.32, .55, .78, 1)]
             for i in range(count)]
    locks = [[(.016,-.064,1.554),(-.052,-.130,1.478),
              (-.099,-.093,1.335),(-.132,-.035,1.165)],
             [(.021,-.057,1.550),(.099,-.095,1.521),
              (.114,-.009,1.413),(.131,.055,1.291)]]
    if refined:
        # Keep the side part, but move the fall toward the cheek contour;
        # the old straight blade obscured too much eye/nose and felt rigid.
        locks = [[(.020,-.061,1.551),(-.044,-.133,1.489),
                  (-.110,-.105,1.365),(-.137,-.027,1.215)],
                 [(.024,-.054,1.548),(.085,-.106,1.529),
                  (.111,-.023,1.425),(.130,.047,1.312)]]
    if sculpted:
        locks = [[(.020,-.071,1.551),(-.067,-.143,1.465),
                  (-.110,-.076,1.345),(-.150,-.018,1.215)],
                 [(.021,-.068,1.550),(.090,-.111,1.516),
                  (.095,.014,1.428),(.130,.061,1.337)]]
    paths.extend([[Vector(p) for p in path] for path in locks])
    chains = add_chains(rig, paths)
    vertices, faces, samples = [], [], []
    around, steps = 128, 60
    for i in range(steps+1):
        t = i/steps
        for j in range(around):
            theta = j*2*pi/around
            vertices.append(tuple(point(t, theta)))
            samples.append((t, theta))
    for i in range(steps):
        for j in range(around):
            a=i*around+j; b=i*around+(j+1)%around
            faces.append((a,b,b+around,a+around))

    def weights(index, _):
        t, theta = samples[index]
        amount = smooth(sin(theta)/.42)
        if amount <= 0:
            return {'J_Bip_C_Head': 1}
        # Interpolate both across neighbouring chains and along their length.
        # Discrete one-chain panels would tear a continuous surface in motion.
        at = max(0, min(count-1, theta/pi*count-.5))
        left = int(at); right = min(count-1, left+1); fraction = at-left
        result = {'J_Bip_C_Head': 1-amount}
        for chain, share in ((chains[left], 1-fraction), (chains[right], fraction)):
            for bone, weight in chain_weights(max(0,(t-.12)/.88), chain).items():
                result[bone] = result.get(bone,0)+weight*amount*share
        return normalize(result)

    mass = mesh_object('JawlieBlockingContinuousHair', vertices, faces,
                       materials[0], rig, weights, .0015)
    weld_surface(mass)
    bpy.data.objects.remove(source, do_unlink=True)
    objects = [mass]
    for index, control in enumerate(locks):
        widths = ([.0006,.023,.020,.0004] if index == 0 else [.0006,.015,.014,.0004]) if sculpted else ([.001,.018,.012,.0003] if refined else [.0005,.023,.018,.0005])
        objects.append(front_mass('JawlieBlockingFrontMass'+str(index), control,
                                  widths,
                                  materials[0], rig, chains[count+index],refined=refined,sculpted=sculpted))
    print('REFERENCE_BLOCKING_HAIR', 'primary_masses',len(objects),
          'chains',len(chains),'bones',sum(map(len,chains)))
    return objects


def front_mass(name, control, widths, material, rig, chain, refined=False, sculpted=False):
    controls = [Vector(p) for p in control]
    def fit_scalp(point):
        # Radial projection uses exactly the blocking crown's ellipsoid.
        # Unlike a y-only sqrt clamp, it stays continuous at its upper rim.
        relative=Vector((point.x/.114,(point.y-.005)/.131,(point.z-1.433)/.133))
        if point.z>1.403 and relative.length<1.018:
            fitted=relative.normalized()*1.018
            fitted=Vector((fitted.x*.114,.005+fitted.y*.131,1.433+fitted.z*.133))
            point=point.lerp(fitted,smooth((point.z-1.403)/.04))
        elif sculpted and point.z > 1.485:
            fitted = relative.normalized() * 1.012
            fitted = Vector((fitted.x*.114,.005+fitted.y*.131,1.433+fitted.z*.133))
            point = point.lerp(fitted,smooth((point.z-1.485)/.035))
        return point
    def point(t):
        a,b,c,d = controls
        return fit_scalp((1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t*t*c+t**3*d)
    vertices, faces, ts = [], [], []
    cross, steps = 16, 48
    for i in range(steps+1):
        t=i/steps; p=point(t)
        tangent=(point(min(1,t+.001))-point(max(0,t-.001))).normalized()
        normal=Vector((p.x,p.y-.005,0)).normalized()
        across=normal.cross(tangent).normalized()
        normal=tangent.cross(across).normalized()
        width=.0003+interpolate(t,[(w,) for w in widths])[0]
        if sculpted:
            width *= .04 + .96*smooth(t/.14)
        depth=min(.005 if refined else .008,width*(.24 if refined else .38))
        for j in range(cross):
            angle=j/cross*2*pi
            p2=p+across*width*cos(angle)+normal*depth*sin(angle)
            p2=fit_scalp(p2)
            vertices.append(tuple(p2)); ts.append(t)
    for i in range(steps):
        for j in range(cross):
            a=i*cross+j; b=i*cross+(j+1)%cross
            faces.append((a,b,b+cross,a+cross))
    faces.extend([tuple(reversed(range(cross))),tuple(steps*cross+j for j in range(cross))])
    return mesh_object(name,vertices,faces,material,rig,
                       lambda i,p:chain_weights(ts[i],chain))
