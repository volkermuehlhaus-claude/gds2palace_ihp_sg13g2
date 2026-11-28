# gds2palace Architecture — a reference for AI agents

This document exists to orient an AI coding agent quickly and *accurately* in this repository:
what gds2palace actually is, what it is not, exactly how a model script talks to it, exactly what
happens when you "run" a model (including the parts that live outside this repo entirely), and a
worked analysis of the most structurally interesting example in the tree (inductor synthesis).

It complements, rather than replaces, `doc/userguide_md_format/gds2palace_workflow_userguide.md`
(the human-facing user guide — more screenshots, more narrative, less "trace the exact function
calls"). Code is cited by module and function name (`util_simulation_setup.create_model()`), not by
line number, so the citations survive edits; search the module for the name. Where this document
and the code disagree, the code is right.

**Repo root** for every path below: `D:\github-claude\gds2palace_ihp_sg13g2\` (GitHub:
`VolkerMuehlhaus/gds2palace_ihp_sg13g2`, upstream of the `volkermuehlhaus-claude` fork this
workspace develops under).

---

## 1. What gds2palace is, in one paragraph

gds2palace is a pure Python toolkit that turns a GDSII layout plus an XML "stackup" file
(metal/dielectric layer definitions, materials, via rules — specific to the IHP SG13G2 open-source
RFIC PDK) into the input files for **AWS Palace**, a 3D FEM electromagnetic solver, or
alternatively for **Elmer FEM**, a different open-source FEM solver. A model script — a short,
hand-written (or AI-written, or setupEM-GUI-generated) Python file — imports `gds2palace`,
describes a few simulation settings and a handful of ports, and calls one function
(`simulation_setup.create_palace(...)` or `create_elmer(...)`). That call runs `gmsh` under the
hood to build 3D geometry and mesh it, then writes out the solver's native input files. **Neither
Palace nor Elmer is part of this package** — see §5.

---

## 2. Package layout — `workflow/gds2palace/`

| File | Responsibility |
|---|---|
| `__init__.py` | Defines the entire public import surface (below) and `__version__` |
| `util_stackup_reader.py` | Parses the XML technology stackup file (`read_substrate()`); has its own reader `__version__` |
| `util_gds_reader.py` | Reads the GDSII layout with gdstk into polygon objects (`read_gds()`): design-cell selection, flattening, via merging, derived layers, polygon repair |
| `util_simulation_setup.py` | The largest module, the core engine: ports, gmsh geometry/mesh construction, Palace `config.json` writer, Elmer `.sif` data (`create_model()`) |
| `util_extruded_mesh.py` | The extruded mesh of Elmer thermal models (`settings['thermal_mesh'] = 'extruded'`): all outlines cut into faces with shapely, a 2D gmsh mesh of them, repeated as prisms at every z level, built as discrete entities with the same physical groups as the tetrahedral mesh. Called from `create_model()` through `_create_extruded_thermal_model()`; not re-exported |
| `util_elmer.py` | Elmer-specific file writers (EM case/solver files, thermal `case.sif`) and the `ElmerGrid` mesh conversion — internal, never imported directly by model scripts |
| `util_utilities.py` | Path/filename helpers, the `run_sim`/`run_elmer` wrapper-script generators, the stackups and result scripts that ship with the package |
| `util_calibration.py` | Port walls (box sides set to `'PORTWALL'`): finds the wall ports, cuts their gaps, the cross-section at the wall, D and the standards' length, writes the calibration standards through `create_model()`, the `run_sim` lines for them. Exported as `calibration` |
| `util_thermal_map.py` | Puts the powers of a circuit simulation onto the heat sources of a KLayout EM Export thermal export (`<name>_thermalmap.json` + a powers file → a setupThermal `.tsimcfg`); used by setupThermal's "Load powers", also a command line tool: `python -m gds2palace.util_thermal_map <name>_thermalmap.json powers.csv <name>.tsimcfg`. Not re-exported |

`workflow/gds2palace/__init__.py` (the imports, verified):

```python
from . import util_stackup_reader as stackup_reader
from . import util_gds_reader as gds_reader
from . import util_utilities as utilities
from . import util_simulation_setup as simulation_setup
from . import util_calibration as calibration

__version__ = "..."   # version of gds2palace
```

So a model script uses **five names**: `stackup_reader`, `gds_reader`, `utilities`,
`simulation_setup`, `calibration`. There is no `__all__`, so `from gds2palace import *` also brings
the module names themselves (`util_stackup_reader`, ..., and `util_elmer`, which
`util_simulation_setup.py` imports); scripts don't use those. `util_elmer` is an internal
dependency of `util_simulation_setup.py`, never called directly from a model script.

**PyPI package name is `gds2palace`, importable as `gds2palace`** — but note the *directory* it
lives in inside this repo is `workflow/gds2palace/`, not the repo root; when reading example
scripts you'll often see `sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'gds2palace')))`
before `from gds2palace import *` — that's for running a script directly against the in-repo source
without installing the package. `pyproject.toml` maps three packages with `[tool.setuptools.package-dir]`:
`gds2palace` from `workflow/gds2palace/`, `gds2palace.stackups` from `XML_stackup/latest/IHP/` (the
latest IHP stackup files and their README) and `gds2palace.scripts` from `scripts/`
(`combine_extend_snp.py` and `palace_summary.py`, as `py-modules`). So the installed wheel has
`python -m gds2palace.scripts.combine_extend_snp` and `python -m gds2palace.scripts.palace_summary`
(both need scikit-rf, which gds2palace doesn't install).

Helpers in `util_utilities.py` find these files in a wheel and in a git clone alike:
`get_stackup_path(filename)` (full path of a shipped stackup; without an argument it prints the
folder and the available files), `get_stackup_dir()`, `get_scripts_dir()`, and
`copy_combine_script(destination_path)`, which `create_run_script()` uses to put a copy of
`combine_extend_snp.py` next to each model (§5.4).

---

## 3. Stackup XML format, `stackupEditor`, and agent-driven stackup generation

Every model script needs an XML "stackup" file — layer stack, materials, via rules — read via
`stackup_reader.read_substrate()` (§4 step 4). This section covers the file format itself, the GUI
tool for editing it, and — most relevant to an agent with no GUI — **how to generate or edit one
programmatically**, using the exact functions the GUI itself is built on.

### 3.1 — File format

Format spec: `doc/XML_stackup_format/XML_stackup_format.md` (this repo); related:
`doc/XML_stackup_format/derived_layers.md`, `doc/XML_stackup_format/evolution_of_stackup_file_format.md`.
Top-level structure:
```xml
<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<Stackup schemaVersion="2.0">
  <Variables>...</Variables>        <!-- optional, first by convention -->
  <Materials>...</Materials>
  <ELayers LengthUnit="um">
    <Dielectrics>...</Dielectrics>
    <Layers>...</Layers>
    <DerivedLayers>...</DerivedLayers>  <!-- optional -->
  </ELayers>
  <Tables>...</Tables>               <!-- optional, thermal conductivity tables -->
</Stackup>
```

Smallest real example in the repo, `XML_stackup/legacy/pcb_ro4003.xml` (full file, verified):
```xml
<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
  <Stackup schemaVersion="2.0">
    <Materials>
      <Material Name="Copper" Type="Conductor" Permittivity="1" DielectricLossTangent="0" Conductivity="3.3e7" Color="00ff00"/>
      <Material Name="RO4003" Type="Dielectric" Permittivity="3.38" DielectricLossTangent="0.0022" Conductivity="0" Color="01e0ff"/>
      <Material Name="AIR" Type="Dielectric" Permittivity="1.0" DielectricLossTangent="0.0" Conductivity="0" Color="d0d0d0"/>
    </Materials>
    <ELayers LengthUnit="um">
      <Dielectrics>
        <Dielectric Name="RO4003" Material="RO4003" Thickness="510" />
      </Dielectrics>
      <Layers>
        <Substrate Offset="0"/>
        <Layer Name="Bottom" Type="Conductor" Zmin="-17" Zmax="0" Material="Copper" Layer="1" />
        <Layer Name="Top" Type="Conductor" Zmin="510" Zmax="527" Material="Copper" Layer="10" />
      </Layers>
    </ELayers>
  </Stackup>
```

**`<Materials>`** — one `<Material>` per material: `Name`, `Type` (`Conductor`/`Dielectric`/
`Semiconductor`/`Resistor`), `Permittivity`, `DielectricLossTangent`, `Conductivity`, `Rs`, plus
thermal-only `Density`/`ThermalConductivity`/`ThermalConductivityTable`, and a `Color` (hex, used
by the stackup preview). `ThermalConductivity.xy`/`.z` and `ThermalConductivityTable.xy`/`.z` give a
lateral and a vertical value (see "schemaVersion 3.2" below).

**`<Dielectrics>`** — the vertical dielectric stack, independent of GDSII, listed top-to-bottom.
Position is resolved by priority: (1) explicit `Zmin`+`Zmax`, (2) Reference-relative
(`Reference="<other Dielectric Name>"` + optional `ReferenceEdge`, default `Top`; own `Zmin`
defaults `0`, `Zmax` defaults `Zmin+Thickness`), (3) legacy implicit stacking by `Thickness` alone.

**`<Layers>`** — drawn, GDSII-sourced layers. `Type` ∈ `conductor`/`via`/`dielectric`/`sheet` —
maps 1:1 to `util_stackup_reader.py`'s `metal_layer.is_metal`/`is_via`/`is_dielectric`/`is_sheet`
flags (see also §4's canonical-pattern walkthrough); a Layer with equal `Zmin` and `Zmax` is a
`sheet` regardless of the stated `Type` (compared as numbers, `_same_number()`). A sheet needs a
`Resistor` material or `PEC`. `<Substrate Offset="...">` shifts every Layer's z by a fixed
amount, also a negative one — mutually exclusive with any `Reference`-based Layer in the same
file. Two Layers with the same `Name` stop `read_substrate()` with an error (`Reference`, ports
and heat sources look layers up by name), and `thermal_table` sorts its points by temperature
and rejects two points at the same temperature (reader 1.10.0).

**Reference-relative positioning** (`schemaVersion="3.0"+`) replaces hand-recomputed absolute
z-values and the single global `Substrate Offset` fudge factor with a `Reference`/`ReferenceEdge`
chain, resolved in dependency order regardless of file order — so a whole stack no longer needs
re-deriving by hand whenever one Dielectric's thickness changes.

**`<DerivedLayers>`** (`schemaVersion="3.0"+`) — computes a new GDSII layer number from existing
ones via boolean ops `AND`/`OR`/`XOR`/`NOT` (≥2 operands, folded pairwise) or `SIZE` (1 operand,
resize by `Oversize`). Operands may chain off other derived layers (topologically sorted). Full
detail: `doc/XML_stackup_format/derived_layers.md`.

**`<Variables>`** (`schemaVersion="3.1"+`; the reader only warns about a `schemaVersion` above its
`SUPPORTED_SCHEMA_VERSION`, currently `"3.2"`) — by convention the
first child of `<Stackup>`; the reader resolves them first wherever they are. Any attribute value anywhere
in the file starting with `=` is an expression (`+ - * / **`, parens, references to other Variables
by name), resolved in dependency order with circular-reference detection:
```xml
<Variables>
  <Variable Name="cu_conductivity" Value="21640000.0" />
  <Variable Name="via_top" Value="=metal_thickness + via_thickness" />
