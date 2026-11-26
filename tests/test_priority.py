"""Priority on <Dielectric> and <Layer> (stackup reader 1.11.0): where volumes overlap, the higher Priority keeps the
overlap. Dielectrics among themselves, conductors and vias among themselves; conductors and vias always win over
dielectrics; equal Priority keeps the order from before Priority existed. Checks the volume of each physical group in
the gmsh model of a small Elmer thermal model, stopped where meshing would start.

    python -m pytest tests/test_priority.py
"""
import os

import gdstk
import gmsh
import pytest

from gds2palace import gds_reader, simulation_setup, stackup_reader

STACKUP = '''<?xml version="1.0" encoding="UTF-8"?>
<Stackup schemaVersion="3.2">
  <Materials>
    <Material Name="Mold" Type="Dielectric" Permittivity="3.8" ThermalConductivity="0.5" />
    <Material Name="Si" Type="Semiconductor" Permittivity="11.9" ThermalConductivity="148" />
    <Material Name="Cu" Type="Conductor" Conductivity="5.8e7" ThermalConductivity="400" />
  </Materials>
  <ELayers LengthUnit="um">
    <Dielectrics>
      <Dielectric Name="Mold" Material="Mold" Zmin="0" Zmax="50" Boundary="301" {mold} />
      <Dielectric Name="Die" Material="Si" Zmin="0" Zmax="20" Boundary="302" />
    </Dielectrics>
    <Layers>
      <Layer Name="M_A" Type="conductor" Zmin="20" Zmax="21" Material="Cu" Layer="10" {m_a} />
      <Layer Name="M_B" Type="conductor" Zmin="20" Zmax="21" Material="Cu" Layer="11" />
      <Layer Name="Cavity" Type="dielectric" Zmin="5" Zmax="15" Material="Mold" Layer="12" {cavity} />
      <Layer Name="BOTTOM" Type="sheet" Zmin="0" Zmax="0" Material="PEC" Layer="13" />
    </Layers>
  </ELayers>
</Stackup>'''


def layout(path, em=False):
    """Mold outline 50 x 50 um (301), die 10 x 10 um (302), two 4 x 4 um metals overlapping by 2 x 4 um (10, 11),
    a 2 x 2 um cavity inside the die (12), the bottom sheet and its constant temperature (13, 201). For an EM model
    only M_A (conductors must not touch there) and a via port line from the bottom sheet to M_A (202)."""
    lib = gdstk.Library()
    cell = lib.new_cell("top")
    cell.add(gdstk.rectangle((-20, -20), (30, 30), layer=301))
    cell.add(gdstk.rectangle((10, 10), (20, 20), layer=302))
    cell.add(gdstk.rectangle((0, 0), (4, 4), layer=10))
    if em:
        cell.add(gdstk.rectangle((1, 1), (1, 3), layer=202))
    else:
        cell.add(gdstk.rectangle((2, 0), (6, 4), layer=11))
    cell.add(gdstk.rectangle((12, 12), (14, 14), layer=12))
    cell.add(gdstk.rectangle((-20, -20), (30, 30), layer=13))
    cell.add(gdstk.rectangle((-20, -20), (30, 30), layer=201))
    lib.write_gds(path)


