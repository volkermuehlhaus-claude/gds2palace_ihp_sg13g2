"""Datatype per stackup layer (stackup reader 1.11.0, schemaVersion 3.2): a <Layer> with a Datatype is read from
that GDS datatype, whatever datatype list read_gds() gets; a layer without one follows that list. Two stackup layers
can share a GDS layer number with different datatypes (metal on 68/20, via on 68/44). Also Datatype on a derived
layer's <Operand> and BoundaryDatatype on a <Dielectric>.

    python -m pytest tests/test_datatype.py
"""
import os

import gdstk
import gmsh
import pytest

from gds2palace import gds_reader, simulation_setup, stackup_reader
from gds2palace.util_stackup_reader import layer_id, layer_text, split_layer_id

STACKUP = '''<?xml version="1.0" encoding="UTF-8"?>
<Stackup schemaVersion="3.2">
  <Materials>
    <Material Name="Ox" Type="Dielectric" Permittivity="4" ThermalConductivity="1" />
    <Material Name="Cu" Type="Conductor" Conductivity="5.8e7" ThermalConductivity="400" />
  </Materials>
  <ELayers LengthUnit="um">
    <Dielectrics>
      <Dielectric Name="Box" Material="Ox" Zmin="0" Zmax="10" Boundary="301" BoundaryDatatype="5" />
    </Dielectrics>
    <Layers>
      <Layer Name="M1" Type="conductor" Material="Cu" Layer="68" Datatype="20" Zmin="1" Zmax="2" />
      <Layer Name="V1" Type="via" Material="Cu" Layer="68" Datatype="44" Zmin="2" Zmax="3" />
      <Layer Name="M2" Type="conductor" Material="Cu" Layer="69" Zmin="3" Zmax="4" />
      <Layer Name="MD" Type="conductor" Material="Cu" Layer="310" Zmin="6" Zmax="7" />
      <Layer Name="BOTTOM" Type="sheet" Material="PEC" Layer="13" Zmin="0" Zmax="0" />
      {extra_layer}
    </Layers>
    <DerivedLayers>
      <DerivedLayer Name="MD" Layer="310" Operation="AND">
        <Operand Layer="68" Datatype="20" />
        <Operand Layer="70" {operand2} />
      </DerivedLayer>
    </DerivedLayers>
  </ELayers>
</Stackup>'''


def write_files(tmp_path, extra_layer="", operand2=""):
    """Layout: M1 10 x 10 on 68/20, two vias 1 x 1 on 68/44 (0.5 apart), a shape on 68/5 that no layer reads,
    M2 6 x 6 on 69/0 and 3 x 3 on 69/9, the AND partner on 70/0 (half of M1), the box outline on 301/5 and a
    larger shape on 301/0."""
    lib = gdstk.Library()
    cell = lib.new_cell("top")
    cell.add(gdstk.rectangle((0, 0), (10, 10), layer=68, datatype=20))
    cell.add(gdstk.rectangle((2, 2), (3, 3), layer=68, datatype=44))
    cell.add(gdstk.rectangle((3.5, 2), (4.5, 3), layer=68, datatype=44))
    cell.add(gdstk.rectangle((0, 0), (40, 40), layer=68, datatype=5))
    cell.add(gdstk.rectangle((1, 1), (7, 7), layer=69, datatype=0))
    cell.add(gdstk.rectangle((1, 1), (4, 4), layer=69, datatype=9))
    cell.add(gdstk.rectangle((5, 0), (15, 10), layer=70, datatype=0))
    cell.add(gdstk.rectangle((-20, -20), (30, 30), layer=301, datatype=5))
    cell.add(gdstk.rectangle((-50, -50), (50, 50), layer=301, datatype=0))
    cell.add(gdstk.rectangle((-20, -20), (30, 30), layer=13, datatype=0))
    cell.add(gdstk.rectangle((-20, -20), (30, 30), layer=201, datatype=0))
    gds = str(tmp_path / "layout.gds")
    lib.write_gds(gds)
    xml = tmp_path / "stackup.xml"
    xml.write_text(STACKUP.format(extra_layer=extra_layer, operand2=operand2), encoding="utf-8")
    return gds, str(xml)


