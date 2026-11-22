"""Elmer EM models have solver recipes for FEM order 1 and 2 only: order 3 is changed to order 2, with a warning.

    python -m pytest tests/test_elmer_order.py
"""
import os

import pytest

from gds2palace import simulation_setup, stackup_reader, utilities
from gds2palace.util_gds_reader import all_polygons_list

STACKUP = utilities.get_stackup_path('SG13G2_FEM_200um.xml')
TM2, M1 = 134, 8
WARNING = "Elmer EM models support FEM order 1 and 2 only"


def create(tmp_path, order, creator):
    """a TopMetal2 line over a Metal1 plane with a via port at each end; preview only, no meshing.
    Returns the model folder."""
    materials, dielectrics, metals = stackup_reader.read_substrate(STACKUP)
    ap = all_polygons_list()
    ap.add_rectangle(0, -10, 200, 10, TM2)
    ap.add_rectangle(-20, -40, 220, 40, M1)
    ap.add_rectangle(0, -10, 0, 10, 201)
    ap.add_rectangle(200, -10, 200, 10, 202)
    ports = simulation_setup.all_simulation_ports()
    for n in (1, 2):
        ports.add_port(simulation_setup.simulation_port(portnumber=n, voltage=1, port_Z0=50, source_layernum=200 + n,
                                                        from_layername='Metal1', to_layername='TopMetal2', direction='z'))
    sim_path = utilities.create_sim_path(str(tmp_path), 'line', dirname='palace_model')
    settings = dict(unit=1e-6, margin=50, air_around=50, fpoint=[10e9], refined_cellsize=5, meshsize_max=70,
                    order=order, no_gui=True, preview_only=True,
                    simulation_ports=ports, materials_list=materials, dielectrics_list=dielectrics, metals_list=metals,
                    allpolygons=ap, sim_path=sim_path, model_basename='line')
    getattr(simulation_setup, creator)(ports.all_active_excitations(), settings)
    return sim_path


def solver_recipe(sim_path):
    """the solver file that the Elmer case.sif includes"""
    with open(os.path.join(sim_path, 'case.sif')) as f:
        return next(line.split('"')[1] for line in f
                    if 'include' in line and ('first-order' in line or 'quadratic-' in line))


@pytest.mark.parametrize('order, recipe, warned', [
    (3, 'quadratic-direct.sif', True),
    (2, 'quadratic-direct.sif', False),
    (1, 'first-order.sif', False),
])
def test_order_3_runs_as_order_2_with_a_warning(tmp_path, capsys, order, recipe, warned):
    sim_path = create(tmp_path, order, 'create_elmer')
    assert (WARNING in capsys.readouterr().out) is warned
    assert solver_recipe(sim_path) == recipe


def test_palace_keeps_order_3(tmp_path, capsys):
    create(tmp_path, 3, 'create_palace')
    assert WARNING not in capsys.readouterr().out