</Variables>
```
`stackup_reader.read_substrate(XML_filename, variable_overrides={...})` lets a model script
override a named Variable at run time without editing the XML — the mechanism setupEM's "Override
stackup Variables" grid feeds into.

**`schemaVersion="3.2"`** (stackup reader 1.11.0, gds2palace 0.13.0) adds four optional features. A
stackup without them is read and built exactly as before. Full rules, with use cases:
`doc/XML_stackup_format/XML_stackup_format.md`.

- **Priority** on `<Dielectric>` and `<Layer>` (`resolve_priority()`, `.priority`): where two volumes
  overlap, the higher Priority keeps the overlap. It compares dielectrics among themselves and
  conductors and vias among themselves; a conductor or via always wins over a dielectric. So
  `<Dielectric>` boxes may overlap (mold compound around a die); two that overlap with equal Priority
  stop with an error.
- **Thermal conductivity per direction** on `<Material>`: `.xy` and `.z` variants of
  `ThermalConductivity` and `ThermalConductivityTable`; the plain attribute stays the value for all
  directions. `stackup_material.thermal_xyz` holds the three directions (each a constant or a table).
- **Allowed values of Variables**: `Min`/`Max` (numbers or `=` expressions), `Step`, `List` (`a;b;c`)
  and `Description` on `<Variable>`. `variables_list.check_allowed_values()` checks the file's values
  and every override after all variables are resolved, and stops outside them.
- **Datatype** on `<Layer>` and on a derived layer's `<Operand>`, `BoundaryDatatype` on `<Dielectric>`:
  the layer is read from that GDS datatype, whatever `purposelist` `read_gds()` gets. A layer with a
  `Datatype` is identified by a **layer id** instead of its plain layer number: a leading 1, five
  digits layer number, five digits datatype (68/20 is `10006800020`; `layer_id()`,
  `split_layer_id()`, `layer_text()`). `metal.layernum` and `metals_list.getlayernumbers()` hold these
  ids, `metal.gds_layernum` / `metal.datatype` the two parts. Everything downstream that is keyed by
  layer number (polygons, bounding boxes, via merging, derived layers, port walls) works on the ids
  unchanged, and two stackup layers can share a GDS layer number. Layers without a `Datatype` keep
  their plain number.

### 3.2 — `stackupEditor`: what it is, and what it's built on

`stackupEditor` is a PySide6 GUI (`setupEM/src/setupEM/stackupEditor.py`, `StackupEditorWindow`,
console script `stackupEditor = "setupEM.stackupEditor:main"`, in the sibling `setupEM` repo) for
editing stackup XML files without hand-editing — Variables, Materials, Dielectric stack, Layers,
Derived Layers, and thermal Tables, each as an editable grid, plus a live cross-section preview.

**The important architectural fact for an agent: the GUI holds no separate, richer domain model of
its own.** Its single source of truth is a plain `xml.etree.ElementTree` (`self.tree`),
loaded/created via `stackup_writer.load_stackup_tree(filename)` / `stackup_writer.new_stackup_tree()`.
Every tab is a generic `ElementTableEditor` widget parameterized with plain `stackup_writer`
functions as callbacks, e.g.:
```python
add_fn=lambda root, **attrs: stackup_writer.add_material(root, **attrs),
remove_fn=stackup_writer.remove_material,
type_choices=list(stackup_writer.VALID_MATERIAL_TYPES),
```
So editing a row in the GUI just calls the same `stackup_writer.add_material()`/`remove_material()`/
etc. an agent would call directly. There is no intermediate GUI-only object an agent needs to
reconstruct.

### 3.3 — `stackup_writer.py`: the actual, GUI-independent XML editing API

`setupEM/src/setupEM/stackup_writer.py` is a **standalone module with zero Qt/GUI
dependency** — its only imports are `ast`, `xml.etree.ElementTree`, and
`from gds2palace import stackup_reader` (itself pure stdlib). Its own docstring states the intent
directly: it's deliberately kept separate from `util_stackup_reader.py` because *"the reader turns
XML into the read-only object model ... used by the rest of gds2palace, while this module is for
tools that need to load a file, edit it ..., and write it back out ... while leaving any parts of
the file they don't understand (e.g. XML comments) completely untouched."*

**This means: an AI agent can generate or edit a stackup XML file by importing `stackup_writer`
directly and calling it — no GUI, no Qt event loop, no `QApplication` — exactly the functions
`stackupEditor` itself calls.**

Full public API (function names/signatures verified directly against source):
```python
load_stackup_tree(filename)                                   # -> ElementTree, comment-preserving parse
new_stackup_tree(length_unit="um", schema_version="2.0")       # -> ElementTree, minimal empty <Stackup>
save_stackup_tree(tree, filename)                               # writes to disk, self-corrects schemaVersion

get_materials_element(root) / get_dielectrics_element(root) / get_layers_element(root)
get_substrate_offset_element(root) / get_derived_layers_element(root, create=False)
get_variables_element(root, create=False) / get_tables_element(root, create=False)

add_material(root, **attrs)  / remove_material(root, element)
add_dielectric(root, index=None, **attrs)  / remove_dielectric(root, element)
move_dielectric(root, element, direction)      # direction: -1 up / +1 down
add_layer(root, **attrs)  / remove_layer(root, element)
reorder_layers(root, ordered_elements)         # file order only; the reader sorts by z itself
set_substrate_offset(root, value)              # value None/0 removes the <Substrate> element
add_derived_layer(root, **attrs)  / remove_derived_layer(root, element)
get_operand_layers(element) / set_operands(element, layer_numbers)   # "68/20": an operand with a Datatype
add_variable(root, **attrs)  / remove_variable(root, element)
add_table(root, **attrs)  / remove_table(root, element)
add_point(table_element, **attrs)  / remove_point(table_element, element)

validate_stackup(root)          # -> list[str] of problems, [] if OK
find_reserved_material_definitions(root)   # warnings only, e.g. a <Material Name="PEC"> entry
required_schema_version(root)   # -> "2.0"/"3.0"/"3.1", the minimum actually needed by file content
stamp_header_comments(root, app_name, description="")
get_file_description(root)      # -> str
```
`add_*`/`remove_*` take/return plain `Element` objects; keyword arguments become XML attributes
directly (`None`/`""` values are skipped). `VALID_MATERIAL_TYPES`, `VALID_LAYER_TYPES`,
`VALID_DERIVED_OPERATIONS` module-level tuples give the exact allowed values for each `Type`/
`Operation` field.

**Comment preservation is real, not just a GUI-editor claim**: `load_stackup_tree()` uses a custom
comment-preserving parser (`ET.TreeBuilder(insert_comments=True)`), so hand-written
`<!-- comments -->` in a file survive an agent's load→edit→save round-trip untouched — including
any `<Tables>` content, which the writer's own logic never touches at all.

**Worked example** — generating the `pcb_ro4003.xml` file above from scratch, using nothing but
`stackup_writer`:
```python
from setupEM import stackup_writer

tree = stackup_writer.new_stackup_tree(length_unit="um", schema_version="2.0")
root = tree.getroot()

stackup_writer.add_material(root, Name="Copper", Type="Conductor",
                             Permittivity="1", DielectricLossTangent="0",
                             Conductivity="3.3e7", Color="00ff00")
stackup_writer.add_material(root, Name="RO4003", Type="Dielectric",
                             Permittivity="3.38", DielectricLossTangent="0.0022",
                             Conductivity="0", Color="01e0ff")

stackup_writer.add_dielectric(root, Name="RO4003", Material="RO4003", Thickness="510")

stackup_writer.set_substrate_offset(root, 0)
stackup_writer.add_layer(root, Name="Bottom", Type="conductor",
                          Zmin="-17", Zmax="0", Material="Copper", Layer="1")
stackup_writer.add_layer(root, Name="Top", Type="conductor",
                          Zmin="510", Zmax="527", Material="Copper", Layer="10")

errors = stackup_writer.validate_stackup(root)
if errors:
    raise SystemExit("\n".join(errors))

stackup_writer.stamp_header_comments(root, app_name="agent-script",
                                      description="Generated programmatically")
stackup_writer.save_stackup_tree(tree, "pcb_ro4003_generated.xml")
```
(`stackup_writer` is a plain submodule of the installed `setupEM` package — not re-exported from
`setupEM`'s own top-level `__init__.py` (which only exports `main`), so
`import setupEM.stackup_writer as stackup_writer` / `from setupEM import stackup_writer` both work,
but `from setupEM import *` will not surface it.)

**Cross-repo note**: `stackup_writer.py` lives in the `setupEM` repo, not this one —
`gds2palace_ihp_sg13g2` has no writer of its own (`util_stackup_reader.py` only reads). Using it
requires `setupEM` installed alongside `gds2palace` (`setupEM`'s own `pyproject.toml` depends on
`gds2palace`, never the reverse — there is no `setupEM` reference in this repo's
`pyproject.toml`).

### 3.4 — Does an agent-generated file actually round-trip through gds2palace's reader?

Reasonably reliably, and not just by construction — **`stackup_writer.save_stackup_tree()` actively
exercises gds2palace's own `stackup_reader.parse_substrate()`** as part of every save, to resolve
sort order for Layers (by resolved `Zmin`) and Table points (by resolved `Temperature`), and
`required_schema_version()`/`validate_stackup()` run their own independent checks beforehand. So a
file that passes `validate_stackup(root)` cleanly and saves without error has already been parsed
once by the real reader logic before it ever reaches disk. The one caveat: the save-time sort steps
silently skip their cosmetic reordering (not fail the whole save) if `parse_substrate()` raises —
so a clean `validate_stackup()` result plus a successful save is strong, but not
absolutely 100%-exhaustive, evidence the file will read back correctly. **The definitive check
remains calling `gds2palace.stackup_reader.read_substrate()` on the generated file directly** and
confirming no exception.

---

## 4. The canonical model-script pattern

Traced end-to-end from `workflow/palace_rfcmim.py` (a hand-written RF MIM capacitor model — chosen
as representative because it's not one of the more elaborate synthesis/sweep scripts) and
cross-checked against `workflow/palace_line_viaport.py` (layout `line_simple_viaport.gds`). Every model script in this repo — hand
written, setupEM-generated, or the inductor synthesis scripts (§12) — follows this same sequence.

```python
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'gds2palace')))
from gds2palace import *

