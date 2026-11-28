"""Elmer thermal models with settings['thermal_mesh'] = 'extruded' (util_extruded_mesh.py): a 2D mesh of all outlines,
repeated as prisms at every z level. Checks that the bodies and the Elmer case.sif are the same as with the
tetrahedral mesh, that every body has the right volume (including where layers overlap), and that the
constant-temperature boundary covers its polygon. Elmer itself does not run here.

    python -m pytest tests/test_extruded_thermal_mesh.py
"""
import os
import re
import sys

import gdstk
import gmsh
import numpy as np
import pytest

from gds2palace import gds_reader, simulation_setup, stackup_reader, utilities

STACKUP = utilities.get_stackup_path("SG13G2_FEM_200um.xml")
ACTIV = ((0, 0), (40, 30))
SOURCE = ((10, 10), (20, 16))
METAL1 = ((-5, -5), (45, 35))
VIA1 = ((30, 20), (34, 24))
METAL2 = ((25, 15), (60, 40))
MARGIN = 10.0


def layout(path):
    """Activ with a heat source inside it (202, on HEAT_TRANSISTOR, the top 40 nm of Activ), Metal1 over it, a
    Via1 up to a Metal2 that reaches beyond, and the backside held at constant temperature (203)."""
    lib = gdstk.Library()
    cell = lib.new_cell("device")
    for (a, b), layer in ((ACTIV, 1), (SOURCE, 202), (METAL1, 8), (VIA1, 19), (METAL2, 10)):
        cell.add(gdstk.rectangle(a, b, layer=layer))
    cell.add(gdstk.rectangle((-5, -5), (60, 40), layer=203))
    lib.write_gds(path)


def build(tmp_path, thermal_mesh):
    gds = str(tmp_path / "device.gds")
    layout(gds)
    materials, dielectrics, metals = stackup_reader.read_substrate(STACKUP)
    thermal_objects = simulation_setup.all_thermal_objects()
    thermal_objects.add_heatsource(simulation_setup.heatsource(power=0.01, source_layernum=202,
                                                               target_layername="HEAT_TRANSISTOR"))
    thermal_objects.add_consttemp(simulation_setup.constanttemp(temp=300.0, source_layernum=203,
                                                                target_layername="BACKSIDEGND"))
    layernumbers = metals.getlayernumbers() + thermal_objects.layers
    polygons = gds_reader.read_gds(gds, layernumbers, purposelist=[0], metals_list=metals)
    sim_path = str(tmp_path / thermal_mesh)
    os.makedirs(sim_path, exist_ok=True)
    settings = {"unit": 1e-6, "margin": MARGIN, "refined_cellsize": 2.0, "meshsize_max": 20.0, "no_gui": True,
                "thermal_mesh": thermal_mesh, "thermal_objects": thermal_objects, "materials_list": materials,
                "dielectrics_list": dielectrics, "metals_list": metals, "layernumbers": layernumbers,
                "allpolygons": polygons, "sim_path": sim_path, "model_basename": "device"}
    try:
        simulation_setup.create_elmer_thermal(settings)
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()
    return sim_path, metals, dielectrics


def area(rect):
    (x0, y0), (x1, y1) = rect
    return (x1 - x0) * (y1 - y0)


def sif_blocks(text, kind):
    return re.findall(rf'^{kind} \d+\n(.*?)^End', text, flags=re.M | re.S)


def bodies_and_materials(sim_path):
    """{body name: (its material block without the number, body force)} and the boundary conditions of case.sif"""
    text = open(os.path.join(sim_path, "case.sif")).read()
    materials = sif_blocks(text, "Material")
    bodies = {}
    for block in sif_blocks(text, "Body"):
        name = re.search(r'Name = "(.*?)"', block).group(1)
        material = materials[int(re.search(r'Material = (\d+)', block).group(1)) - 1]
        bodies[name] = (material, 'Body Force' in block)
    return bodies, sif_blocks(text, "Boundary Condition")


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("extruded")
    return {kind: build(tmp_path, kind) for kind in ("extruded", "tetrahedral")}


