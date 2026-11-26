"""Direction-dependent thermal conductivity in the stackup XML (ThermalConductivity.xy / .z and
ThermalConductivityTable.xy / .z): reader precedence and errors, and the Elmer heat conductivity text.
Elmer itself does not run here; the Elmer syntax (Heat Conductivity(3) as constants and as a table with a
column per direction, linear extrapolation outside a table) was checked with Elmer 26.2 on a unit cube.

    python -m pytest tests/test_directional_thermal.py
"""
import os

import pytest

from gds2palace import stackup_reader, util_elmer
from gds2palace.util_simulation_setup import _elmer_heat_conductivity, _thermal_conductivity_info

TABLES = '''
  <Tables>
    <Table Name="k_lat"><Point Temperature="300" Value="200" /><Point Temperature="400" Value="150" /></Table>
    <Table Name="k_vert"><Point Temperature="250" Value="120" /><Point Temperature="350" Value="100" /></Table>
  </Tables>'''


def read_material(tmp_path, attributes, variables=''):
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Stackup schemaVersion="3.2">
  <Variables>{variables}</Variables>{TABLES}
  <Materials>
    <Material Name="M" Type="Dielectric" Permittivity="4" {attributes} />
  </Materials>
  <ELayers LengthUnit="um">
    <Dielectrics><Dielectric Name="D" Material="M" Thickness="10" /></Dielectrics>
    <Layers></Layers>
  </ELayers>
</Stackup>'''
    path = tmp_path / 'stackup.xml'
    path.write_text(xml, encoding='utf-8')
    materials, _, _ = stackup_reader.read_substrate(str(path))
    return materials.get_by_name('M')


def described(material):
    return [str(spec) for spec in material.thermal_xyz]


def test_plain_value_is_used_in_all_directions(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivity="1.4"')
    assert described(m) == ['1.4', '1.4', '1.4']
    assert not m.thermal_is_directional()
    assert m.thermalcond == 1.4


def test_lateral_and_vertical_override_the_plain_value(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivity="1.4" ThermalConductivity.z="0.3"')
    assert described(m) == ['1.4', '1.4', '0.3']
    m = read_material(tmp_path, 'ThermalConductivity.xy="0.9" ThermalConductivity.z="0.3"')
    assert described(m) == ['0.9', '0.9', '0.3']
    assert m.thermal_is_directional()
    assert m.thermal_description() == 'xy 0.9, z 0.3'
    assert m.thermalcond == 0          # what an older reader sees


def test_direction_beats_the_plain_table_and_the_other_way(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivityTable="k_lat" ThermalConductivity.z="0.3"')
    assert described(m) == ['table k_lat', 'table k_lat', '0.3']
    assert m.thermal_xyz[0].table.points == [(300, 200), (400, 150)]
    m = read_material(tmp_path, 'ThermalConductivity="1.4" ThermalConductivityTable.z="k_vert"')
    assert described(m) == ['1.4', '1.4', 'table k_vert']
    assert m.thermal_xyz[2].table.name == 'k_vert'


def test_expressions_and_empty_attributes(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivity="1.4" ThermalConductivity.z="=k_z * 2" ThermalConductivity.xy=""',
                      variables='<Variable Name="k_z" Value="0.15" />')
    assert described(m) == ['1.4', '1.4', '0.3']


def test_equal_directions_are_not_directional(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivity.xy="2" ThermalConductivity.z="2"')
    assert not m.thermal_is_directional()
    assert _elmer_heat_conductivity(m) == (2.0, 1)


@pytest.mark.parametrize('attributes', [
    'ThermalConductivity.z="1" ThermalConductivityTable.z="k_vert"',   # constant and table, same direction
    'ThermalConductivity.x="1"',                                       # only .xy and .z
    'Permittivity.z="3"',                                              # only thermal conductivity
])
def test_unsupported_attributes_stop(tmp_path, attributes):
    with pytest.raises(SystemExit):
        read_material(tmp_path, attributes)


def test_elmer_isotropic_unchanged(tmp_path):
    assert _elmer_heat_conductivity(read_material(tmp_path, 'ThermalConductivity="1.4"'), 0.5) == (0.7, 1)
    value, size = _elmer_heat_conductivity(read_material(tmp_path, 'ThermalConductivityTable="k_lat"'))
    assert size == 1
    assert value == 'Variable Temperature\n    Real\n      300.00 200.00\n      400.00 150.00\n    End'


def test_elmer_constant_tensor_with_fill_factor(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivity.xy="0.9" ThermalConductivity.z="0.4"')
    assert _elmer_heat_conductivity(m) == ('Real 0.9 0.9 0.4', 3)
    assert _elmer_heat_conductivity(m, 0.5) == ('Real 0.45 0.45 0.2', 3)
    assert _thermal_conductivity_info(m, 0.5) == 'heat conductivity = xy 0.45, z 0.2 W/mK'


def test_elmer_merged_table(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivityTable.xy="k_lat" ThermalConductivityTable.z="k_vert"')
    value, size = _elmer_heat_conductivity(m)
    assert size == 3
    rows = [[float(v) for v in line.split()] for line in value.splitlines()[2:-1]]
    # every temperature of both tables; outside its own range, a table is extrapolated linearly like Elmer does
    assert rows == [[250, 225, 225, 120], [300, 200, 200, 110], [350, 175, 175, 100], [400, 150, 150, 90]]


def test_elmer_table_and_constant(tmp_path):
    m = read_material(tmp_path, 'ThermalConductivity="1.5" ThermalConductivityTable.z="k_vert"')
    value, size = _elmer_heat_conductivity(m, 2)
    assert size == 3
    assert value.splitlines()[2:-1] == ['      250.00 3 3 240', '      350.00 3 3 200']


@pytest.mark.parametrize('attributes, message', [
    ('ThermalConductivity.z="0.3"', r'no lateral \(x, y\) thermal conductivity'),
    ('ThermalConductivity.xy="1" ThermalConductivityTable.z="missing"', 'not in the <Tables> section'),
    ('', 'has no ThermalConductivity defined'),
])
def test_elmer_errors(tmp_path, attributes, message):
    with pytest.raises(ValueError, match=message):
        _elmer_heat_conductivity(read_material(tmp_path, f'ThermalConductivity="0" {attributes}'))


def test_case_sif_keyword(tmp_path):
    materials = [{"name": "iso", "density": 1.0, "thermalcond": 1.4},
                 {"name": "aniso", "density": 1.0, "thermalcond": 'Real 0.9 0.9 0.3', "thermalcond_size": 3}]
    bodies = [{"name": "iso", "material": 1}, {"name": "aniso", "material": 2}]
    path = os.path.join(str(tmp_path), 'case.sif')
    util_elmer.write_elmer_thermal_file(1e-6, path, materials, bodies, [], [], [{"name": "sink", "temp": 298.0}])
    text = open(path).read()
    assert '   Heat Conductivity = 1.4\n' in text
    assert '   Heat Conductivity(3) = Real 0.9 0.9 0.3\n' in text
