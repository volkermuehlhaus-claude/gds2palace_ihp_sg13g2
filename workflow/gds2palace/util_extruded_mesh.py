"""Extruded mesh for Elmer thermal models: settings['thermal_mesh'] = 'extruded'.

A chip is a stack of flat layers. Instead of building the 3D geometry and filling it with tetrahedra, the extruded
mesh is built in three steps:

1. The outlines of everything in the model (drawn layers, the dielectric boxes of the stackup, heat sources and
   constant-temperature boundaries) are cut into faces that don't overlap. Inside one face, each layer is either
   there or not.
2. gmsh meshes these faces in 2D.
3. The triangles are repeated at every z level of the stackup, as rows of prisms (wedges). Each prism gets the body
   of whatever is at its place and height, with the same rules as the tetrahedral mesh where things overlap.

gmsh's 3D mesher is never used, so thin layers over a large area (drawn metal planes, filler-equivalent slabs), which
make it fail ("Could not recover boundary mesh", empty volumes), can't stop the model. The price: the cells in the
plane are the same on every layer, so the fine cells at a heat source run through the whole stack, and the rows in z
run through the whole chip.

The mesh is built as discrete entities in the current gmsh model, with the same physical groups (names, layer names,
via fill factors) as the tetrahedral mesh, so the Elmer files are written by the same code.
"""
import math

import gmsh
import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely.ops import polygonize, unary_union


def _polygonal (geometry):
    """The polygons of a shapely geometry (a snapped shape can come back as a collection with lines or points)."""
    parts = [g for g in shapely.get_parts(geometry) if g.geom_type == 'Polygon' and not g.is_empty]
    return shapely.MultiPolygon(parts) if parts else None


def _shape_of (poly, grid):
    """Shapely shape of a gds_polygon, snapped to the grid. Self-touching keyhole polygons (holes, or pieces bridged
    together) become proper polygons with holes."""
    shape = Polygon(np.column_stack([poly.pts_x, poly.pts_y])).buffer(0)
    return _polygonal(shapely.set_precision(shape, grid) if grid > 0 else shape)


def _round_grid (value):
    """value rounded down to 1, 2 or 5 times a power of ten, so that layout coordinates stay on it"""
    power = 10 ** math.floor(math.log10(value))
    return max(step * power for step in (1, 2, 5) if step * power <= value * (1 + 1e-9))


def _snap_box (xmin, ymin, xmax, ymax, grid):
    return _polygonal(shapely.set_precision(box(xmin, ymin, xmax, ymax), grid) if grid > 0 else box(xmin, ymin, xmax, ymax))