# --- 1. path/output-directory bootstrap ---
script_path    = utilities.get_script_path(__file__)
model_basename = utilities.get_basename(__file__)
sim_path       = utilities.create_sim_path(script_path, model_basename)

# --- 2. settings dict (plain dict, see §6 for the full key reference) ---
settings = {}
settings['unit']              = 1e-6
settings['margin']            = 50
settings['fstart']            = 1e9
settings['fstop']             = 20e9
settings['fstep']             = 1e9
settings['refined_cellsize']  = 2

XML_filename = "SG13G2_nosub.xml"
gds_filename = "my_layout.gds"

# --- 3. ports ---
simulation_ports = simulation_setup.all_simulation_ports()
simulation_ports.add_port(simulation_setup.simulation_port(
    portnumber=1, voltage=1, port_Z0=50, source_layernum=201,
    from_layername='Metal1', to_layername='TopMetal1', direction='z'))
simulation_ports.add_port(simulation_setup.simulation_port(
    portnumber=2, voltage=1, port_Z0=50, source_layernum=202,
    from_layername='Metal1', to_layername='Metal5', direction='z'))

# --- 4. read the stackup ---
materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate(XML_filename)

# --- 5. build the layer list to extract, and read the GDSII ---
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)
allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0],
    metals_list=metals_list, merge_polygon_size=0)

# --- 6. stuff everything the engine needs into settings ---
settings['simulation_ports'] = simulation_ports
settings['materials_list']   = materials_list
settings['dielectrics_list'] = dielectrics_list
settings['metals_list']      = metals_list
settings['layernumbers']     = layernumbers
settings['allpolygons']      = allpolygons
settings['sim_path']         = sim_path
settings['model_basename']   = model_basename

# --- 7. build the model (writes config.json + mesh + port_information.json) ---
excite_ports = simulation_ports.all_active_excitations()
config_name, data_dir = simulation_setup.create_palace(excite_ports, settings)

# --- 8. write the convenience run script into sim_path ---
utilities.create_run_script(sim_path)
```

### What each call actually does

- **`utilities.create_sim_path(script_path, model_basename, dirname='palace_model')`**
  builds `<script_dir>/palace_model/<model_basename>_data/` and
  creates it (`os.makedirs`). On Windows, if the base path would exceed 200 characters, or if
  directory creation fails for any other reason, it falls back to a directory under the
  system temp dir instead, with a `[WARNING]` line — worth knowing if a generated model's
  output ends up somewhere unexpected on a Windows box with a deeply-nested repo path.

- **`simulation_setup.simulation_port(...)`** validates, at
  construction time, that you've specified either a **via port** (`direction` contains `z`/`Z`,
  plus `from_layername` + `to_layername`) or an **in-plane port** (`direction` contains `x`/`y`,
  plus `target_layername`) — anything else prints an error and calls `exit(1)` immediately.
  There is no gentler failure mode here; a malformed port definition kills the whole
  script at construction time, before any geometry or meshing work happens.

- **`all_simulation_ports.all_active_excitations()`** returns only the ports whose
  `abs(voltage) > 1e-6` — a `voltage=0` port is *defined* (its geometry still gets built and it
  still appears as a matrix row/column) but never *excited*. This is the mechanism used throughout
  the repo to cheaply simulate "just this one path" of a larger multi-port structure — see the
  ATTENTION callout in §8.

- **`stackup_reader.read_substrate(XML_filename, variable_overrides=None)`**
  parses the XML with a comment-preserving `ElementTree`
  parser, checks `schemaVersion` (a warning above the supported version), and returns exactly the 3-tuple
  `(materials_list, dielectrics_list, metals_list)`. `metals_list` also carries
  `.derived_layers` for the boolean-operation "derived layer" feature (§3.1). `variable_overrides`
  is a dict of `{variable_name: value}` used to override a `<Variables>`-declared value from Python
  without editing the XML file — this is exactly the mechanism setupEM's "Override stackup
  Variables" grid feeds into.

- **`gds_reader.read_gds(filename, layerlist, purposelist=None, metals_list=None, preprocess=False,
  merge_polygon_size=0, mirror=False, offset_x=0, offset_y=0, gds_boundary_layers=[],
  layernumber_offset=0, cellname="", derived_layers=None)`** (`util_gds_reader.py`), in order:
  1. Opens the GDS with `gdstk.read_gds` and picks the cell with `select_design_cell()`: the named
     cell, else the largest top-level cell that is not a `$$$` cell (KLayout's
     `$$$CONTEXT_INFO$$$`), else the first top-level cell (gds2palace 0.11.0 and newer; the same
     rule as gds_prepare_for_EM and gds2openEMS).
  2. Flattens it (paths become polygons), applies `mirror` (about the y axis) and then
     `offset_x`/`offset_y`, and for each requested layer number (plus `gds_boundary_layers`)
     extracts layer/datatype polygons matching `purposelist` (`None` means `[0]`). A layer id of a
     stackup layer with a `Datatype` (§3.1) is read from that datatype only, whatever `purposelist`
     says; its polygons carry the id as `layernum`, with `poly.gds_layer` / `poly.gds_datatype` for
     the two parts. `layernumber_offset` is added to every layer number, so that two GDS files can be
     read into one model. A note is printed for shapes on a stackup layer's number that are on
     datatypes not read. `all_polygons.print_layers(metals_list)` lists what was read into which layer.
  3. Via arrays: on `metal.is_via` layers with `merge_polygon_size > 0`, `merge_via_array()` merges
     vias closer than that distance, then `split_bridging_via_merges()` splits a merged region again
     where it would connect different metal shapes above or below (gds2palace 0.8.1 and newer). The
     unmerged vias are kept in `all_polygons.via_originals` (keyed by layer number or id); `create_model()`
     uses them only when `settings['fill_factor_correction']` is set, calling
     `all_polygons_list.compute_via_fill_factors()` to set each merged via polygon's `fill_factor`,
     so reading GDSII costs nothing extra otherwise.
  4. Derived layers: `resolve_derived_layers()` computes the stackup's `<DerivedLayers>` (boolean
     operations and `SIZE`, in dependency order) from the raw layer polygons. An operand with a
     `Datatype` is a layer id and is read from that datatype. With
     `derived_layers=None` (the normal call), they come from `metals_list.derived_layers`.
  5. The dielectric bounding boxes from `gds_boundary_layers`.
  6. `_repair_malformed_polygons()`: self-intersecting polygons on layers meshed as solids (stackup
     metals and vias, dielectric boundary layers, derived layers — not port or marker layers) are
     repaired right after reading, instead of failing later in meshing.

  The `preprocess` argument is obsolete: it only prints a note (cutouts are handled downstream after
  flattening). Model scripts that still pass `preprocess=settings['preprocess_gds']` work unchanged.

- **`simulation_setup.create_palace(excite_ports, settings)`** is a thin wrapper —
  it just calls `create_model(excite_ports, settings)`. Palace is the *default* mode.
  `create_elmer(excite_ports, settings)` sets `settings['elmer']=True` then calls
  the same `create_model()`. `create_elmer_thermal(settings)` (no `excite_ports` —
  thermal has no EM ports) sets `settings['elmer']=True, settings['elmer_thermal']=True` and dummy
  `fstart=fstop=1e9` (mesh-only frequencies). **All three funnel into one function,
  `create_model()`, by far the largest in the package** — this is the actual engine. In order, it:
  1. Pulls every setting out of the `settings` dict via a local
     `get_optional_setting(settings, key, default)` closure (`settings.get(key, default)`) —
     unrecognized keys are ignored, missing optional keys fall back to defaults rather than raising.
     Checks: `order` outside 1-3 falls back to 2 with a warning, `conductor_model` (and the legacy
     `filled_metals`; `z_thickness_factor` is ignored with a warning), the boundary list. For
     `fstart = 0` the sweep starts at `fstep` and two points from `low_frequency_point()` are added
     (10 and 20 MHz, higher for a refined cell size below 0.5 µm). Sets `config_name`
     (`config<config_suffix>.json`) and `data_dir`.
  2. **Port-wall phase, before gmsh** (EM models only; skipped while building a calibration
     standard, `settings['_calibration_standard']`): `util_calibration.clip_derived_layers()` cuts
     derived layers at a wall on the layout edge, `extend_walls()` continues the cross-section
     outward for `settings['wall_extension']`, and for sides set to `'PORTWALL'`:
     `port_wall_box()` (margin and air on those sides), `analyze_port_walls()` (wall ports, D, the
     standards' length, `reference_plane_shift`, `deembedding_length`, `port_wall_extension`),
     `apply_port_walls()` (cuts the port gaps into the lines), `standard_records()`.
     `via_ports_in_pec_walls()` stops a model whose via port would be shorted by a PEC wall. An
     Elmer model with a port wall stops with `PortWallError` — port walls are Palace only.
  3. `gmsh.initialize()`, creates a fresh gmsh model.
  4. `add_metal_volumes(...)` — turns each drawn polygon into a gmsh 3D volume or 2D
     surface depending on the corresponding XML `<Layer>` type (via / dielectric-brick / sheet /
     planar metal). With `conductor_model = 'solve_inside_skin'`, `add_conductor_skin_cores()` then
     splits each conductor into skin layers and a core (depths from `skin_layer_depths()`). Thermal
     models: `add_thermal_sources()` / `add_thermal_boundaries()` build the heat-source volumes
     and the constant-temperature surfaces from the marker polygons.
  5. `add_dielectrics(...)` — builds the stackup dielectric boxes and, unless doing
     thermal, an outer airbox sized by `margin`/`air_around`. `resolve_dielectric_overlaps()` cuts
     each overlap of two boxes out of the one with the lower Priority (equal Priority: error);
     `resolve_dielectric_layer_priorities()` then cuts a drawn dielectric layer where a `<Dielectric>`
     has a higher Priority.
  6. Boolean-cuts metal and drawn dielectric layers out of the dielectric boxes
     (`gmsh.model.occ.cut`), then `gmsh.model.occ.fragment(...)` to conformally stitch everything
     together. A piece shared by two drawn volumes goes to the one named last, in the order of
     `_overlap_class()`: drawn dielectric layers, then vias and conductors, each by Priority, at equal
     Priority a conductor after a via.
  7. `add_ports(...)` — builds the port 2D-sheet surfaces and returns the port metadata struct.
     Several surfaces of one port (several shapes on its layer, or the four walls of a tube port)
     become elements `P<n>`, `P<n>_2`, ... of one multielement port. A second
     `gmsh.model.occ.fragment(...)` inserts the ports and sheets into the volumes.
  8. Assigns gmsh physical groups for every conductor/dielectric/boundary entity.
  9. Writes **`port_information<config_suffix>.json`** into `sim_path` (not for thermal): the
     `add_ports()` struct (per port/element: number, `Z0`, direction, geometry, `"tube": true` for
     tube walls) plus `unit`, `name` (the model name), `deembedding: 'none'` if set, and
     `port_walls` (`util_calibration.port_information_record()`). This file is gds2palace's own
     metadata, consumed later by the Touchstone-conversion script (§9), never by Palace itself.
  10. **Palace path** (`if not elmer:`): writes `config.json` — a nested dict with
     `Problem` (`Type`, `Verbose`, `Output` = `"output/<model_basename>"`), `Model` (mesh filename,
     `L0`, AMR `Refinement` block), `Solver` (linear-solver params incl. `ComplexCoarseSolve`,
     `Order`, `Device: "CPU"`, `Driven.Samples` frequency list, `AdaptiveTol`), `Domains.Materials`
     (keyed by numeric gmsh physical-group `Attributes`), and `Boundaries` (`Conductivity`,
     `LumpedPort` with `Elements` for multielement ports, optionally
     `Impedance`/`Absorbing`/`PEC`/`PMC`).
  11. **Elmer path** (`if elmer:`): builds equivalent `Elmer_*` structures and calls
     `util_elmer.write_elmer_frequencies/write_elmer_physics_file/write_elmer_thermal_file/
     write_case_and_solver_files`, plus writes `ELMERSOLVER_STARTINFO`.
  12. Mesh-size fields from `refined_cellsize`/`refined_cellsize_override`/`meshsize_max`/
      `cells_per_wavelength`, optional gmsh GUI preview (`gmsh.fltk.run()`, unless
      `no_gui`/`no_preview`). With `preview_only` it stops here, without a mesh and without
      calibration standards.
  13. Meshing: `gmsh.model.mesh.generate(3)` with `General.AbortOnError = 0`; if 3D Delaunay leaves
      volumes without elements, it retries with the HXT algorithm. A check for zero-volume elements
      follows (an `ERROR` for Elmer, a `WARNING` for Palace). Then `gmsh.write(msh_name)` —
      **forcing `Mesh.MshFileVersion = 2.2`**, because *"Palace requires mesh version 2.2!"*
  14. For Elmer: `util_elmer.convert_mesh_to_elmer(msh_name, ELMER_MPI_THREADS)`
      converts the `.msh` to Elmer's native mesh format via the external `ElmerGrid` tool.
  15. With port walls: the calibration standards. For each wall group (not shared with another
      wall), `util_calibration.standard_settings()` builds the settings of the thru lines L and 2 L,
      `create_model()` is called recursively for each, and `write_key()` writes its key file — into
      the same `_data` folder.
  16. Returns `(config_name, data_dir)` — `data_dir` is literally the string
      `'output/' + model_basename`, a relative path baked into `config.json`'s
      `Problem.Output`. **Palace itself creates that `output/` directory when it runs** — gds2palace
      never creates it.

- **`utilities.create_run_script(sim_path)`** writes a convenience
  wrapper — see §5.4 for exact content and why it exists.

### Concrete files a Palace run produces (verified against a real generated directory)

`<script_dir>/palace_model/<model_basename>_data/`:
```
config.json                    # Palace's solver-control file (written by gds2palace)
<model_basename>.msh           # gmsh mesh, forced to format version 2.2 (written by gds2palace)
port_information.json          # gds2palace's own port metadata (written by gds2palace)
run_sim                        # convenience wrapper (written by create_run_script(), see §5.4)
combine_extend_snp.py          # copy of the result script that matches this model (create_run_script(), 0.10.0+)
config_cal_<side>_<L|2L>.json, port_information_cal_<side>_<L|2L>.json,
<model_basename>_cal_<side>_<L|2L>.msh, cal_<side>_<L|2L>.key
                               # only with port walls: the calibration standards