def read(tmp_path, purposelist=None, merge=0, **kwargs):
    gds, xml = write_files(tmp_path, **kwargs)
    materials, dielectrics, metals = stackup_reader.read_substrate(xml)
    layers = metals.getlayernumbers() + [201]
    polygons = gds_reader.read_gds(gds, layers, purposelist, metals, merge_polygon_size=merge,
                                   gds_boundary_layers=dielectrics.get_boundary_layers())
    return materials, dielectrics, metals, polygons, layers


def area(polygons, metals, name):
    number = int(metals.getbylayername(name).layernum)
    return sum(gdstk.Polygon(list(zip(p.pts_x, p.pts_y))).area() for p in polygons.polygons if int(p.layernum) == number)


def test_layer_ids():
    assert layer_id(126) == 126 and split_layer_id(126) == (126, None) and layer_text(126) == "126"
    assert split_layer_id(layer_id(68, 20)) == (68, 20) and layer_text(layer_id(68, 20)) == "68/20"
    assert split_layer_id(layer_id(68, 0)) == (68, 0) and layer_id(68, 0) != 68
    assert layer_id(68, 20) == 10006800020                       # readable: 1 | 00068 | 00020
    assert split_layer_id(layer_id(65535, 65535)) == (65535, 65535)


def test_polygon_fields_and_layer_table(tmp_path, capsys):
    _, _, metals, polygons, _ = read(tmp_path)
    m1 = next(p for p in polygons.polygons if int(p.layernum) == int(metals.getbylayername("M1").layernum))
    m2 = next(p for p in polygons.polygons if int(p.layernum) == int(metals.getbylayername("M2").layernum))
    assert (m1.gds_layer, m1.gds_datatype) == (68, 20) and str(m1).startswith("Layer = 68/20,")
    assert (m2.gds_layer, m2.gds_datatype) == (69, None) and str(m2).startswith("Layer = 69,")
    capsys.readouterr()
    polygons.print_layers(metals)
    lines = [line.split() for line in capsys.readouterr().out.splitlines()]
    assert lines[0] == ["Stackup", "layer", "GDS", "layer", "Layer", "id", "Polygons"]
    assert ["M1", "68/20", "10006800020", "1"] in lines and ["V1", "68/44", "10006800044", "2"] in lines
    assert ["M2", "69", "69", "1"] in lines and ["-", "201", "201", "1"] in lines


def test_reader_layer_datatypes(tmp_path):
    _, xml = write_files(tmp_path)
    _, dielectrics, metals = stackup_reader.read_substrate(xml)
    assert metals.get_layer_datatypes() == {"M1": (68, 20), "V1": (68, 44), "M2": (69, None), "MD": (310, None),
                                            "BOTTOM": (13, None)}
    m1 = metals.getbylayername("M1")
    assert (m1.gds_layernum, m1.datatype) == ("68", 20)
    assert metals.getbylayernumber(m1.layernum) is m1          # the id finds only M1, not V1
    assert metals.getbylayername("M2").layernum == "69"        # no Datatype: the plain number, as before
    assert split_layer_id(dielectrics.get_boundary_layers()[0]) == (301, 5)


def test_two_layers_on_one_number_get_their_own_shapes(tmp_path):
    _, _, metals, polygons, _ = read(tmp_path)
    assert area(polygons, metals, "M1") == pytest.approx(100)
    assert area(polygons, metals, "V1") == pytest.approx(2)
    assert area(polygons, metals, "M2") == pytest.approx(36)      # 69/0, the default datatype
    assert area(polygons, metals, "MD") == pytest.approx(50)      # 68/20 AND 70/0


def test_stackup_datatype_wins_over_the_datatype_list(tmp_path):
    _, _, metals, polygons, _ = read(tmp_path, purposelist=[9])
    assert area(polygons, metals, "M1") == pytest.approx(100)     # still 68/20
    assert area(polygons, metals, "V1") == pytest.approx(2)
    assert area(polygons, metals, "M2") == pytest.approx(9)       # 69/9: no Datatype, follows the list
    assert area(polygons, metals, "MD") == pytest.approx(0)       # the operand 70 without Datatype follows the list