def build_extruded_thermal_mesh (allpolygons, metals_list, materials_list, dielectrics_list, thermal_objects, margin,
                                 refined_cellsize, refined_cellsize_override_dict, max_cellsize, unit, grid,
                                 fill_factor_correction, growth):
    """Build the extruded mesh in the current gmsh model.

    Args:
        allpolygons, metals_list, materials_list, dielectrics_list, thermal_objects: model data, as for create_model()
        margin (tuple): dielectric oversize per side (xmin, xmax, ymin, ymax), from margin_per_side()
        refined_cellsize (float): cell size at the heat sources
        refined_cellsize_override_dict (dict): per heat source (source_<layer>) or metal layer: its own cell size
            (metal layers: refinement along their edges)
        max_cellsize (float): the largest cell size
        unit (float): drawing unit in m
        grid (float): all outlines are snapped to this grid first, in drawing units (0: no snapping)
        fill_factor_correction (bool): via layers are split into groups of similar fill factor
        growth (float): the cell size grows by this much per unit of distance from a refined region

    Returns:
        physical_groups_3D, physical_groups_2D: lists of dicts as in create_model() (layername, groupname,
        grouptag, and fill_factor for 3D)
    """
    from .util_simulation_setup import (_bucket_by_fill_factor, _boundary_target_layer, _boxes_overlap,
                                        _source_target_layer, _thermal_conductivity_info, _is_pec_material)

    tolerance = 1e-9 / unit   # 1 nm: z positions closer than this are the same plane

    # ------------------------------------------------------------------ what is in the model
    # every item is a shape in the plane with a z range, a body (physical group) and a rank: where items overlap,
    # the highest rank wins, at equal rank the later item. The ranks follow _overlap_class() of the tetrahedral
    # mesh: <Dielectric>s, then drawn dielectric layers (a <Dielectric> with a higher Priority wins over them),
    # then vias and conductors by Priority (a conductor over a via), then heat sources.
    items = []
    boundaries = {}   # constant-temperature boundaries: name -> [target layer name, [shapes], [z, ...]]

    margin_xmin, margin_xmax, margin_ymin, margin_ymax = margin
    stack_boxes = {}
    for dielectric in dielectrics_list.dielectrics:
        if dielectric.gdsboundary is None:
            xmin, xmax, ymin, ymax = allpolygons.get_bounding_box()
        else:
            xmin, xmax, ymin, ymax = allpolygons.bounding_box.get_layer_bounding_box(int(dielectric.gdsboundary))
        xmin, xmax, ymin, ymax = xmin - margin_xmin, xmax + margin_xmax, ymin - margin_ymin, ymax + margin_ymax
        stack_boxes[dielectric.name] = (xmin, ymin, dielectric.zmin, xmax, ymax, dielectric.zmax)
        items.append(dict(shape=_snap_box(xmin, ymin, xmax, ymax, grid), zmin=dielectric.zmin, zmax=dielectric.zmax,
                          layername=dielectric.name, group=dielectric.name, rank=(0, dielectric.priority, 0)))
    names = list(stack_boxes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa, pb = dielectrics_list.get_by_name(a).priority, dielectrics_list.get_by_name(b).priority
            if pa == pb and _boxes_overlap(stack_boxes[a], stack_boxes[b]):
                print(f'ERROR: Dielectrics "{a}" and "{b}" overlap and have the same Priority ({pa}). '
                      'Give the one that should fill the overlap a higher Priority in the stackup XML file.')
                exit(51)

    # heat sources get a finer grid if they are small: a transistor's heat source can be narrower than the grid of the
    # layout (an npn13G2 emitter is 0.07 um wide). 1/20 of their smallest side keeps their area within a few percent.
    source_sides = [min(poly.xmax - poly.xmin, poly.ymax - poly.ymin) for poly in allpolygons.polygons
                    if metals_list.getallbylayernumber(poly.layernum) is None and poly.layernum in thermal_objects.layers
                    and getattr(thermal_objects.get_object_by_layernumber(poly.layernum), 'type', None) == 'source']
    source_sides = [side for side in source_sides if side > 0]
    source_grid = min([grid] + [_round_grid(side / 20) for side in source_sides]) if grid > 0 else 0
    if source_grid < grid:
        print(f'Extruded mesh: heat sources snapped to a {source_grid:g} grid (smallest side {min(source_sides):g}), '
              f'everything else to {grid:g}')

    via_polygons = {}   # via layer name -> [(item index, fill factor)]
    for poly in allpolygons.polygons:
        layers = metals_list.getallbylayernumber(poly.layernum)
        if layers is not None:
            shape = None
            for layer in layers:
                if layer.is_sheet or layer.zmax - layer.zmin <= 0:
                    continue   # sheets have no volume; a PEC sheet is ignored in thermal models anyway
                shape = shape or _shape_of(poly, grid)
                if shape is None:
                    continue
                if layer.is_dielectric:
                    rank = (0, layer.priority, 1)
                else:
                    rank = (1, layer.priority, 0 if layer.is_via else 1)
                items.append(dict(shape=shape, zmin=layer.zmin, zmax=layer.zmax, layername=layer.name, group=layer.name,
                                  rank=rank))
                if layer.is_via and fill_factor_correction:
                    via_polygons.setdefault(layer.name, []).append((len(items) - 1, poly.fill_factor))
        elif poly.layernum in thermal_objects.layers:
            thermal_object = thermal_objects.get_object_by_layernumber(poly.layernum)
            if thermal_object is None:
                continue
            if thermal_object.type == 'source':
                # a heat source is the bounding box of its polygon, as in the tetrahedral mesh
                target = _source_target_layer(thermal_object, metals_list)
                items.append(dict(shape=_snap_box(poly.xmin, poly.ymin, poly.xmax, poly.ymax, source_grid), zmin=target.zmin,
                                  zmax=target.zmax, layername=target.name,
                                  group=f'source_{thermal_object.source_layernum}', rank=(2, 0, 0)))
            elif thermal_object.type == 'constanttemp':
                target = _boundary_target_layer(thermal_object, metals_list)
                shape = _shape_of(poly, grid)
                if shape is not None:
                    planes = [target.zmin] + ([target.zmax] if target.zmax != target.zmin else [])
                    boundaries.setdefault(f'constanttemp_{thermal_object.source_layernum}',
                                          [target.name, [], planes])[1].append(shape)
    boundaries = {name: (target, unary_union(shapes), planes) for name, (target, shapes, planes) in boundaries.items()}

    # via layers split by fill factor: one group per range of similar fill factor, as in the tetrahedral mesh
    fill_factor_of_group = {}
    for layername, pairs in via_polygons.items():
        buckets = _bucket_by_fill_factor(pairs)
        via_metal = metals_list.getbylayername(layername)
        via_material = materials_list.get_by_name(via_metal.material)
        print(f'Fill factor correction for via layer {layername}: {len(buckets)} group(s)')
        used = set()
        for i, bucket in enumerate(buckets):
            groupname = f'{layername}_x{bucket["mean_fill_factor"]:.2f}'
            if groupname in used:
                groupname = f'{groupname}_{i}'
            used.add(groupname)
            fill_factor_of_group[groupname] = bucket['mean_fill_factor']
            for index in bucket['tags']:
                items[index]['group'] = groupname
            if _is_pec_material(via_metal.material):
                info = 'PEC material'
            elif via_material is not None:
                info = _thermal_conductivity_info(via_material, bucket['mean_fill_factor'])
            else:
                info = f'material {via_metal.material} not found'
            print(f'  {groupname}: {len(bucket["tags"])} polygon(s), mean fill factor {bucket["mean_fill_factor"]:.3f}, {info}')

    # one shape per layer and body: the layout reader cuts large polygons into pieces, and every cut would be an
    # edge of the 2D mesh. Merged items keep the place of their first piece (for the order at equal rank).
    merged = {}
    for item in items:
        if item['shape'] is None:
            continue
        key = (item['layername'], item['group'], item['zmin'], item['zmax'], item['rank'])
        merged.setdefault(key, dict(item, shapes=[]))['shapes'].append(item['shape'])
    items = []
    for item in merged.values():
        item['shape'] = _polygonal(unary_union(item.pop('shapes')))
        if item['shape'] is not None:
            items.append(item)

    # ------------------------------------------------------------------ z planes and rows of prisms
    zs = sorted([z for item in items for z in (item['zmin'], item['zmax'])] +
                [z for _, _, zlist in boundaries.values() for z in zlist])
    planes = [zs[0]]
    for z in zs[1:]:
        if z - planes[-1] > tolerance:
            planes.append(z)
    slices = list(zip(planes[:-1], planes[1:]))

    sources = [item for item in items if item['group'].startswith('source_')]

    def source_size (item):
        return refined_cellsize_override_dict.get(item['group'], refined_cellsize)

    def size_in_z (z):
        """the cell size wanted at height z: grows from each heat source (its box grown by its cell size, as the gmsh
        Box field of the tetrahedral mesh) by growth per unit of distance"""
        size = max_cellsize
        for item in sources:
            s = source_size(item)
            d = max(item['zmin'] - s - z, z - item['zmax'] - s, 0.0)
            size = min(size, s + growth * d)
        return size

    z_levels, row_slice = [planes[0]], []
    for s, (z0, z1) in enumerate(slices):
        zz = np.linspace(z0, z1, 401)
        mid = 0.5 * (zz[1:] + zz[:-1])
        steps = np.concatenate([[0.0], np.cumsum(np.diff(zz) / np.array([size_in_z(z) for z in mid]))])
        n = max(1, math.ceil(steps[-1] - 1e-9))
        z_levels += list(np.interp(np.linspace(0, steps[-1], n + 1)[1:], steps, zz))
        z_levels[-1] = z1   # exactly on the plane
        row_slice += [s] * n
    z_levels = np.array(z_levels)
    row_slice = np.array(row_slice)
    level_of_plane = {z: int(np.argmin(abs(z_levels - z))) for z in planes}

    # ------------------------------------------------------------------ faces in the plane
    lines = [item['shape'].boundary for item in items] + [shape.boundary for _, shape, _ in boundaries.values()]
    noded = unary_union(lines)
    if grid > 0:
        # the points where edges of different layers cross are not on the grid: snap them too, else almost collinear
        # points make triangles without area, and node again where snapping made edges meet
        noded = unary_union(shapely.set_precision(noded, source_grid))
    faces = [f for f in polygonize(shapely.get_parts(noded)) if f.area > tolerance ** 2]
    points = [f.representative_point() for f in faces]
    tree = shapely.STRtree([item['shape'] for item in items])
    point_index, item_index = tree.query(points, predicate='within')
    items_of_face = [[] for _ in faces]
    for p, i in zip(point_index, item_index):
        items_of_face[p].append(i)
    faces_kept = [n for n in range(len(faces)) if items_of_face[n]]   # a face that nothing covers is a hole
    faces = [faces[n] for n in faces_kept]
    items_of_face = [items_of_face[n] for n in faces_kept]
    points = [points[n] for n in faces_kept]

    # slivers: a face thinner than half the grid lies between edges of two layers that almost coincide (e.g. a slanted
    # edge passing a few nm from a corner). gmsh can only fill it with triangles without area, so it joins the
    # neighbour it shares the longest edge with, and takes that neighbour's layers. Below the grid, it isn't geometry.
    if grid > 0:
        owner = list(range(len(faces)))

        def find (n):
            while owner[n] != n:
                n = owner[n]
            return n

        face_tree = shapely.STRtree(faces)
        thin = [n for n, f in enumerate(faces) if 2 * f.area / f.length < grid / 2]
        for n in sorted(thin, key=lambda n: faces[n].area):
            if find(n) != n:
                continue
            best, shared_best = None, 0.0
            for m in face_tree.query(faces[n]):
                m = find(int(m))
                if m == n:
                    continue
                shared = faces[n].boundary.intersection(faces[m].boundary).length
                if shared > shared_best:
                    best, shared_best = m, shared
            if best is not None:
                faces[best] = unary_union([faces[best], faces[n]])
                owner[n] = best
        kept = [n for n in range(len(faces)) if owner[n] == n]
        if len(kept) < len(faces):
            print(f'Extruded mesh: {len(faces) - len(kept)} sliver(s) thinner than {grid / 2:g} joined to a neighbour')
        faces = [_polygonal(faces[n]).geoms[0] if faces[n].geom_type != 'Polygon' else faces[n] for n in kept]
        items_of_face = [items_of_face[n] for n in kept]
        points = [points[n] for n in kept]

    # body of each face on each slice: the highest rank among the items there, at equal rank the later item
    groups = []
    group_of = {}
    face_group = np.full((len(slices), len(faces)), -1, dtype=np.int64)
    for s, (z0, z1) in enumerate(slices):
        zm = 0.5 * (z0 + z1)
        for f, candidates in enumerate(items_of_face):
            best = None
            for i in candidates:
                item = items[i]
                if item['zmin'] - tolerance <= zm <= item['zmax'] + tolerance:
                    if best is None or (item['rank'], i) > (items[best]['rank'], best):
                        best = i
            if best is not None:
                key = items[best]['group']
                if key not in group_of:
                    group_of[key] = len(groups)
                    groups.append((key, items[best]['layername']))
                face_group[s, f] = group_of[key]

    # ------------------------------------------------------------------ 2D mesh
    main_model = gmsh.model.getCurrent()
    gmsh.model.add('extruded_mesh_plane')
    point_tag, line_tag = {}, {}

    def point (c):
        key = (round(c[0], 9), round(c[1], 9))
        if key not in point_tag:
            point_tag[key] = gmsh.model.geo.addPoint(key[0], key[1], 0, max_cellsize)
        return point_tag[key]

    def curve_loop (ring):
        coords = list(ring.coords)
        tags = []
        for a, b in zip(coords[:-1], coords[1:]):
            pa, pb = point(a), point(b)
            if pa == pb:
                continue
            if (pa, pb) in line_tag:
                tags.append(line_tag[(pa, pb)])
            elif (pb, pa) in line_tag:
                tags.append(-line_tag[(pb, pa)])
            else:
                line_tag[(pa, pb)] = gmsh.model.geo.addLine(pa, pb)
                tags.append(line_tag[(pa, pb)])
        return gmsh.model.geo.addCurveLoop(tags)

    surface_of_face = []
    for f in faces:
        loops = [curve_loop(f.exterior)] + [curve_loop(r) for r in f.interiors]
        surface_of_face.append(gmsh.model.geo.addPlaneSurface(loops))
    gmsh.model.geo.synchronize()

    # cell size: Box fields at the heat sources and Distance fields along the edges of metal layers with their own
    # size, as in the tetrahedral mesh, growing by growth per unit of distance
    fields = []

    def transition (size):
        return max(max_cellsize - size, 0) / growth

    for item in sources:
        s = source_size(item)
        xmin, ymin, xmax, ymax = item['shape'].bounds
        field = gmsh.model.mesh.field.add('Box')
        for name, value in (('VIn', s), ('VOut', max_cellsize), ('XMin', xmin - s), ('XMax', xmax + s),
                            ('YMin', ymin - s), ('YMax', ymax + s), ('ZMin', -1), ('ZMax', 1),
                            ('Thickness', transition(s))):
            gmsh.model.mesh.field.setNumber(field, name, value)
        fields.append(field)
    source_groups = {item['group'] for item in sources}
    coordinate_of = {tag: c for c, tag in point_tag.items()}
    line_list = [(np.array(coordinate_of[pa]), np.array(coordinate_of[pb]), tag) for (pa, pb), tag in line_tag.items()]
    middles = shapely.points([(a + b) / 2 for a, b, _ in line_list])
    for key, size in refined_cellsize_override_dict.items():
        if key in source_groups:
            print(f'Mesh size at heat source {key}: {size}')
            continue
        outline = [item['shape'].boundary for item in items if item['layername'] == key and not key.startswith('source_')]
        if not outline:
            print(f'WARNING: refined_cellsize_override: {key} is neither a heat source nor a metal layer of this model, '
                  'ignored')
            continue
        print(f'Edge refinement of {key}: {size}')
        on_edge = shapely.distance(middles, unary_union(outline)) < tolerance
        edges = [(a, b, tag) for (a, b, tag), keep in zip(line_list, on_edge) if keep]
        if not edges:
            continue
        distance = gmsh.model.mesh.field.add('Distance')
        gmsh.model.mesh.field.setNumbers(distance, 'CurvesList', [tag for _, _, tag in edges])
        # samples at most size/2 apart on the longest edge (all edges of a field get the same number)
        longest = max(float(np.linalg.norm(b - a)) for a, b, _ in edges)
        gmsh.model.mesh.field.setNumber(distance, 'Sampling', max(2, math.ceil(longest / (size / 2)) + 1))
        threshold = gmsh.model.mesh.field.add('Threshold')
        for name, value in (('InField', distance), ('SizeMin', size), ('SizeMax', max_cellsize), ('DistMin', 0),
                            ('DistMax', transition(size))):
            gmsh.model.mesh.field.setNumber(threshold, name, value)
        fields.append(threshold)
    constant = gmsh.model.mesh.field.add('MathEval')
    gmsh.model.mesh.field.setString(constant, 'F', f'{max_cellsize}')
    fields.append(constant)
    smallest = gmsh.model.mesh.field.add('Min')
    gmsh.model.mesh.field.setNumbers(smallest, 'FieldsList', fields)
    gmsh.model.mesh.field.setAsBackgroundMesh(smallest)
    for option in ('Mesh.MeshSizeExtendFromBoundary', 'Mesh.MeshSizeFromPoints', 'Mesh.MeshSizeFromCurvature'):
        gmsh.option.setNumber(option, 0)
    gmsh.option.setNumber('Mesh.Algorithm', 6)
    print(f'Extruded mesh: {len(faces)} faces in the plane, {len(slices)} layers in z')
    gmsh.model.mesh.generate(2)

    node_tags, node_xyz, _ = gmsh.model.mesh.getNodes()
    index = np.zeros(int(node_tags.max()) + 1, dtype=np.int64)
    index[node_tags.astype(np.int64)] = np.arange(len(node_tags))
    xy = node_xyz.reshape(-1, 3)[:, :2]
    triangles, triangle_face = [], []
    for f, surface in enumerate(surface_of_face):
        types, _, element_nodes = gmsh.model.mesh.getElements(2, surface)
        for element_type, nodes in zip(types, element_nodes):
            if element_type == 2:
                t = index[nodes.astype(np.int64)].reshape(-1, 3)
                triangles.append(t)
                triangle_face.append(np.full(len(t), f))
    gmsh.model.remove()
    gmsh.model.setCurrent(main_model)
    triangles = np.concatenate(triangles)
    triangle_face = np.concatenate(triangle_face)
    a = xy[triangles[:, 1]] - xy[triangles[:, 0]]
    b = xy[triangles[:, 2]] - xy[triangles[:, 0]]
    clockwise = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0] < 0
    triangles[clockwise] = triangles[clockwise][:, [0, 2, 1]]   # counter-clockwise: prisms with positive volume

    def flat_triangles ():
        """triangles whose corners are (almost) on one line: their prisms Elmer rejects ("Degenerate 3D element")"""
        p0, p1, p2 = xy[triangles[:, 0]], xy[triangles[:, 1]], xy[triangles[:, 2]]
        cross = (p1 - p0)[:, 0] * (p2 - p0)[:, 1] - (p1 - p0)[:, 1] * (p2 - p0)[:, 0]
        longest = np.sqrt(np.maximum.reduce([((p1 - p0) ** 2).sum(1), ((p2 - p1) ** 2).sum(1), ((p0 - p2) ** 2).sum(1)]))
        return np.flatnonzero(abs(cross) / longest < 1e-3 * max(grid, tolerance))

    # gmsh leaves such a triangle where a hole of a face touches its outline at one point on a straight edge: three
    # mesh nodes a, v, b on that edge. It covers no area: remove it, and split the triangle on the other side of its
    # long edge a-b at v, so the mesh stays conforming
    flat = flat_triangles()
    if len(flat):
        by_edge = {}
        for t, (i, j, k) in enumerate(triangles):
            for e in ((i, j), (j, k), (k, i)):
                by_edge.setdefault(frozenset(e), []).append(t)
        removed, extra, extra_face = set(), [], []
        for t in flat:
            corners = list(triangles[t])
            lengths = [np.sum((xy[corners[(i + 1) % 3]] - xy[corners[(i + 2) % 3]]) ** 2) for i in range(3)]
            v = corners[int(np.argmax(lengths))]            # the middle node, opposite the long edge a-b
            a_, b_ = [c for c in corners if c != v]
            others = [s for s in by_edge.get(frozenset((a_, b_)), []) if s != t and s not in removed]
            removed.add(t)
            if others:
                s = others[0]
                c = [n for n in triangles[s] if n not in (a_, b_)][0]
                removed.add(s)
                for p, q in ((a_, v), (v, b_)):
                    tri = [p, q, c]
                    pa, pb, pc = xy[tri[0]], xy[tri[1]], xy[tri[2]]
                    if (pb - pa)[0] * (pc - pa)[1] - (pb - pa)[1] * (pc - pa)[0] < 0:
                        tri = [q, p, c]
                    extra.append(tri)
                    extra_face.append(triangle_face[s])
        keep = np.array([t not in removed for t in range(len(triangles))])
        triangles = np.vstack([triangles[keep]] + ([np.array(extra)] if extra else []))
        triangle_face = np.concatenate([triangle_face[keep], np.array(extra_face, dtype=triangle_face.dtype)])
        print(f'Extruded mesh: {len(flat)} triangle(s) without area removed (where a hole touches its outline)')

    # anything left: stop here and say where, before a mesh is written
    flat = flat_triangles()
    if len(flat):
        print(f'ERROR: the 2D mesh of the extruded thermal mesh has {len(flat)} triangle(s) without area, '
              'at (x, y) in drawing units:')
        for n in flat[:10]:
            centre = xy[triangles[n]].mean(axis=0)
            print(f'   ({centre[0]:.3f}, {centre[1]:.3f})')
        print("   Edges of different layers almost meet there. A coarser grid for the outlines helps, e.g. "
              f"settings['thermal_mesh_grid'] = {10 * grid:g} (now {grid:g}). No mesh file is written.")
        exit(1)
    used = np.unique(triangles)
    renumber = np.full(len(xy), -1)
    renumber[used] = np.arange(len(used))
    xy, triangles = xy[used], renumber[triangles]

    # ------------------------------------------------------------------ prisms
    n2, n_rows = len(xy), len(row_slice)
    prism_group = face_group[row_slice][:, triangle_face]   # (rows, triangles), -1 = nothing there
    coords = np.column_stack([np.tile(xy, (n_rows + 1, 1)), np.repeat(z_levels, n2)])
    n_nodes = len(coords)
    print(f'Extruded mesh: {len(triangles)} triangles x {n_rows} rows of prisms, {n_nodes:,} nodes, '
          f'thinnest layer {min(z1 - z0 for z0, z1 in slices) * unit * 1e9:.0f} nm')

    entities = {}
    for g, (groupname, _) in enumerate(groups):
        entities[g] = gmsh.model.addDiscreteEntity(3)
    # all nodes on the entity of the first group: the element connectivity is what counts
    gmsh.model.mesh.addNodes(3, entities[0], np.arange(1, n_nodes + 1), coords.reshape(-1))
    next_element = 1
    rows = np.repeat(np.arange(n_rows), len(triangles))
    bottom = (np.tile(triangles, (n_rows, 1)) + (rows * n2)[:, None] + 1)
    top = bottom + n2
    flat_group = prism_group.reshape(-1)
    physical_groups_3D = []
    prism_count = 0
    for g, (groupname, layername) in enumerate(groups):
        mask = flat_group == g
        count = int(mask.sum())
        if count == 0:
            continue
        nodes = np.column_stack([bottom[mask], top[mask]]).reshape(-1)
        gmsh.model.mesh.addElementsByType(entities[g], 6, np.arange(next_element, next_element + count), nodes)
        next_element += count
        prism_count += count
        group_tag = gmsh.model.addPhysicalGroup(3, [entities[g]])
        gmsh.model.setPhysicalName(3, group_tag, groupname)
        physical_groups_3D.append({"layername": layername, "groupname": groupname, "grouptag": group_tag,
                                   "fill_factor": fill_factor_of_group.get(groupname, 1.0)})
    print(f'Extruded mesh: {prism_count:,} prisms in {len(physical_groups_3D)} bodies')

    # ------------------------------------------------------------------ constant-temperature boundaries
    physical_groups_2D = []
    points_array = np.array(points, dtype=object)
    for name, (target_name, shape, zlist) in boundaries.items():
        inside = shapely.within(points_array, shape)
        triangle_nodes = []
        for z in zlist:
            plane = min(planes, key=lambda p: abs(p - z))
            level = level_of_plane[plane]
            # a face of the plane that has a prism above or below it
            below = prism_group[level - 1] if level > 0 else np.full(len(triangles), -1)
            above = prism_group[level] if level < n_rows else np.full(len(triangles), -1)
            keep = inside[triangle_face] & ((below >= 0) | (above >= 0))
            triangle_nodes.append(triangles[keep] + level * n2 + 1)
        triangle_nodes = np.concatenate(triangle_nodes) if triangle_nodes else np.zeros((0, 3), dtype=np.int64)
        if len(triangle_nodes) == 0:
            print(f'WARNING: constant-temperature boundary {name} touches no part of the model')
            continue
        surface = gmsh.model.addDiscreteEntity(2)
        gmsh.model.mesh.addElementsByType(surface, 2, np.arange(next_element, next_element + len(triangle_nodes)),
                                          triangle_nodes.reshape(-1))
        next_element += len(triangle_nodes)
        group_tag = gmsh.model.addPhysicalGroup(2, [surface])
        gmsh.model.setPhysicalName(2, group_tag, name)
        physical_groups_2D.append({"layername": target_name, "groupname": name, "grouptag": group_tag})
    return physical_groups_3D, physical_groups_2D