output/                        # created BY PALACE ITSELF when it runs — empty/absent until then
mesh_convergence_summary.txt   # AMR runs only: written later by scripts/palace_summary.py (§9.3)
```
With `settings['config_suffix']`, the config and port information files are
`config<suffix>.json` and `port_information<suffix>.json`.

For Elmer EM:
```
case.sif  ELMERSOLVER_STARTINFO  first-order.sif  frequencies.dat  physics.sif
quadratic-direct.sif  quadratic-iterative.sif  port_information.json
run_elmer                       # run_elmer.bat on Windows (create_elmer_run_script(), §5.4)
<model_basename>.msh   mesh/    # ElmerGrid-converted mesh partition directory
```
Elmer thermal models (written to `elmer_model/<model_basename>_data/` by the thermal example, which
calls `create_sim_path(..., dirname='elmer_model')`) have `case.sif`, `ELMERSOLVER_STARTINFO`, the
`.msh` and `mesh/`; ElmerSolver writes `thermal_results.dat` and `thermal_results_t0001.vtu` there.

---

## 5. "Palace itself is not included" — what that means concretely

### 5.1 — Confirmed: not a Python dependency

`pyproject.toml`:
```toml
[project]
name = "gds2palace"
...
dependencies = [
    "gdstk",
    "gmsh",
    "numpy",
    "shapely>=2.0",
]
```
Only these are pip dependencies (gdstk replaced gdspy in 0.11). **No `palace`, no MPI bindings, nothing
solver-related.** `pip install gds2palace` gives you the model-file *generator*, nothing that can
actually run an FEM solve.

### 5.2 — What this package does vs. what it explicitly does not do

- `README.md`: *"It creates model files for the AWS Palace FEM solver, which must be installed
  separately, as described in chapter 'Installing Palace'."*
- `README.md`: *"The gds2palace workflow does not change, it only creates the input files for
  Palace and does not care how you installed Palace, or on what platform you run the actual Palace
  simulation from these model files."*

So concretely: gds2palace's job stops at producing `<model>.msh` + `config.json` (+
`port_information.json`) inside `palace_model/<name>_data/`. Actually **running** the FEM solve —
the compute-heavy, MPI-parallel, compiled C++/MFEM binary that reads that `.msh` + `config.json`
and produces raw S-parameters — is entirely external to this repo and this package.

### 5.3 — What a user or agent must install/provide separately

Two documented installation paths for the Palace binary, **both Linux-only**
(`README.md`: *"This workflow is designed for Linux systems"*; on Windows, Palace runs in WSL):

1. **Apptainer/Singularity container**: pull the prebuilt Palace 0.20.0 image —
   `apptainer pull ~/palace_0200.sif oras://ghcr.io/volkermuehlhaus/palace_0200:latest` — or build
   it from source; both in `doc/building-palace-apptainer.md` (and `README.md`).
2. **Build from source via the Spack package manager** — `doc/building-palace-spack.md`.

`scripts/install_linux/install_gds2palace.sh` and `scripts/install_windows/install_gds2palace.bat`
(with `install_gds2palace.py` and `install_palace_wsl.sh`) are one-file installers: a venv with
setupEM, gds2palace, gds_prepare_for_EM and scikit-rf from PyPI, generated `run_palace`/`combine_snp`
scripts, and Palace as the prebuilt Apptainer container (on Windows inside WSL, with Windows-side
wrappers that forward into WSL). Each folder has a README; both installers have `--help`.

Either way, the repo's own reference launcher, **`scripts/run_palace`** (full file, 2 lines):
```bash
#!/bin/bash
apptainer exec ~/palace.sif palace -np 8 $1
```
This runs the `palace` binary *inside* a container image at `~/palace.sif`, with Palace's own
`-np 8` flag telling it to partition the simulation domain across 8 MPI processes, and `$1` (the
first CLI argument, expected to be `config.json`) passed straight through.

**`scripts/README.md` is explicit that this is just the author's own dev setup, not a
requirement**: *"If you prefer to install and run Palace in a different way, no problem! The
gds2palace workflow creates the input files for Palace, and it is entirely your choice how you run
the simulator with these model files, local or on a sophisticated HPC cluster."*

There's also **`scripts/run_palace_remote`**, meant to be renamed to `run_palace` in place of the
local version: it `scp`s the entire model output directory to a remote Linux machine, `ssh`es in
and runs that machine's own `run_sim` (see §5.4 below) there, then `scp`s the resulting `output/`
directory back — i.e. Palace execution is fully decoupled from wherever the Python model-generation
step ran (you can generate model files on Windows/macOS and simulate on a remote Linux box).

### 5.4 — The generated per-model `run_sim` wrapper (distinct from `scripts/run_palace`)

`utilities.create_run_script(sim_path)` (called at the end of every model script, §4 step 8) writes
`<sim_path>/run_sim`. For a model without port walls:
```bash
#!/bin/bash
run_palace config.json
wrapper=$(command -v combine_snp)
if [ -n "$wrapper" ] && ! grep -q "\./combine_extend_snp.py" "$wrapper"; then echo "WARNING: your combine_snp runs the copy of combine_extend_snp.py in ~/scripts, ..."; fi
combine_snp
```
It also copies `combine_extend_snp.py` (the version shipped with this gds2palace,
`copy_combine_script()`) into `sim_path`; the `combine_snp` wrapper runs that copy when it is there
(§9.2), so the result conversion matches the model. The `wrapper=` check warns when the
`combine_snp` on `PATH` is older than gds2palace 0.10.0 and still runs `~/scripts/combine_extend_snp.py`.
If the copy can't be written, the two check lines are left out.

With port walls, `util_calibration.run_script_lines()` adds, before `run_palace config.json`, one
block per calibration standard listed in `port_information.json`: `run_palace config_cal_<...>.json`,
skipped when `output/<model>_cal_<...>/port-S.csv` exists and its `cal.key` equals the standard's key
file (an earlier result of the same standard is reused), then `echo "device model"`.

