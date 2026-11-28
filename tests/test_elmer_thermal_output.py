"""Elmer thermal output: heat flow per constant-temperature boundary (always), heat flux and temperature gradient
per body (settings['heat_flux_output']), one reduced SaveScalars file with MPI; and scripts/thermal_summary.py.
Checks the case.sif text and the summary of stored result files; Elmer itself does not run here.

    python -m pytest tests/test_elmer_thermal_output.py
"""
import os
import re
import sys

import pytest

from gds2palace import util_elmer, simulation_setup

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import thermal_summary  # noqa: E402

MATERIALS = [{"name": "SiO2", "density": 1.0, "thermalcond": 1.0}]
BODIES = [{"name": "SiO2", "material": 1}, {"name": "source_201", "material": 1, "bodyforce_number": 1}]
SINKS = [{"name": "constanttemp_202", "temp": 298.0}, {"name": "constanttemp_203", "temp": 310.0}]


def case_sif(tmp_path, sinks=SINKS, **kwargs):
    path = os.path.join(str(tmp_path), 'case.sif')
    util_elmer.write_elmer_thermal_file(1e-6, path, MATERIALS, BODIES, [], [0.65], sinks, **kwargs)
    with open(path) as f:
        return f.read()


def solver_blocks(text):
    return {int(n): body for n, body in re.findall(r'^Solver (\d+)\n(.*?)^End', text, flags=re.M | re.S)}


def test_heat_flow_per_boundary_by_default(tmp_path):
    text = case_sif(tmp_path)
    assert 'Post File = ../thermal_results.vtu' in text
    assert 'Active Solvers(3) = 1 2 3' in text
    assert 'Calculate Loads = Logical True' in solver_blocks(text)[1]
    heatflow = solver_blocks(text)[3]
    assert 'Filename = "../thermal_heatflow.dat"' in heatflow
    assert 'Parallel Reduce = Logical True' in heatflow
    for n, sink in enumerate(SINKS, start=1):
        assert f'Variable {n} = Temperature Loads' in heatflow
        assert f'Mask Name {n} = String "heatflow_{sink["name"]}"' in heatflow
        assert f'   heatflow_{sink["name"]} = Logical True\n' in text
    assert 'FluxSolver' not in text


def test_iterative_solve_is_tight_enough_for_the_heat_balance(tmp_path):
    """with 1e-7 the heat flow through the boundaries missed up to 3 % of the input power"""
    heat = solver_blocks(case_sif(tmp_path, iterative=True))[1]
    assert 'Linear System Iterative Method = BiCGStabl' in heat
    assert 'Linear System Convergence Tolerance = 1.0e-10' in heat


def test_min_max_temperature_reduced_with_mpi(tmp_path):
    minmax = solver_blocks(case_sif(tmp_path))[2]
    assert 'Filename = "../thermal_results.dat"' in minmax
    assert 'Parallel Reduce = Logical True' in minmax


def test_no_heat_flow_solver_without_constant_temperature(tmp_path):
    text = case_sif(tmp_path, sinks=[])
    assert 'Active Solvers(2) = 1 2' in text
    assert 'thermal_heatflow' not in text


def test_heat_flux_output_per_body(tmp_path):
    text = case_sif(tmp_path, heat_flux_output=True)
    blocks = solver_blocks(text)
    assert 'Active Solvers(5) = 1 2 3 4 5' in text
    assert 'Post File' not in text
    assert 'Discontinuous Galerkin = Logical True' in blocks[4]
    assert 'Calculate Flux = Logical True' in blocks[4] and 'Calculate Grad = Logical True' in blocks[4]
    output = blocks[5]
    for line in ('Output File Name = "../thermal_results"', 'Discontinuous Bodies = Logical True',
                 'Save Geometry Ids = Logical True', 'Exec Solver = After Simulation'):
        assert line in output


def test_capability_flag_for_setupem():
    assert simulation_setup.THERMAL_HEAT_FLUX_OUTPUT is True


def write_results(run_path, minmax, heatflow, mpi=False):
    os.makedirs(run_path, exist_ok=True)
    with open(os.path.join(run_path, 'thermal_results.dat'), 'w') as f:
        f.write('   ' + '   '.join(f'{v:.12E}' for v in minmax) + '\n')
    if heatflow is None:
        return
    with open(os.path.join(run_path, 'thermal_heatflow.dat'), 'w') as f:
        f.write('  ' + '   '.join(f'{v:.12E}' for _, v in heatflow) + '\n')
    with open(os.path.join(run_path, 'thermal_heatflow.dat.names'), 'w') as f:
        f.write('Metadata for SaveScalars file: mesh/../thermal_heatflow.dat\nVariables in columns of matrix: \n')
        for n, (name, _) in enumerate(heatflow, start=1):
            f.write(f'   {n}: boundary sum: temperature loads over bc heatflow_{name}{" : mpi_sum" if mpi else ""}\n')


def test_thermal_summary_two_sinks(tmp_path):
    case_sif(tmp_path)
    write_results(str(tmp_path), [297.998, 346.07], [('constanttemp_202', -1.0821), ('constanttemp_203', 0.4323)],
                  mpi=True)
    assert thermal_summary.read_case(str(tmp_path)) == ({'constanttemp_202': 298.0, 'constanttemp_203': 310.0},
                                                         pytest.approx(0.65))
    assert thermal_summary.read_heatflow(str(tmp_path)) == [('constanttemp_202', pytest.approx(1.0821)),
                                                           ('constanttemp_203', pytest.approx(-0.4323))]
    text, has_results = thermal_summary.build_summary(str(tmp_path))
    assert has_results
    assert 'Max temperature : 346.07 K' in text
    assert re.search(r'constanttemp_203\s+310\.00\s+-0\.4323\s+-66\.5 %', text)
    assert re.search(r'Total\s+0\.6498\s+100\.0 %', text)


def test_thermal_summary_older_model_and_no_results(tmp_path):
    older = os.path.join(str(tmp_path), 'older')
    os.makedirs(older)
    case_sif(older)
    write_results(older, [298.0, 346.19], None)
    text, has_results = thermal_summary.build_summary(older)
    assert has_results and 'before 0.13.0' in text

    empty = os.path.join(str(tmp_path), 'empty')
    os.makedirs(empty)
    case_sif(empty)
    assert thermal_summary.build_summary(empty)[1] is False
    assert sorted(thermal_summary.find_thermal_dirs(str(tmp_path))) == [empty, older]
