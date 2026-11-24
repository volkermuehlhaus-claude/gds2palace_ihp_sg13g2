"""Elmer thermal: a face shared by two metal or via bodies is an interior face, not an error. Example: a resistor whose
poly heads are drawn on HEAT_RESISTOR around its contacts. The stackup's Cont starts at Activ level, so each contact
passes through the head poly and touches it at its side walls; EM models still reject touching conductors.
preview_only stops before meshing but after the check, so this takes seconds.

    python -m pytest tests/test_thermal_interior_faces.py
"""
import os

import gdstk
import gmsh
import pytest

from gds2palace import gds_reader, simulation_setup, stackup_reader, utilities


def resistor_with_heads(path):
    """A 1 x 4 um resistor body (heat source marker 202), poly heads on HEAT_RESISTOR (321) with a hole for the
    contact of each head, the contacts (Cont 6) and Metal1 (8) over them, the outline for the backside (201)."""
    lib = gdstk.Library()
    cell = lib.new_cell("resistor")
    cell.add(gdstk.rectangle((0, 0), (1, 4), layer=202))
    for y0, y1, cy0, cy1 in ((-0.43, 0.0, -0.33, -0.17), (4.0, 4.43, 4.17, 4.33)):
        head = gdstk.rectangle((0, y0), (1, y1))
        contact = gdstk.rectangle((0.42, cy0), (0.58, cy1))
        cell.add(*gdstk.boolean(head, contact, "not", layer=321))
        cell.add(gdstk.rectangle((0.42, cy0), (0.58, cy1), layer=6))
        cell.add(gdstk.rectangle((0.02, y0 + 0.02), (0.98, y1 - 0.02), layer=8))
    cell.add(gdstk.rectangle((-20, -20), (21, 24), layer=201))
    lib.write_gds(path)


def settings_for(tmp_path):
    gds = str(tmp_path / "resistor.gds")
    resistor_with_heads(gds)
    materials, dielectrics, metals = stackup_reader.read_substrate(utilities.get_stackup_path("SG13G2_FEM_200um.xml"))
    thermal_objects = simulation_setup.all_thermal_objects()
    thermal_objects.add_heatsource(simulation_setup.heatsource(power=0.01, source_layernum=202,
                                                               target_layername="HEAT_RESISTOR"))
    thermal_objects.add_consttemp(simulation_setup.constanttemp(temp=300.0, source_layernum=201,
                                                                target_layername="BACKSIDEGND"))
    layernumbers = metals.getlayernumbers() + thermal_objects.layers
    polygons = gds_reader.read_gds(gds, layernumbers, purposelist=[0], metals_list=metals,
                                   gds_boundary_layers=dielectrics.get_boundary_layers())
    sim_path = str(tmp_path / "model")
    os.makedirs(sim_path, exist_ok=True)
    return {"unit": 1e-6, "margin": 20.0, "refined_cellsize": 1.0, "meshsize_max": 20.0, "no_gui": True,
            "preview_only": True, "thermal_objects": thermal_objects, "materials_list": materials,
            "dielectrics_list": dielectrics, "metals_list": metals, "layernumbers": layernumbers,
            "allpolygons": polygons, "sim_path": sim_path, "model_basename": "resistor"}


def test_contact_through_poly_heads_is_accepted(tmp_path):
    settings = settings_for(tmp_path)
    try:
        simulation_setup.create_elmer_thermal(settings)      # exit(101) before: "touches another conductor layer"
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()