The file is written with Unix line endings even on Windows, and `chmod 0o755`'d only when running on
Linux.

**The relationship between the two:**
- `run_sim` is generated **fresh into every model's own output directory** by gds2palace. It
  contains no simulator-specific configuration — it's purely "solve this model, then convert its
  results," and it calls `run_palace`/`combine_snp` as bare commands, relying on `$PATH`.
- `run_palace` (and `combine_snp`) are **general-purpose, hand-configured-once-per-machine**
  scripts that must exist somewhere on `PATH` (`scripts/README.md`: *"Include the script folder to
  your PATH"*). They decide *how* Palace actually launches on this particular machine (which
  container image, how many cores, or — via the renamed `run_palace_remote` — dispatch to a
  different machine entirely).

**An agent generating a new model should call `utilities.create_run_script(sim_path)` exactly as
existing scripts do, and should assume a working `run_palace` + `combine_snp` already exist on
`PATH` in the target execution environment — it should not try to reimplement Palace invocation
logic itself.**

Some model scripts additionally offer an in-Python auto-run toggle right after `create_palace()`:
```python
start_simulation = False
run_command = ['./run_sim']
...
if start_simulation:
    os.chdir(sim_path)
    subprocess.run(run_command, shell=True)
```
— i.e. the model script itself can `cd` into the freshly-created output directory and shell out to
`./run_sim` immediately after generating it.

**Elmer equivalent**: `utilities.create_elmer_run_script(sim_path, settings)` writes `run_elmer`
into `sim_path`, either:
```bash
#!/bin/bash
ElmerSolver
combine_snp
```
(single process, when `settings['ELMER_MPI_THREADS']` is 1 or unset) or:
```bash
#!/bin/bash
mpirun -np 8 ElmerSolver case.sif
combine_snp
```
(MPI-parallel — the `-np N` value comes from `util_elmer.get_ELMER_MPI_THREADS(settings)`). On
Windows it writes `run_elmer.bat` instead, with Windows line endings, no shebang, and MS-MPI's
`mpiexec -n N ElmerSolver case.sif` for the parallel case.

---

## 6. `settings` dict — the full key reference

`settings` is a **plain Python dict**, not a class, passed straight into
`simulation_setup.create_palace(excite_ports, settings)` / `create_elmer(...)`. The defaults below
are the `get_optional_setting(settings, key, default)` calls in `create_model()`
(`util_simulation_setup.py`); the code is the complete list — search for `get_optional_setting`.
**Unknown keys are silently ignored**, so a typo (`settings['nogui']`) leaves the default in place.
AGENTS.md has the same table for model-script writers.

**Required:**

| Key | Meaning |
|---|---|
| `margin` | Oversize of dielectrics from the drawing's bounding box, in the xy plane. Single value, or a list of 4 `[xmin,xmax,ymin,ymax]` values, all 0 or more |
| `fstart`, `fstop` | Frequency sweep, in Hz. Not every step is necessarily EM-simulated, due to the adaptive frequency sweep. Both may be left out when `fpoint` or `fdump` gives the frequencies. `fstart` below 0.1 MHz: see §4 step 1 |
| `refined_cellsize` | Target mesh size at polygon edges, in `unit` |

**With a default:** `unit` (`1e-6`, microns) and `fstep` (`(fstop - fstart)/100`).

**Optional — discrete frequencies in addition to / instead of the sweep:**

| Key | Meaning |
|---|---|
| `fpoint` | List of discrete frequencies, e.g. `[10e9, 15e9]` |
| `fdump` | Like `fpoint`, but Palace also writes a field dump for Paraview at these frequencies — see §10 |

**Optional — everything else:**