def mesh_of(sim_path):
    """volume per physical group of the prism mesh, prism heights and bottom areas, constant-temperature triangles"""
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.open(os.path.join(sim_path, "device.msh"))
        tags, coords, _ = gmsh.model.mesh.getNodes()
        xyz = np.zeros((int(tags.max()) + 1, 3))
        xyz[tags.astype(int)] = coords.reshape(-1, 3)
        volumes, heights, areas, boundary = {}, [], [], {}
        for dim, group in gmsh.model.getPhysicalGroups():
            name = gmsh.model.getPhysicalName(dim, group)
            for entity in gmsh.model.getEntitiesForPhysicalGroup(dim, group):
                types, _, nodes = gmsh.model.mesh.getElements(dim, entity)
                for element_type, element_nodes in zip(types, nodes):
                    if dim == 3:
                        assert element_type == 6, "the extruded mesh has prisms only"
                        p = xyz[element_nodes.astype(int)].reshape(-1, 6, 3)
                        a, b = p[:, 1, :2] - p[:, 0, :2], p[:, 2, :2] - p[:, 0, :2]
                        bottom = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / 2
                        height = p[:, 3, 2] - p[:, 0, 2]
                        heights.append(height)
                        areas.append(bottom)
                        volumes[name] = volumes.get(name, 0.0) + float((bottom * height).sum())
                    else:
                        p = xyz[element_nodes.astype(int)].reshape(-1, 3, 3)
                        a, b = p[:, 1, :2] - p[:, 0, :2], p[:, 2, :2] - p[:, 0, :2]
                        boundary.setdefault(name, []).append((abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / 2, p[:, :, 2]))
        return volumes, np.concatenate(heights), np.concatenate(areas), boundary
    finally:
        gmsh.finalize()


def test_same_bodies_and_case_sif_as_the_tetrahedral_mesh(models):
    extruded, _, _ = models["extruded"]
    tetrahedral, _, _ = models["tetrahedral"]
    assert bodies_and_materials(extruded) == bodies_and_materials(tetrahedral)
    assert bodies_and_materials(extruded)[0]["source_202"][1], "the heat source has its body force"


def test_every_prism_points_up_and_has_an_area(models):
    _, heights, areas, _ = mesh_of(models["extruded"][0])
    assert heights.min() > 0 and areas.min() > 0


def test_body_volumes(models):
    sim_path, metals, dielectrics = models["extruded"]
    volumes, _, _, _ = mesh_of(sim_path)
    thickness = {name: metals.getbylayername(name).thickness for name in ("Activ", "HEAT_TRANSISTOR", "Metal1", "Via1",
                                                                          "Metal2")}
    assert volumes["source_202"] == pytest.approx(area(SOURCE) * thickness["HEAT_TRANSISTOR"], rel=1e-9)
    # the heat source wins over Activ where they overlap (the top 40 nm of Activ), a conductor over a via
    assert volumes["Activ"] == pytest.approx(area(ACTIV) * thickness["Activ"] - area(SOURCE) * thickness["HEAT_TRANSISTOR"],
                                             rel=1e-9)
    for name, rect in (("Metal1", METAL1), ("Via1", VIA1), ("Metal2", METAL2)):
        assert volumes[name] == pytest.approx(area(rect) * thickness[name], rel=1e-9)
    # the dielectrics fill the rest of the box: the layout's bounding box with the margin, over the whole stack
    (x0, y0), (x1, y1) = (-5, -5), (60, 40)
    box = (x1 - x0 + 2 * MARGIN) * (y1 - y0 + 2 * MARGIN)
    height = max(d.zmax for d in dielectrics.dielectrics) - min(d.zmin for d in dielectrics.dielectrics)
    assert sum(volumes.values()) == pytest.approx(box * height, rel=1e-9)


def test_constant_temperature_boundary_covers_its_polygon(models):
    sim_path, _, _ = models["extruded"]
    _, _, _, boundary = mesh_of(sim_path)
    triangles = boundary["constanttemp_203"]
    total = sum(float(a.sum()) for a, _ in triangles)
    # the polygon, not the whole bottom of the model (which is larger by the margin)
    assert total == pytest.approx(65 * 45, rel=1e-9)
    assert all(np.allclose(z, 0.0) for _, z in triangles), "BACKSIDEGND is at z = 0"


def test_a_heat_source_narrower_than_the_grid_keeps_its_size(tmp_path, monkeypatch):
    """the outlines are snapped to 0.1 um, the heat sources to a grid from their smallest side: an npn13G2 emitter
    (0.07 x 0.9 um) would otherwise shrink to nothing or double"""
    monkeypatch.setattr(sys.modules[__name__], "SOURCE", ((10, 10), (10.07, 10.9)))
    sim_path, metals, _ = build(tmp_path, "extruded")
    volumes, _, _, _ = mesh_of(sim_path)
    assert volumes["source_202"] == pytest.approx(0.07 * 0.9 * metals.getbylayername("HEAT_TRANSISTOR").thickness,
                                                  rel=1e-9)


def test_unknown_mesh_type_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        build(tmp_path, "hexahedral")
