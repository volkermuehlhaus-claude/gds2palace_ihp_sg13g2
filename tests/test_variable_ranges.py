"""Allowed values of stackup <Variable>s (stackup reader 1.11.0, schemaVersion 3.2): Min/Max (numbers or "="
expressions), List ("a;b;c"), Step (positive, not enforced), Description. A value outside them, from the file or
from variable_overrides, stops with an error.

    python -m pytest tests/test_variable_ranges.py
"""
import pytest

from gds2palace import stackup_reader

VARIABLES = '''
    <Variable Name="total_thickness" Value="200" Min="25" Max="750" Step="5" Description="chip thickness, um" />
    <Variable Name="bulk_thickness" Value="=total_thickness - 20" Min="0" />
    <Variable Name="air_thickness" Value="100" Max="=total_thickness" />
    <Variable Name="substrate" Value="300" List="200; 300; 750" />
    <Variable Name="table_choice" Value="Si_a" Type="string" List="Si_a;Si_b" />
    {extra}'''


def read(tmp_path, overrides=None, extra=""):
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Stackup schemaVersion="3.2">
  <Variables>{VARIABLES.format(extra=extra)}</Variables>
  <Materials><Material Name="Si" Type="Dielectric" Permittivity="11.9" /></Materials>
  <ELayers LengthUnit="um">
    <Dielectrics><Dielectric Name="Bulk" Material="Si" Thickness="=bulk_thickness" /></Dielectrics>
    <Layers></Layers>
  </ELayers>
</Stackup>'''
    path = tmp_path / "stackup.xml"
    path.write_text(xml, encoding="utf-8")
    return stackup_reader.read_substrate(str(path), variable_overrides=overrides)


def variables_of(tmp_path, overrides=None, extra=""):
    """The variables_list as the reader resolves and checks it."""
    read(tmp_path, overrides, extra)
    import xml.etree.ElementTree as ET
    root = ET.parse(str(tmp_path / "stackup.xml")).getroot()
    variables = stackup_reader.variables_list()
    for data in root.iter("Variable"):
        variables.append(stackup_reader.variable(data))
    variables.apply_overrides(overrides)
    variables.resolve_all()
    variables.check_allowed_values()
    return variables


def test_values_inside_the_limits(tmp_path):
    variables = variables_of(tmp_path)
    total = variables.get_by_name("total_thickness")
    assert (total.minimum, total.maximum, total.step) == (25, 750, 5)
    assert total.description == "chip thickness, um"
    assert total.allowed_values_text() == "25 .. 750, step 5"
    assert variables.get_by_name("air_thickness").maximum == 200       # an expression
    assert variables.get_by_name("air_thickness").allowed_values_text() == "max 200"
    assert variables.get_by_name("substrate").allowed_values_text() == "one of 200, 300, 750"


@pytest.mark.parametrize("overrides", [
    {"total_thickness": 300},
    {"substrate": 750.0},                 # numbers compared as numbers
    {"table_choice": "Si_b"},
    {"total_thickness": 750},             # the limit itself is allowed
])
def test_allowed_overrides(tmp_path, overrides):
    read(tmp_path, overrides)


@pytest.mark.parametrize("overrides", [
    {"total_thickness": 1000},            # above Max
    {"total_thickness": 15},              # below Min, and makes bulk_thickness negative
    {"air_thickness": 300},               # above Max="=total_thickness"
    {"substrate": 250},                   # not in List
    {"table_choice": "Si_c"},
])
def test_overrides_outside_stop(tmp_path, overrides):
    with pytest.raises(SystemExit):
        read(tmp_path, overrides)


def test_computed_variable_is_checked(tmp_path):
    # a computed variable is checked too: b2 = 18 - 20 = -2 is below its Min
    with pytest.raises(SystemExit):
        read(tmp_path, extra='<Variable Name="t2" Value="18" /><Variable Name="b2" Value="=t2 - 20" Min="0" />')


@pytest.mark.parametrize("extra", [
    '<Variable Name="x" Value="1" Min="0" List="1;2" />',      # range and list together
    '<Variable Name="x" Value="1" Step="0" />',                    # Step must be positive
    '<Variable Name="x" Value="abc" Type="string" Min="0" />',     # Min on text
    '<Variable Name="x" Value="1" List="1;two" />',             # list of a number variable must be numbers
    '<Variable Name="x" Value="1" Max="=undefined_name" />',
])
def test_invalid_definitions_stop(tmp_path, extra):
    with pytest.raises(SystemExit):
        read(tmp_path, extra=extra)