| Key | Default | Meaning |
|---|---|---|
| `cells_per_wavelength` | 10 | Calculated at the highest frequency; must be ≥10 |
| `meshsize_max` | 70 | Maximum mesh size limit, on top of `cells_per_wavelength` |
| `refined_cellsize_override` | `[]` | Per-layer override, e.g. `[['Metal3', 10], ['Metal2', 2]]`. Only conductor/sheet layers produce the boundary curves this applies to — a via or dielectric layer name (or any typo/nonexistent name) is a plain dict-key miss inside `create_model()`, silently ignored with no error (`util_simulation_setup.py`'s `refined_cellsize_override_dict` lookup, fed only by `boundary_line_tags_dict`, which vias/dielectrics never populate). setupEM's own "Advanced..." mesh-override dialog restricts its layer picker to valid conductor/sheet layers for exactly this reason. |
| `boundary` | `['ABC']*6` | 6 values for xmin/xmax/ymin/ymax/zmin/zmax: `ABC` (`PML` is accepted and treated as `ABC`), `PEC`, or `PMC`. `'PORTWALL'` on xmin/xmax/ymin/ymax makes a port wall: a PEC wall at the layout edge, the ports on it calibrated with standards (`util_calibration.py`, Palace only, §9.2 step 7) |
| `reference_plane_shift` | none | Port walls: dict per wall side, e.g. `{'xmin': 60}`, in `unit`, positive into the layout |
| `port_wall_extension` | none | Port walls: dict per wall side, `'auto'` or a length: moves the wall outward, the feed continued with the cross-section at the wall |
| `deembedding_length` | 4 D, at most λg/5 at `fstop`, at least 2 D | Port walls: length of the shorter calibration standard, in `unit` |
| `wall_extension` | none | Dict per side that is not a port wall, e.g. `{'xmax': 2000}`: the layout's cross-section at that edge continued outward (pieces of a split region) |
| `deembedding` | (on) | `'none'`: written to `port_information.json`; `combine_snp` then writes only the raw result, no `_deembedded` file |
| `fill_factor_correction` | `False` | Scale the conductivity of merged via arrays by their fill factor (needs `merge_polygon_size > 0` in `read_gds()`) |
| `amr_tol` / `amr_max_dof` | `1e-2` / `2e6` | AMR stop criteria (Palace `Refinement` block) |
| `config_suffix` | `''` | Suffix for `config.json` and `port_information.json`, e.g. `'_fine'` |
| `iterative` | `False` for Elmer EM, `True` for Elmer thermal | Elmer linear solver. EM: direct = MUMPS (`quadratic-direct.sif`), iterative = `quadratic-iterative.sif` (order 2 only). Thermal: iterative = BiCGStabl with ILU3, at most 10000 iterations; direct = UMFPACK (`util_elmer.write_elmer_thermal_file()`) |
| `ELMER_MPI_THREADS` | 1 | Elmer: number of MPI processes; the mesh is partitioned for them by `ElmerGrid` and `run_elmer` starts `mpirun -np N` (`mpiexec -n N` on Windows) |
| `air_around` | same as `margin` (a 4-value `margin`: per side, `zmin`/`zmax` the largest value) | Single value, or a list of 6 `[xmin,xmax,ymin,ymax,zmin,zmax]` values. `0` is allowed on any side (e.g. a backside ground plane flush with the simulation boundary, no wasted air layer) |
| `order` | 2 | FEM basis-function order (2 = accurate; 1 = quick/dirty) — see §7 for what this actually does to accuracy |
| `substrate_refinement` | `False` | Extra mesh refinement into the substrate |
| `adaptive_sweep` | `True` | Enable Palace's adaptive frequency sweep |
| `adaptive_mesh_iterations` | 0 | AMR iterations — often unnecessary with a fine initial mesh |
| `adaptive_mesh_conformal` | `False` | Use conformal AMR mesh refinement instead of Palace's default nonconformal (hanging-node) refinement |
| `save_adaptive_mesh` | `False` | Save the AMR-iteration mesh for reuse |
| `complex_coarse_solve` | `True` | Palace: the sparse direct coarse solver factorizes the full complex system, not only its real part (Palace's own default, which leaves absorbing boundaries, port resistances and losses out of the preconditioner). On for every model (surface impedance or filled metals): without it, some models don't converge at some frequencies and get wrong S-parameters there - e.g. a D-band GCPW line at 170 GHz, an inductor at 2.4 GHz. Same results and same or shorter run time where both converge; costs 1.0-1.6x (order 2) / 1.5-1.9x (order 1) peak RAM, model dependent |
| `solver_maxits` | 400 | Palace linear solver (GMRES) iteration limit per frequency. Reaching it only logs "solver did NOT converge" - that frequency's result is unreliable |
| `solver_tol` | 1e-6 | Palace linear solver relative residual tolerance |
| `save_gmsh_unrolled` | `False` | Also save the unmeshed gmsh geometry, for inspection |
| `conductor_model` | `'surface'` | `'surface'`: conductors as hollow volumes with a surface impedance boundary on all faces. `'solve_inside'`: conductors as solid bulk-conductivity volumes (EM only — Palace and Elmer; Elmer thermal always models metal as solid volumes, regardless of this setting). Mesh resolution normal to the conductor surface determines the accuracy at high frequency. Where a via and a conductor geometrically overlap (e.g. a via drawn to extend slightly into its pad, for a watertight boolean), the conductor's material wins the shared region. `'solve_inside_skin'`: like `'solve_inside'`, plus each conductor is split into thin layers along all its faces and a core (inward offset, `add_conductor_skin_cores()`), so the mesh has thin cells at the surface without a fine mesh along it: 0.4 and 1 skin depth at the highest frequency (`skin_layer_depths()`), for layers at least 4 skin depths thick and conductivity up to 1e8 S/m. Legacy `filled_metals` (`True`/`False`, before 0.9.0) maps to `'solve_inside'`/`'surface'` with a note; any other `filled_metals` value, and `skin_layers`, stop with an error |
| `no_gui` | `False` | Don't show the gmsh UI — for unattended/scripted runs |
| `no_preview` | `False` | Skip the unmeshed-geometry preview, go straight to showing the meshed model |
| `preview_only` | `False` | Show the unmeshed geometry and stop: no mesh, no calibration standards |

**Not user-facing settings, but required in the dict before calling `create_palace`/`create_elmer`**
(built during steps 4-6 of §4, not typed by hand): `simulation_ports`, `materials_list`,
`dielectrics_list`, `metals_list`, `layernumbers`, `allpolygons`, `sim_path`, `model_basename`.

---

## 7. FEM order and what it does to accuracy

`settings['order']` selects the polynomial order of the finite-element basis functions Palace uses
within each mesh cell (tetrahedron): 1 (linear), 2 (quadratic, the default), or 3 (cubic). Enforced
in `create_model()`: any value outside `1-3` prints a warning and falls
back to `order=2`. It maps directly to `config.json`'s `Solver.Order` field.

**What raising the order actually buys you**: a higher-order basis function can represent field
variation *within a single mesh cell* more accurately (more degrees of freedom per cell), so a
coarser mesh (larger `refined_cellsize`) can reach the same accuracy as a much finer mesh at a
lower order. Conversely, order=1 needs a denser mesh to resolve the same field distribution
accurately — this is the classic FEM p-refinement (raise polynomial order) vs. h-refinement (refine
the mesh) trade-off.

The user guide documents a real head-to-head comparison for exactly this trade-off
(`doc/userguide_md_format/gds2palace_workflow_userguide.md`, section "Single microstrip line", an 880 µm long / 15 µm-wide
TopMetal2-over-Metal1 microstrip line testcase), simulated four different ways:

| `refined_cellsize` | `order` | Simulation time | Degrees of freedom (DOF) |
|---|---|---|---|
| 2 µm | 1 | 64 s | 321,999 |
| 5 µm | 2 | 282 s | 699,658 |
| **2 µm** | **2 (default)** | **733 s** | **1,640,126** |
| 5 µm | 3 | 1967 s | 1,982,661 |

Findings from that comparison, quoted/paraphrased from the user guide:
- **order=1 is a clear outlier** — visibly different S11/S21 magnitude and phase from every
  higher-order configuration, regardless of mesh density. Treat order=1 as "quick/dirty" only,
  never for a final result.
- **`refined_cellsize=5, order=3` reproduces the `refined_cellsize=2, order=2` baseline almost
  exactly** (S11 and S21 magnitude/phase visually identical) — confirming a higher basis-function
  order really can substitute for a finer mesh.
- But in this case that substitution was **not a good trade**: it took *more* DOF and nearly 3×
  the simulation time (1967 s vs. 733 s) to match the accuracy the default
  (`refined_cellsize=2, order=2`) already gave more cheaply. The guide's own conclusion:
  *"refined_cellsize=2, order=2 is the best choice for accurate data... at less simulation time."*

**Practical guidance for an agent choosing these settings**: don't reach for `order=3` as a first
move to improve accuracy — try tightening `refined_cellsize` at the default `order=2` first, and
only escalate to `order=3` if a documented convergence check (e.g. via `adaptive_mesh_iterations`,
or a manual before/after comparison like the one above) shows it's actually needed. `order=1`
should be reserved for fast exploratory sweeps where some visible error is acceptable — this is
exactly how the inductor-synthesis examples in §12 use it (`order=1` for a broad coarse sweep
across dozens of candidates, `order=2` only for the finalists).

**Elmer note**: Elmer's EM solver only supports `order` 1 or 2 (`util_elmer.write_case_and_solver_files()`
has recipes for these two). `order=3` is Palace-only: `create_model()` changes it to 2 for an Elmer EM
model, with a warning.

---

## 8. Ports

Ports are geometry-driven: **drawn as polygons on special GDSII layers** (conventionally 201 and
up) that are not part of the real IHP layer table, then mapped by `simulation_port(...)` to real
technology layers via `from_layername`/`to_layername` (vertical/via port) or `target_layername`
(in-plane port), plus a `direction` (`x`/`y`/`z`, case-insensitive per `util_simulation_setup.py`'s
`Z in self.direction.upper()`-style checks).

**Two structural quirks worth knowing:**

1. **`voltage` doesn't mean voltage to Palace** — Palace itself doesn't support the `voltage`
   parameter; it only supports polarity reversal by flipping port direction. This workflow instead
   *repurposes* `voltage` as an excitation on/off switch: **`voltage=0` means "define this port's
   geometry, but don't excite it."** `all_simulation_ports.all_active_excitations()` filters out
   any port with `abs(voltage) <= 1e-6` before it's passed to `create_palace(...)`.
2. **Palace runs one excitation at a time, sequentially.** To get a full S-matrix you must define
   *every* port with a nonzero voltage — Palace then simulates each excitation, one after another,
   automatically. **If any port is left at `voltage=0`, its row in the S-parameter output is
   entirely absent (later padded with zeros by the Touchstone converter, §9)** — this is a
   deliberate, useful trick for cheaply simulating just one signal path of a larger multi-port
   structure, not a bug.

Port shape requirement: ports are **2D-sheet lumped ports**. For a vertical (via) port, draw a
zero-width box in GDSII (a line, effectively): one vertical sheet. A long, narrow box (short side
up to 10 % of the long side) also gives one sheet, along its xmin or ymin edge. A shape with more
area gives a tube port: the four side walls of its bounding box as one multielement port
(`via_port_is_tube()` in `util_simulation_setup.py`, gds2palace 0.12.0 and newer; its walls are
marked `"tube": true` in `port_information.json` and are not de-embedded by `combine_snp`).

**Several shapes on one port layer** give one port with one element per shape (gds2palace 0.9.3 and
newer): `add_ports()` names the surfaces `P<n>`, `P<n>_2`, ..., and the Palace config gets one
`LumpedPort` with an `Elements` list — the elements are in parallel, the port impedance stays `Z0`.
This is how a terminal spread over several strips (e.g. the source fingers of a transistor) becomes
one port. Multielement and tube ports are Palace only, not Elmer. Separate ports are not merged:
each port with a non-zero voltage stays its own port of the S-matrix.

**Port walls** (`'PORTWALL'` in `settings['boundary']`, gds2palace 0.10.0 and newer, Palace only):
the box side becomes a PEC wall at the layout edge that is the ground of the ports on it, and these
ports are calibrated with two line standards instead of the estimated port inductance (§4 steps 2
and 15, §9.2 step 7).

---

## 9. From raw Palace output to Touchstone `.snp`

### 9.1 — `port-S.csv` is Palace's own native output, not something gds2palace writes

gds2palace's only involvement in Palace's output is setting `config.json`'s
`Problem.Output = "output/<model_basename>"` (written in `create_model()`) — a relative
path telling Palace where to write its own results. **Palace itself** creates that `output/`
directory and writes `port-S.csv` (and other files) into it when it actually runs — the CSV's
column-header convention (`|S[i][j]|`/`arg(S[i][j])`, `(dB)`/`(deg.)` suffixes) is Palace's native
format, not anything gds2palace defines.

gds2palace does separately write its own metadata file, `port_information.json`, directly into
`sim_path` (one level up from Palace's `output/<model>/` folder) — per port element: port number,
element number, `Z0`, direction, geometry (length/width/position), `"tube": true` for tube-port
walls; plus `unit`, `name`, and optionally `deembedding: "none"` and `port_walls` (§4 step 9). This
is *not* consumed by Palace; it's read back only by the Touchstone-conversion step below, for the
`Z0` header value and for de-embedding.

### 9.2 — `combine_snp` → `combine_extend_snp.py`

`scripts/combine_snp` (the thin invocation wrapper, comments left out):
```bash
#!/bin/bash
script=~/scripts/combine_extend_snp.py
if [ -f ./combine_extend_snp.py ]; then
  script=./combine_extend_snp.py
fi
~/venv/palace/bin/python "$script" "$@"
```
It prefers the model's own copy of `combine_extend_snp.py` (written next to every model since
gds2palace 0.10.0, §5.4), so the conversion matches the gds2palace that wrote the model; older
models fall back to `~/scripts`. The interpreter path is machine-specific — `scripts/README.md` says
to adjust it (it needs scikit-rf). Arguments are passed through. `combine_extend_snp.py` has
`--help`, `--version` and an optional `folder` argument (default: the current folder); without it,
it walks the current directory tree, so it must be run from within (or above) the directory tree
holding the Palace/Elmer output — which is exactly what `run_sim`/`run_elmer` do, since they run it
right after the solve, from `sim_path`. It prints its version and path as the first line. In the pip
package it is also `python -m gds2palace.scripts.combine_extend_snp`.

**What `combine_extend_snp.py` actually does, traced through its real logic** (`main()` and
`_process_datafile()` in `scripts/combine_extend_snp.py`):

1. **Discovery**: recursively walks the current directory tree, collecting every file literally
   named `port-S.csv` (Palace) or `scalar_results.names` (Elmer) — a brute-force scan, which is
   exactly why it tolerates Palace's AMR `iterationN/` subfolder nesting (one AMR iteration's
   result sits one directory level deeper than the final result).
2. **Per found file**: walks *upward* from the file's directory, up to 4 levels, looking for a
   sibling `port_information.json`. If found: extracts each port's `Z0` into a Touchstone header
   value (supports mixed port impedances as a space-separated list), and reads an optional
   `"name"` field used as a filename fallback — needed because Elmer's native output directory is
   always literally called `mesh`. If not found: defaults `Z0` to `"50"` and later prints a
   warning.
3. **Parsing**: `parse_palace_csv()` for `port-S.csv` (strips Palace's CSV formatting, enumerates
   which `S[i][j]` columns are actually present — since only excited ports produce data) or
   `parse_elmer_results()` for `scalar_results.names`+its paired data file (Elmer's "coupling
   matrix" `cmf`/`cmf im` columns, converted from angular frequency in rad/s to GHz).
4. **Assembling Touchstone rows**: for 2-port results specifically, swaps to `S[j][i]` ordering to
   match Touchstone's traditional `S11 S21 S12 S22` convention (any other port count uses natural
   row-major `S[i][j]` order). Any `(i,j)` pair with no data (an un-excited port, per §8) is padded
   with `0.0`/`0.0` — this is exactly the "missing rows padded with zeros" behavior the user guide
   documents.
5. **Writing**: `<parentname>.s<N>p` (e.g. `mymodel.s2p`), written by hand (not via scikit-rf's
   writer) as a header line `#  {freq_unit} S DB R {Z0_string}` followed by one
   whitespace-separated data line per frequency.
