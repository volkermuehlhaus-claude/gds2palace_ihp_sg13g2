"""Constant-temperature boundaries: every polygon on the boundary's GDS layer gets its faces. The face list was
assigned per polygon, so only the last polygon of a layer kept its boundary and the others silently had none
(found on a resistor model with both terminals held at 300 K on one layer: only one terminal was).

    python -m pytest tests/test_thermal_boundaries.py
"""
import gdstk
import gmsh
import pytest

from gds2palace import simulation_setup, stackup_reader, utilities
from gds2palace import util_gds_reader as reader
from gds2palace import util_simulation_setup as setup


@pytest.fixture
def gmsh_model():
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("thermal_boundaries")
    yield
    gmsh.finalize()


def test_every_polygon_of_a_constant_temperature_layer_gets_faces(tmp_path, gmsh_model):
    lib = gdstk.Library()
    cell = lib.new_cell("DESIGN")
    cell.add(gdstk.rectangle((0, 0), (10, 5), layer=203))          # two terminals on one boundary layer
    cell.add(gdstk.rectangle((0, 20), (10, 25), layer=203))
    cell.add(gdstk.rectangle((0, 40), (10, 45), layer=204))        # and one on its own layer
    path = str(tmp_path / "terminals.gds")
    lib.write_gds(path)

    _, _, metals = stackup_reader.read_substrate(utilities.get_stackup_path("SG13G2_FEM_200um.xml"))
    thermal_objects = simulation_setup.all_thermal_objects()
    for layer in (203, 204):
        thermal_objects.add_consttemp(simulation_setup.constanttemp(temp=300.0, source_layernum=layer,
                                                                    target_layername="Metal1"))
    polygons = reader.read_gds(path, [203, 204], purposelist=[0], metals_list=metals)

    faces = setup.add_thermal_boundaries(polygons, metals, thermal_objects)
    gmsh.model.occ.synchronize()

    # Metal1 has a thickness: a bottom and a top face per polygon
    assert len(faces["source_203"]) == 4
    assert len(faces["source_204"]) == 2
    centres_y = sorted({round(gmsh.model.occ.getCenterOfMass(2, tag)[1], 6) for tag in faces["source_203"]})
    assert centres_y == [2.5, 22.5]
