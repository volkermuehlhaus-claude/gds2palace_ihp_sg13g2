"""Stackup reader edge cases: sheets by numeric Zmin/Zmax, negative Substrate Offset, Table point order,
unique Layer names.

    python -m pytest tests/test_stackup_reader.py
"""
import pytest

from gds2palace import stackup_reader

MATERIALS = '''
  <Materials>
    <Material Name="Metal1" Type="Conductor" Conductivity="2e7" ThermalConductivityTable="k_metal" />
    <Material Name="Via1" Type="Conductor" Conductivity="1e6" ThermalConductivity="100" />
    <Material Name="RS" Type="Resistor" Rs="10" />
    <Material Name="SiO2" Type="Dielectric" Permittivity="4.1" DielectricLossTangent="0" ThermalConductivity="1" />
  </Materials>'''


def write(tmp_path, layers, offset='', table_points=None):
    points = table_points if table_points is not None else [(250, 300), (300, 250), (350, 200)]
    table = ''.join(f'<Point Temperature="{T}" Value="{k}" />' for T, k in points)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Stackup schemaVersion="3.1">
  <Tables><Table Name="k_metal">{table}</Table></Tables>{MATERIALS}
  <ELayers LengthUnit="um">
    <Dielectrics>
      <Dielectric Name="SiO2" Material="SiO2" Thickness="10" />
    </Dielectrics>
    <Layers>
      {offset}
      {layers}
    </Layers>
  </ELayers>
</Stackup>'''
    path = tmp_path / 'stackup.xml'
    path.write_text(xml, encoding='utf-8')
    return str(path)


def read(path):
    return stackup_reader.read_substrate(path)


def test_equal_numbers_written_differently_make_a_sheet(tmp_path):
    path = write(tmp_path, '<Layer Name="R" Type="conductor" Zmin="0.4" Zmax="0.40" Material="RS" Layer="5" />')
    _, _, metals = read(path)
    layer = metals.getbylayername('R')
    assert layer.is_sheet


def test_different_z_stays_a_conductor(tmp_path):
    path = write(tmp_path, '<Layer Name="Metal1" Type="conductor" Zmin="1" Zmax="1.4" Material="Metal1" Layer="8" />')
    _, _, metals = read(path)
    assert metals.getbylayername('Metal1').is_metal


@pytest.mark.parametrize('offset', [2.0, -2.0])
def test_substrate_offset_shifts_the_layers(tmp_path, offset):
    path = write(tmp_path, '<Layer Name="Metal1" Type="conductor" Zmin="1" Zmax="1.4" Material="Metal1" Layer="8" />',
                 offset=f'<Substrate Offset="{offset}" />')
    _, _, metals = read(path)
    layer = metals.getbylayername('Metal1')
    assert layer.zmin == pytest.approx(1 + offset)
    assert layer.zmax == pytest.approx(1.4 + offset)


def test_negative_offset_with_reference_stops(tmp_path):
    path = write(tmp_path, '<Layer Name="Metal1" Type="conductor" Reference="SiO2" ReferenceEdge="Bottom" '
                           'Zmin="1" Zmax="1.4" Material="Metal1" Layer="8" />',
                 offset='<Substrate Offset="-2" />')
    with pytest.raises(SystemExit):
        read(path)


def test_table_points_are_sorted_by_temperature(tmp_path):
    path = write(tmp_path, '<Layer Name="Metal1" Type="conductor" Zmin="1" Zmax="1.4" Material="Metal1" Layer="8" />',
                 table_points=[(350, 200), (250, 300), (300, 250)])
    materials, _, _ = read(path)
    table = next(m for m in materials.materials if m.name == 'Metal1').thermaltable
    assert [T for T, _ in table.points] == [250, 300, 350]
    assert [k for _, k in table.points] == [300, 250, 200]


def test_two_points_at_the_same_temperature_stop(tmp_path):
    path = write(tmp_path, '<Layer Name="Metal1" Type="conductor" Zmin="1" Zmax="1.4" Material="Metal1" Layer="8" />',
                 table_points=[(250, 300), (300, 250), (300, 240)])
    with pytest.raises(SystemExit):
        read(path)


def test_two_layers_with_the_same_name_stop(tmp_path):
    path = write(tmp_path, '<Layer Name="Metal1" Type="conductor" Zmin="1" Zmax="1.4" Material="Metal1" Layer="8" />'
                           '<Layer Name="Metal1" Type="conductor" Zmin="2" Zmax="2.4" Material="Metal1" Layer="10" />')
    with pytest.raises(SystemExit):
        read(path)

UNKNOWN_NAMES = '''<?xml version="1.0" encoding="UTF-8"?>
<Stackup schemaVersion="3.2">
  <Materials>
    <Material Name="Cu" Type="Conductor" Conductivity="5.8e7" ThermalConductivity.z="300" Colour="ff0000" />
    <Material Name="Ox" Type="Dielectric" Permittivity="4" />
  </Materials>
  <ELayers LengthUnit="um">
    <Dielectrics>
      <Dielectric Name="Box" Material="Ox" Zmin="0" Zmax="10" priority="-1" />
    </Dielectrics>
    <Layers>
      <Layer Name="M1" Type="conductor" Material="Cu" Layer="68" DataType="20" Zmin="1" Zmax="2" Note="pad" />
      <Layr Name="M2" Type="conductor" Material="Cu" Layer="69" Zmin="3" Zmax="4" />
    </Layers>
  </ELayers>
</Stackup>'''


def test_unknown_attributes_and_elements_are_reported(tmp_path, capsys):
    """A misspelled attribute or element is not used: read_substrate() says so and names the closest known one
    (stackup reader 1.11.1). It does not stop."""
    path = tmp_path / 'unknown.xml'
    path.write_text(UNKNOWN_NAMES, encoding='utf-8')
    _, _, metals = stackup_reader.read_substrate(str(path))
    printed = capsys.readouterr().out
    assert 'WARNING: stackup file, <Material Name="Cu">: attribute Colour is not known and is ignored. Did you mean Color?' in printed
    assert '<Dielectric Name="Box">: attribute priority is not known and is ignored. Did you mean Priority?' in printed
    assert '<Layer Name="M1">: attribute DataType is not known and is ignored. Did you mean Datatype?' in printed
    assert '<Layer Name="M1">: attribute Note is not known and is ignored\n' in printed
    assert 'element <Layr> is not known and is ignored. Did you mean <Layer>?' in printed
    assert 'ThermalConductivity.z' not in printed                # a direction suffix is a known attribute
    assert printed.count('is not known') == 5
    assert metals.getbylayername('M1').datatype is None          # the misspelled Datatype was not used


def test_known_names_give_no_warning(tmp_path, capsys):
    path = tmp_path / 'known.xml'
    path.write_text(UNKNOWN_NAMES.replace('Colour', 'Color').replace('priority', 'Priority')
                    .replace('DataType', 'Datatype').replace(' Note="pad"', '').replace('<Layr', '<Layer'),
                    encoding='utf-8')
    stackup_reader.read_substrate(str(path))
    assert 'is not known' not in capsys.readouterr().out