6. **DC extrapolation** (`extrapolate_to_DC()`): only if the Touchstone file has more than 20
   frequency points *and* its lowest frequency is ≤1 GHz — Palace's frequency-domain solve cannot
   go all the way to 0 Hz — this step re-reads the file via `skrf.Network` and adds a 0 Hz point in
   front of the unchanged data with `network_with_dc_point()`: linear in magnitude and in unwrapped
   phase through the first two frequencies, imaginary part dropped (the same value as scikit-rf's
   `extrapolate_to_dc()`, which isn't used because it resamples the whole result). Written as
   `<basename>_dc.s<N>p`.
7. **Port de-embedding**. With port walls (`port_information.json` has `port_walls`, written by
   `util_calibration.port_information_record()`), `calibrated_deembedding()`: per port wall it reads the
   two standards' `port-S.csv` (thru L and 2 L), takes the reciprocal part, converts S to the cascade
   matrix directly (`s2t`, never through Y, which is singular for a half-wave line and for a
   DC-extrapolated inductor), and gets the port's shunt and series element from the double delay
   T_L^-1 T_2L T_L^-1 (`port_from_double`). The elements are interpolated to the device's frequencies
   (imaginary part per omega linear in f, real part linear in sqrt(f), held outside the standards' frequencies; from
   a frequency below fmax/100, the model's lowest one, only the series resistance is used, and the same for a
   point between fmax/100 and fmax/20 whose capacitances and inductance don't agree with the point at fmax/20). One
   2N-port error network at 50 ohm holds the calibrated blocks of all walls (plus `expm(A s)` of the
   line for a reference plane shift) and the estimated inductance of the other ports; it is removed in
   the S domain (`deembed_s`). Writes `_deembedded.s<N>p` with one `!` comment line per port and
   `<basename>_deembedding.json`. The maths is a copy of `test_data/port_deembedding_study/soc_deembed.py`;
   tests in `tests/test_deembedding.py`. The standards' own result folders are skipped
   (`_standard_folder_of()`).
   Without port walls, `port_deembedding()`:
   if `port_information.json` gave port `length`/`width`, computes a parasitic series inductance
   per port using a flat-ribbon-inductor formula credited to F.E. Terman's *Radio Engineers
   Handbook* (1945):
   ```python
   def flat_strip_inductance(length, width, thickness, unit):
       return 2e-7 * length * unit * (
           math.log(2*length/(width+thickness)) + 0.5 + 0.2235*(width+thickness)/length
       )
   ```
   (`thickness=0` always — "Palace ports are 2D sheets with no thickness"). The elements of a
   multielement port are in parallel, so their inductances are combined in parallel. It then puts a
   *negative* series inductor of that value in front of each port, as a scikit-rf `Circuit` with
   explicit, named connections (external port n — `media.inductor` — DUT port n), and writes the
   result as `<basename>_deembedded.s<N>p`. Tube ports, and ports without geometry data, get no
   inductor (a tube port stands for a real conductor whose inductance belongs to the result).
   Applied to both the plain and (if present) the `_dc`-extrapolated file.
   With `"deembedding": "none"` in `port_information.json` (`settings['deembedding'] = 'none'`),
   no `_deembedded` file is written.

### 9.3 — End-to-end summary

```
model script
  → simulation_setup.create_palace(excite_ports, settings)
      writes config.json (Problem.Output = "output/<model_basename>") + <model>.msh + port_information.json
      into <script_dir>/palace_model/<model_basename>_data/
      with port walls also config_cal_<side>_<L|2L>.json + meshes + <name>.key per standard, same folder
  → utilities.create_run_script(sim_path)
      copies combine_extend_snp.py next to the model, writes run_sim: the standards first (skipped
      when output/<model>_cal_*/cal.key matches the key), then "run_palace config.json", a check of
      the combine_snp wrapper, then "combine_snp"

./run_sim  (or the model script's own start_simulation=True auto-run)
  → run_palace config.json     [machine-specific, on PATH — repo's own dev version:
                                 apptainer exec ~/palace.sif palace -np 8 config.json, Linux-only]
      Palace writes output/<model_basename>/port-S.csv (+ other native files)
  → combine_snp                [machine-specific, on PATH — repo's own dev version runs
                                 ./combine_extend_snp.py, else ~/scripts/combine_extend_snp.py]
      finds port-S.csv, cross-references port_information.json for Z0/geometry,
      writes <model_basename>.s<N>p, then optionally _dc.s<N>p and _deembedded.s<N>p
```

**Run summary**: `scripts/palace_summary.py [search_path] [--plot] [--model-basename NAME]` (in the
pip package also `python -m gds2palace.scripts.palace_summary`) finds every run directory with a
`config.json` below `search_path` and prints degrees of freedom, mesh size, run time, peak RAM and
AMR error indicators. For runs with adaptive mesh refinement it also writes the AMR table as
`mesh_convergence_summary.txt` into the run directory, and with `--plot` a `convergence.png` (needs
matplotlib). It exits non-zero when a run has no results yet.

**`scripts/build_pypi_readme.py`** writes `README_pypi.md` (gitignored) from `README.md` with
absolute links; `pyproject.toml` uses it as the PyPI description, so run it before `python -m build`.

---

## 10. Creating field dumps

In addition to S-parameters, Palace can write a full 3D field-solution dump (viewable in ParaView)
at specific frequencies, via `settings['fdump']` — a list of frequencies in Hz, same shape as
`fpoint` (§6):
```python
settings["fdump"] = [15e9]   # save a field dump at 15 GHz
```
(real usage: `workflow/palace_L2n0.py`; likewise `workflow/palace_butlermatrix_dump93.py`
with `[93e9]`).

Mechanically, this is threaded straight into `config.json`'s frequency sweep list
(`Solver.Driven.Samples`, built in `create_model()`): each `fdump` frequency becomes its own `"Type": "Point"`
entry in `Solver.Driven.Samples`, with **`"SaveStep": 1`** — as opposed to a plain `fpoint`
discrete frequency, which gets `"SaveStep": 0`. `SaveStep: 1` is the flag that tells Palace to
write field-solution output at that sample; gds2palace itself does not configure a separate output
directory or file format for this — it's entirely Palace's own native field-dump mechanism,
written under the same `Problem.Output` directory as the raw `port-S.csv` results (§9.1).

Real usage from the user guide (`workflow/palace_L2n0.py`, an octagon inductor with via ports): with
`settings["fdump"] = [15e9]`, opening Palace's resulting field-dump output in ParaView shows the
current density distribution across the structure at 15 GHz — useful for sanity-checking where
current is actually flowing (e.g. confirming skin-effect crowding, or spotting an unintended
current path), not something derivable from S-parameters alone.

**When to use it**: `fdump` is for visual/qualitative inspection of one or a few specific
frequencies, not for production S-parameter extraction — don't add it to every frequency in a
sweep (that multiplies Palace's output size and runtime for no benefit). Pick one or two
frequencies of specific interest (a resonance, a suspected problem frequency), the way both real
examples above do.

---

## 11. Elmer FEM — the alternative solver path

Elmer FEM (https://www.elmerfem.org/) is a **second, independent, also-not-included** open-source
FEM solver — a genuine alternative back end to Palace, not a pre/post-processing helper of it.
The user guide (section "Installing Elmer FEM") is explicit: *"Elmer FEM is not
distributed with gds2palace and must be installed separately... gds2palace needs to find two Elmer
command-line tools: `ElmerGrid` (mesh conversion) and `ElmerSolver` (the solver itself)."* On
Windows, gds2palace looks for `%ELMER_HOME%\bin\ElmerGrid.exe`; on Linux/macOS, both tools must be
on `PATH`.

Choosing Elmer instead of Palace is a **one-line change at the very end of an otherwise identical
model script** — same `settings`, same ports, same `stackup_reader`/`gds_reader` calls:
```python
# Palace:
config_name, data_dir = simulation_setup.create_palace(excite_ports, settings)
utilities.create_run_script(sim_path)
# Elmer:
config_name, data_dir = simulation_setup.create_elmer(excite_ports, settings)
utilities.create_elmer_run_script(sim_path, settings)
```
Both funnel into the same `create_model()` engine (§4), gated by `settings['elmer']`. Documented
behavioral differences: Elmer's EM solver always solves *all* defined ports in one run (no
per-excitation skip trick), has no adaptive-frequency-sweep equivalent, and has no sheet resistors,
multielement or tube ports, or port walls — those are Palace only (a port wall in an Elmer model
stops with an error). The EM linear solver is direct (MUMPS) by default; `settings['iterative'] =
True` selects the iterative recipe (order 2). Results are Elmer's `scalar_results`, which
`combine_snp` converts like Palace's `port-S.csv`.

There's a third mode, `create_elmer_thermal(settings)` — Elmer-only, no Palace equivalent,
steady-state thermal (temperature) simulation using `heatsource`/`constanttemp` objects (marker
polygons on extra GDS layers, `thermal_objects.layers` added to the layer list before `read_gds()`)
instead of EM ports. `util_elmer.write_elmer_thermal_file()` writes `case.sif`: the heat equation,
iterative by default (BiCGStabl with an ILU3 preconditioner, at most 10000 iterations;
`settings['iterative'] = False` gives the direct solver UMFPACK, since MUMPS isn't in the Windows
Elmer build), nonlinear iterations when a material has a temperature-dependent conductivity table.
A material with a lateral and a vertical thermal conductivity (§3.1) is written as a diagonal tensor,
`Heat Conductivity(3)`, with one table column per direction when a direction has a table
(`_elmer_heat_conductivity()` in `util_simulation_setup.py`).
Details: the user guide's "Using gds2palace with Elmer FEM for thermal simulation" chapter and
`more_examples/thermal_simulation_using_Elmer/Elmer_Thermal_Workflow.md`. `util_thermal_map.py`
(§2) fills in heat-source powers from a circuit simulation.

---

## 12. Case study: the inductor synthesis examples

There are **two** inductor-synthesis examples in `more_examples/`:

1. `inductor_synthesis_no_external_library/synthesize_ihp_inductor_v4.py`
2. `inductor_synthesis_using_pclab_library/synthesize_inductor_v11.py`

**This chapter primarily analyzes #1**, which its own sibling README (in example #2's directory)
cross-references as the more illustrative, self-contained example of gds2palace usage: *"For
inductor synthesis in IHP SG13G2 without need for an external geometry library, see this
example."* Example #2 delegates all geometry generation to a vendored, modified copy of the
third-party [pcLab](https://github.com/dgrujic/pcLab) library — it's really a demo of "gds2palace +
pcLab integration," not of gds2palace's own API surface. The differences are summarized in §12.5.

### 12.1 — What's actually being "synthesized"

**Geometry, not just EM verification of a pre-drawn part.** The script draws a symmetric
octagonal spiral inductor directly to GDSII in Python (via `gdspy` primitives — gdspy is not a
gds2palace dependency since 0.11.0, so these examples need `pip install gdspy`), for a whole grid of
candidate `(turns N, width w, spacing s)` combinations, computing each candidate's required outer
diameter `D` from a closed-form equation. gds2palace is used purely as the **EM solver backend
inside an optimization loop** — called once per candidate geometry, many times per run — not to
generate geometry itself.

The example's own README states its 8-step "principle of operation" plainly:

1. Determine candidate implementations via closed-form equations (required diameter for target L),
   filtering out ones that are geometrically invalid or exceed a maximum diameter.
2. Create GDSII layouts for every candidate (including ports + ground return).
3. Run a **fast, low-order** FEM sweep over all candidates via gds2palace.
4. Evaluate the top-N candidates by Q factor at the target frequency, and re-tune each toward the
   target L.
5. After a fixed number of re-tune iterations, pick the single best candidate and run a **full,
   wideband, high-order** FEM sweep on it.
6. Plot L and Q of that final candidate.
7. Generate a final "production" GDSII with all the extra IHP SG13G2 OPDK layout features required
   for a real PDK cell (no simulation-only geometry).

### 12.2 — The optimization loop, precisely

```
closed-form estimate (Wheeler's equation) for D, per (N, w, s) combo
  → draw candidate GDSII (with EM ports + ground-return frame)
  → gds2palace EM sim, order=1 (fast/coarse)     [one create_palace() call per candidate]
  → read back .s2p via skrf.Network, compute differential L/Q at target frequency
  → keep the best-Q candidates, rescale D by sqrt(Ltarget / L_measured)
  → redraw, gds2palace EM sim, order=2 (accurate)   [repeated a *fixed* number of iterations —
                                                       not until convergence]
  → pick the single winner
  → gds2palace EM sim, wideband, order=2 (final)
  → regenerate GDSII with production OPDK decoration layers, no ports/ground frame
```

**This is grid search + a fixed-point rescaling loop, not a real optimizer** — there is no
`scipy.optimize` anywhere in either script. An agent asked to "improve convergence" here should
understand this existing pattern before reaching for a different optimization algorithm.

### 12.3 — How gds2palace is actually called (per candidate)

The per-candidate model-creation function (`create_simulation_model()`) is a direct instance of
§4's canonical pattern, just wrapped in a function and invoked in a loop:

```python
sim_path = utilities.create_sim_path(script_path, model_basename)
simulation_ports = simulation_setup.all_simulation_ports()
for portnumber in range(1, portcount+1):
    simulation_ports.add_port(simulation_setup.simulation_port(
        portnumber=portnumber, voltage=1, port_Z0=50,
        source_layernum=200+portnumber,
        from_layername=ground_layer_name, to_layername=port_layer_name,
        direction='z'))

layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)
allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0],
    metals_list=metals_list, preprocess=settings['preprocess_gds'],
    merge_polygon_size=settings['merge_polygon_size'])

settings['simulation_ports'] = simulation_ports
settings['materials_list']   = materials_list
settings['dielectrics_list'] = dielectrics_list
settings['metals_list']      = metals_list
settings['layernumbers']     = layernumbers
settings['allpolygons']      = allpolygons
settings['sim_path']         = sim_path
settings['model_basename']   = model_basename

excite_ports = simulation_ports.all_active_excitations()
config_name, data_dir = simulation_setup.create_palace(excite_ports, settings)
return config_name, data_dir
```

**Batch execution**: rather than running each candidate's Palace solve immediately, the script
collects `config_name`s across a whole sweep phase and writes a single shell script
(`simulate_all`) that `cd`s into each candidate's data directory and runs `run_palace <config.json>`
for all of them **sequentially** — explicitly not parallelized, "to avoid asynchronous finish of
simulation jobs" (a comment in the source) — then runs `combine_snp` once at the end and copies all
resulting `.s*p` files back to the script directory. This whole batch is invoked via
`subprocess.run(simulate_script_filename, shell=True)`, gated on `sys.platform.startswith("linux")`
— **this script's Palace-invocation step only actually runs on Linux**, consistent with §5.

**Results are read back entirely outside gds2palace's own API** — using `skrf.Network` directly on
the Touchstone file `combine_snp` produced, then a script-local `get_diff_model()` function converts
the raw 1/2/3-port Z or Y matrix into a scalar differential inductance/resistance/Q (handling the
optional floating center-tap port by nulling it out algebraically). **There is no gds2palace-
provided S-parameter-to-L/Q utility** — every example that needs to "close the loop" from simulation
results back into a design decision re-implements this kind of post-processing itself.

### 12.4 — Non-obvious patterns worth knowing about (for an agent working on similar scripts)

- **No result caching or reuse** — every run deletes prior `palace_model/`, `*.s?p`, `*.gds`
  output and resimulates everything from scratch (`cleanup_old_data=True` by default). No
  memoization of previously-seen `(N,w,s,D)` combinations, even within a single run.
- **Runtime cost is a first-class, explicitly-acknowledged concern**: the initial sweep alone can
  spawn dozens of full 3D-meshed Palace solves (e.g. 2 turn-counts × 8 widths × 4 spacings = up to
  64 combinations, filtered by geometric validity). The script gives the user a 10-second
  `Ctrl+C`-to-abort window before committing to the full batch.
- **FEM order is deliberately varied by phase** — order 1 (fast, less accurate) for the broad
  sweep, bumped to order 2 before the fine-tune loop and kept at 2 for the final wideband run —
  the standard speed/accuracy tradeoff pattern in this codebase (§7).
- **A "faked DC" frequency point** (a low-but-nonzero frequency, e.g. 100 MHz, explicitly commented
  "do not change") stands in for true DC inductance, since a real 0 Hz EM solve is ill-posed — used
  only internally to compute the diameter-rescale factor, not reported to the user.
- **A center-tap port, when present in the drawn geometry, is deliberately excluded from EM
  excitation** during the sweep/fine-tune phases (2-port simulation only, tap left floating) and
  only added back for the final model — meaning intermediate phases produce `.s2p` files while the
  final phase produces `.s3p`. An agent debugging a "file not found" error against one of these
  scripts should check which phase it's in before assuming a bug.
- **Sanity filtering happens before any simulation runs at all**: a candidate whose crossover
  geometry would force physically-invalid via placement, or whose diameter exceeds the configured
  maximum, is dropped from the candidate list before any GDSII is even drawn for it — so the actual
  number of Palace runs in a sweep phase is data-dependent, not simply the full cross-product of
  the configured ranges.
- **The deliverable is a real, PDK-compliant GDSII cell**, not just simulation artifacts: the final
  step regenerates the winning geometry a second time *without* the simulation-only ports/ground
  frame, adding the IHP SG13G2 OPDK decoration layers (`nofill`/`PWell.block`/`NoRCX`/`IND`
  purposes) that a real PDK cell requires, saved with a `final_` prefix alongside its
  `final_`-prefixed verified Touchstone file.

### 12.5 — How the pcLab-based variant (example #2) differs

"No external library" specifically means *no dependency on pcLab* — the SG13G2-specific spiral
drawing, via-array drawing, port/ground-frame drawing, and OPDK decoration that pcLab (plus its
`pin2port`/`ihp_sg13_features` helper modules) would otherwise provide are all reimplemented
directly with `gdspy` primitives in example #1's single script. Concretely, pcLab (vendored at
`more_examples/inductor_synthesis_using_pclab_library/pclab/`) provides:

- A generic technology-rule engine (`pclTech.Technology("SG13G2.tech")`) that geometry classes
  query instead of hard-coded via-rule constants.
- Reusable, technology-agnostic inductor-shape classes (`pclInductor.py`'s `inductorSym`,
  `inductorSymCT`) instead of a single bespoke `symmetric_octa_IHP()` function.
- A generic pin-to-EM-port converter (`pin2port.py`'s `gds_pin2viaport(...)`) that auto-detects
  which side of the bounding box each labeled pin sits on and synthesizes port/frame geometry from
  that, geometrically, rather than example #1's parametric-formula approach.
- A separate, explicit OPDK-decoration post-processing step (`ihp_sg13_features.py`'s
  `gds_add_sg13_features(...)`) rather than example #1's approach of doing decoration inline as
  part of the main drawing function.

The optimization-loop code itself (`create_simulation_model`, `run_models_from_list`,
`get_best_results`, `get_diff_model`, `calc_resize_factor`, the overall sweep→finetune→final flow)
is essentially identical between the two scripts — **the only real difference is in how the
geometry gets drawn**, not in how gds2palace gets used.

---

## 13. Quick checklist — writing a new model script

1. `sys.path.insert(...)` + `from gds2palace import *` (only needed if running against the in-repo
   source rather than an installed package).
2. `utilities.get_script_path/get_basename/create_sim_path` → `sim_path`.
3. Build `settings = {}` with at minimum `margin`, `fstart`/`fstop` (or `fpoint`/`fdump`),
   `refined_cellsize` (§6); `unit` (default `1e-6`) and `fstep` usually too, and `no_gui = True`
   for unattended runs.
4. Define ports via `simulation_setup.all_simulation_ports()` +
   `simulation_ports.add_port(simulation_setup.simulation_port(...))` (§8) — remember `voltage=0`
   defines-but-doesn't-excite a port.
5. `stackup_reader.read_substrate(XML_filename)` → `materials_list, dielectrics_list, metals_list`
   (§3 covers the file format and how to generate/edit one programmatically via `stackup_writer`).
6. `layernumbers = metals_list.getlayernumbers(); layernumbers.extend(simulation_ports.portlayers)`
   (for thermal models `thermal_objects.layers` instead of the port layers).
7. `gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0], metals_list=metals_list, ...)`
   → `allpolygons`.
8. Stuff `simulation_ports`, `materials_list`, `dielectrics_list`, `metals_list`, `layernumbers`,
   `allpolygons`, `sim_path`, `model_basename` into `settings`.
9. `excite_ports = simulation_ports.all_active_excitations()`, then
   `simulation_setup.create_palace(excite_ports, settings)` (or `create_elmer(...)`).
10. `utilities.create_run_script(sim_path)` (or `create_elmer_run_script(sim_path, settings)`).
11. To actually simulate: a working `run_palace` (Palace binary via Apptainer/Spack, on Linux/WSL)
    and `combine_snp` must exist on `PATH` in the execution environment — this repo does not, and
    cannot, provide those. Do not attempt to invoke `palace`/`ElmerSolver` directly; go through the
    generated `run_sim`/`run_elmer` wrapper, which in turn goes through those two `PATH`-resolved
    commands.
12. Simulation results land as `<model_basename>.s<N>p` (+ optionally `_dc`/`_deembedded` variants)
    next to `port-S.csv`, produced by `combine_snp` → `combine_extend_snp.py` (§9) — read them with
    `skrf.Network(...)`, same as every example in this repo does; there is no gds2palace-native
    result-reading API.