def test_boundary_datatype(tmp_path):
    _, dielectrics, _, polygons, _ = read(tmp_path)
    assert polygons.bounding_box.get_layer_bounding_box(dielectrics.get_boundary_layers()[0]) == (-20, 30, -20, 30)


def test_note_about_datatypes_not_read(tmp_path, capsys):
    read(tmp_path)
    out = capsys.readouterr().out
    assert "Note: GDS layer 68 (M1, V1): read 68/20, 68/44; in the file but not read: 68/5 (1 polygons)" in out
    assert "Note: GDS layer 69 (M2): read 69/0; in the file but not read: 69/9 (1 polygons)" in out


def test_via_merging_with_metal_and_via_on_one_number(tmp_path):
    _, _, metals, polygons, _ = read(tmp_path, merge=1.0)
    via = int(metals.getbylayername("V1").layernum)
    merged = [p for p in polygons.polygons if int(p.layernum) == via]
    assert len(merged) == 1                                       # both vias land on M1 and M2: one merged shape
    polygons.compute_via_fill_factors()
    assert merged[0].fill_factor == pytest.approx(2 / 2.5)
    assert area(polygons, metals, "M1") == pytest.approx(100)     # the metal on the same number is not merged


@pytest.mark.parametrize("kwargs", [
    {"extra_layer": '<Layer Name="X" Type="conductor" Material="Cu" Layer="310" Datatype="1" Zmin="8" Zmax="9" />'},
    {"extra_layer": '<Layer Name="X" Type="conductor" Material="Cu" Datatype="1" Zmin="8" Zmax="9" />'},
])
def test_invalid_datatype_use_stops(tmp_path, kwargs):
    _, xml = write_files(tmp_path, **kwargs)
    with pytest.raises(SystemExit):
        stackup_reader.read_substrate(xml)


class _Stop(Exception):
    pass


def test_model_volumes(tmp_path):
    """Elmer thermal model, stopped where meshing would start: the two layers on GDS layer 68 are two bodies."""
    materials, dielectrics, metals, polygons, layers = read(tmp_path)
    thermal_objects = simulation_setup.all_thermal_objects()
    thermal_objects.add_consttemp(simulation_setup.constanttemp(temp=300.0, source_layernum=201, target_layername="BOTTOM"))
    sim_path = str(tmp_path / "model")
    os.makedirs(sim_path, exist_ok=True)
    settings = {"unit": 1e-6, "margin": 0.0, "refined_cellsize": 2.0, "meshsize_max": 20.0, "no_gui": True,
                "thermal_objects": thermal_objects, "materials_list": materials, "dielectrics_list": dielectrics,
                "metals_list": metals, "layernumbers": layers, "allpolygons": polygons, "sim_path": sim_path,
                "model_basename": "datatype"}
    volumes = {}

    def stop_before_meshing(*args, **kwargs):
        for dim, group in gmsh.model.getPhysicalGroups(3):
            name = gmsh.model.getPhysicalName(dim, group)
            volumes[name] = sum(gmsh.model.occ.getMass(3, tag) for tag in gmsh.model.getEntitiesForPhysicalGroup(dim, group))
        raise _Stop

    original = gmsh.model.mesh.generate
    gmsh.model.mesh.generate = stop_before_meshing
    try:
        simulation_setup.create_elmer_thermal(settings)
    except _Stop:
        pass
    finally:
        gmsh.model.mesh.generate = original
        if gmsh.isInitialized():
            gmsh.finalize()
    assert volumes["M1"] == pytest.approx(100) and volumes["V1"] == pytest.approx(2)
    assert volumes["M2"] == pytest.approx(36) and volumes["MD"] == pytest.approx(50)
    assert volumes["Box"] == pytest.approx(50 * 50 * 10 - 100 - 2 - 36 - 50)      # the outline on 301/5