def group_volumes(tmp_path, mold="", m_a="", cavity="", em=False):
    """Volume of every 3D physical group, by name, where meshing would start. em: a Palace model (with air box)
    instead of an Elmer thermal model."""
    xml = tmp_path / "stackup.xml"
    xml.write_text(STACKUP.format(mold=mold, m_a=m_a, cavity=cavity), encoding="utf-8")
    gds = str(tmp_path / "layout.gds")
    layout(gds, em)
    materials, dielectrics, metals = stackup_reader.read_substrate(str(xml))
    settings = {"unit": 1e-6, "margin": 0.0, "refined_cellsize": 2.0, "meshsize_max": 20.0, "no_gui": True,
                "materials_list": materials, "dielectrics_list": dielectrics, "metals_list": metals,
                "model_basename": "priority"}
    if em:
        ports = simulation_setup.all_simulation_ports()
        ports.add_port(simulation_setup.simulation_port(portnumber=1, voltage=1, port_Z0=50, source_layernum=202,
                                                        from_layername="BOTTOM", to_layername="M_A", direction="z"))
        layernumbers = metals.getlayernumbers() + ports.portlayers
        settings.update(fstart=1e9, fstop=10e9, fstep=1e9, air_around=10, simulation_ports=ports)
    else:
        thermal_objects = simulation_setup.all_thermal_objects()
        thermal_objects.add_consttemp(simulation_setup.constanttemp(temp=300.0, source_layernum=201,
                                                                    target_layername="BOTTOM"))
        layernumbers = metals.getlayernumbers() + thermal_objects.layers
        settings["thermal_objects"] = thermal_objects
    polygons = gds_reader.read_gds(gds, layernumbers, purposelist=[0], metals_list=metals,
                                   gds_boundary_layers=dielectrics.get_boundary_layers())
    sim_path = str(tmp_path / "model")
    os.makedirs(sim_path, exist_ok=True)
    settings.update(layernumbers=layernumbers, allpolygons=polygons, sim_path=sim_path)
    volumes = {}

    def stop_before_meshing(*args, **kwargs):
        # the physical groups are complete when meshing starts: measure them and stop
        for dim, group in gmsh.model.getPhysicalGroups(3):
            name = gmsh.model.getPhysicalName(dim, group)
            volumes[name] = sum(gmsh.model.occ.getMass(3, tag) for tag in gmsh.model.getEntitiesForPhysicalGroup(dim, group))
        raise _StopBeforeMeshing

    original = gmsh.model.mesh.generate
    gmsh.model.mesh.generate = stop_before_meshing
    try:
        if em:
            simulation_setup.create_palace(ports.all_active_excitations(), settings)
        else:
            simulation_setup.create_elmer_thermal(settings)
    except _StopBeforeMeshing:
        pass
    finally:
        gmsh.model.mesh.generate = original
        if gmsh.isInitialized():
            gmsh.finalize()
    assert volumes, "meshing was not reached"
    return volumes


class _StopBeforeMeshing(Exception):
    pass


MOLD_BOX = 50 * 50 * 50
DIE_BOX = 10 * 10 * 20
METALS = 4 * 4 + 4 * 4 - 2 * 4      # the two metals together


def test_higher_priority_dielectric_keeps_the_overlap(tmp_path):
    volumes = group_volumes(tmp_path, mold='Priority="-1"')
    assert volumes["Die"] == pytest.approx(DIE_BOX - 2 * 2 * 10)          # minus the cavity, which wins at equal Priority
    assert volumes["Cavity"] == pytest.approx(2 * 2 * 10)
    assert volumes["Mold"] == pytest.approx(MOLD_BOX - DIE_BOX - METALS)   # the die and the metals are cut out


def test_equal_priority_dielectrics_must_not_overlap(tmp_path):
    with pytest.raises(SystemExit):
        group_volumes(tmp_path)


def test_dielectric_layer_gives_way_to_a_higher_dielectric(tmp_path):
    volumes = group_volumes(tmp_path, mold='Priority="-1"', cavity='Priority="-1"')
    assert "Cavity" not in volumes or volumes["Cavity"] == pytest.approx(0)
    assert volumes["Die"] == pytest.approx(DIE_BOX)


@pytest.mark.parametrize("m_a, expected_a, expected_b", [
    ('', 4 * 4 - 2 * 4, 4 * 4),               # equal Priority: as before Priority existed (here M_B, written last)
    ('Priority="1"', 4 * 4, 4 * 4 - 2 * 4),   # M_A keeps the overlap
])
def test_higher_priority_conductor_keeps_the_overlap(tmp_path, m_a, expected_a, expected_b):
    volumes = group_volumes(tmp_path, mold='Priority="-1"', m_a=m_a)
    assert volumes["M_A"] == pytest.approx(expected_a)
    assert volumes["M_B"] == pytest.approx(expected_b)


def test_reader_priority(tmp_path):
    xml = tmp_path / "stackup.xml"
    xml.write_text(STACKUP.format(mold='Priority="=-1"', m_a='Priority="3"', cavity=""), encoding="utf-8")
    _, dielectrics, metals = stackup_reader.read_substrate(str(xml))
    assert dielectrics.get_by_name("Mold").priority == -1
    assert dielectrics.get_by_name("Die").priority == 0
    assert metals.getbylayername("M_A").priority == 3
    xml.write_text(STACKUP.format(mold='Priority="0.5"', m_a="", cavity=""), encoding="utf-8")
    with pytest.raises(SystemExit):
        stackup_reader.read_substrate(str(xml))


def test_overlapping_dielectrics_in_an_em_model(tmp_path):
    # Palace: the air box is cut out of the overlapping dielectrics (failed before with overlapping dielectrics)
    volumes = group_volumes(tmp_path, mold='Priority="-1"', em=True)
    assert volumes["Die"] == pytest.approx(DIE_BOX - 2 * 2 * 10)
    assert volumes["Mold"] == pytest.approx(MOLD_BOX - DIE_BOX, rel=1e-3)    # M_A is a surface in this model
    assert "airbox" in volumes
