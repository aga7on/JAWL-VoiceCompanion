"""Contact fitting for wrist cuffs and boot shafts, in baked rest space."""
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_skin_cache = {}


def section_bounds(obj, axis, coordinate, material_index=None, side=None):
    points = []
    seen = set()
    for polygon in obj.data.polygons:
        if material_index is not None and polygon.material_index != material_index:
            continue
        for a, b in polygon.edge_keys:
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            p, q = obj.data.vertices[a].co, obj.data.vertices[b].co
            if side is not None and (p.x + q.x) * side <= 0:
                continue
            for endpoint in (p, q):
                if abs(endpoint[axis] - coordinate) < 1e-6:
                    points.append(endpoint)
            if (p[axis] - coordinate) * (q[axis] - coordinate) > 0:
                continue
            if abs(q[axis] - p[axis]) < 1e-8:
                continue
            points.append(p.lerp(q, (coordinate - p[axis]) / (q[axis] - p[axis])))
    if len(points) < 8:
        raise RuntimeError(f'Insufficient actual mesh section: {obj.name} / {coordinate}: {len(points)}')
    other = [i for i in range(3) if i != axis]
    low = [min(p[i] for p in points) for i in other]
    high = [max(p[i] for p in points) for i in other]
    return [(a + b) / 2 for a, b in zip(low, high)], [(b - a) / 2 for a, b in zip(low, high)]


def wrist_fit(body, side):
    skin = next(i for i, m in enumerate(body.data.materials) if 'Body_00_SKIN' in m.name)
    center, radii = section_bounds(body, 0, side * .557, material_index=skin)
    if not all(.006 < radius < .032 for radius in radii):
        raise RuntimeError(f'Unexpected wrist size: {side}, {radii}')
    return center, radii


def closest_skin_weights(body, point):
    # Endpoint is within 2 mm of the original source skin. Copy its binding
    # rather than moving the cuff exclusively with the forearm during flex.
    key = body.as_pointer()
    if key not in _skin_cache:
        skin = next(i for i, m in enumerate(body.data.materials) if 'Body_00_SKIN' in m.name)
        body.data.calc_loop_triangles()
        triangles = [tuple(t.vertices) for t in body.data.loop_triangles if t.material_index == skin]
        coords = [v.co.copy() for v in body.data.vertices]
        bindings = [{body.vertex_groups[g.group].name:g.weight for g in v.groups} for v in body.data.vertices]
        _skin_cache[key] = (BVHTree.FromPolygons(coords,triangles,all_triangles=True),triangles,coords,bindings)
    tree, triangles, coords, bindings = _skin_cache[key]
    location, _, index, _ = tree.find_nearest(Vector(point))
    if location is None:
        raise RuntimeError('Cuff has no source Skin surface')
    triangle = triangles[index]
    a,b,c = [coords[i] for i in triangle]
    e0,e1,delta = b-a,c-a,location-a
    aa,ab,bb = e0.dot(e0),e0.dot(e1),e1.dot(e1)
    denominator = aa*bb-ab*ab
    if denominator < 1e-14:
        raise RuntimeError('Degenerate source Skin triangle for cuff binding')
    w1 = (bb*delta.dot(e0)-ab*delta.dot(e1))/denominator
    w2 = (aa*delta.dot(e1)-ab*delta.dot(e0))/denominator
    weights = {}
    for vertex_id, amount in zip(triangle,(1-w1-w2,w1,w2)):
        for name, weight in bindings[vertex_id].items():
            weights[name] = weights.get(name,0)+max(0,amount)*weight
    return weights


def ankle_fit(pants, side):
    center, radii = section_bounds(pants, 2, .205, side=side)
    if not all(.012 < radius < .060 for radius in radii):
        raise RuntimeError(f'Unexpected pant hem section: {side}, {radii}')
    return center, radii


def fitted_section(obj, axis, coordinate, directions, clearance, material_index=None, side=None):
    """Sample the actual section contour; an ellipse can miss asymmetric corners."""
    center, _ = section_bounds(obj, axis, coordinate, material_index, side)
    other = [i for i in range(3) if i != axis]
    segments = []
    for polygon in obj.data.polygons:
        if material_index is not None and polygon.material_index != material_index:
            continue
        hits = []
        for a, b in polygon.edge_keys:
            p, q = obj.data.vertices[a].co, obj.data.vertices[b].co
            if side is not None and (p.x + q.x) * side <= 0:
                continue
            dp, dq = p[axis] - coordinate, q[axis] - coordinate
            if (dp > 1e-6 and dq > 1e-6) or (dp < -1e-6 and dq < -1e-6):
                continue
            if abs(dp) < 1e-6:
                hits.append(p)
            if abs(dq) < 1e-6:
                hits.append(q)
            if dp * dq < 0 and abs(q[axis] - p[axis]) >= 1e-8:
                hits.append(p.lerp(q, (coordinate - p[axis]) / (q[axis] - p[axis])))
        unique = []
        for point in hits:
            if not any((point - previous).length < 1e-7 for previous in unique):
                unique.append(point)
        if len(unique) == 2:
            segments.append(tuple(tuple(p[i] - center[k] for k, i in enumerate(other)) for p in unique))
    if not segments:
        raise RuntimeError(f'No section perimeter: {obj.name}/{coordinate}')
    cross = lambda a, b: a[0] * b[1] - a[1] * b[0]
    points = []
    for direction in directions:
        radii = []
        for p, q in segments:
            edge = (q[0] - p[0], q[1] - p[1])
            denominator = cross(direction, edge)
            if abs(denominator) < 1e-9:
                continue
            radius, along = cross(p, edge) / denominator, cross(p, direction) / denominator
            if radius > 0 and -.00001 <= along <= 1.00001:
                radii.append(radius)
        if not radii:
            raise RuntimeError(f'Uncovered contour direction: {obj.name}/{coordinate}/{direction}')
        radius = max(radii) + clearance
        point = [0., 0., 0.]
        point[axis] = coordinate
        for k, i in enumerate(other):
            point[i] = center[k] + direction[k] * radius
        points.append(tuple(point))
    return points
