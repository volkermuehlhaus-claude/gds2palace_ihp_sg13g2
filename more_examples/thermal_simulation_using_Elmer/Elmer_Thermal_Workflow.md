# Elmer Thermal Simulation Workflow

This describes how to go from a GDSII layout + stackup XML to a steady-state
thermal (heat conduction) simulation solved by [Elmer FEM](https://www.elmerfem.org/blog/), using
gds2palace. It's a two-step process:

1. **Build the model** — run a Python script that reads your layout and
   stackup, meshes the 3D geometry, and writes Elmer's input files.
2. **Solve it** — run `ElmerSolver` on the generated files.

The rest of this guide walks through that flow using a hand-written model
script, which is the most direct way to see what's actually happening. If you
prefer a GUI instead of writing Python model code, see
[Alternative: using setupThermal](#alternative-using-setupthermal) below —
it drives the same gds2palace functions and produces the same output files.

Worked example files (in this repo):

| File | Role |
|---|---|
| `elmer_thermal_simplest_typicalvalues.py` | Model-building script |
| `SG13_interposer_thermal_typicalvalues.xml` | Stackup with thermal material properties |
| `simplest_with_source.gds` | Layout, including the heat-source/boundary marker layers |

## Prerequisites

- Python with gds2palace and its dependencies (`gdstk`, `gmsh`, `numpy`,
  `shapely`) installed (`pip install gds2palace`), or the `gds2palace`
  package folder placed next to your model script.
- **Elmer FEM** installed, with `ElmerGrid` and `ElmerSolver` available:
  - Windows: set the `ELMER_HOME` environment variable to your Elmer install
    directory (gds2palace looks for `%ELMER_HOME%\bin\ElmerGrid.exe`).
  - Linux/macOS: have `ElmerGrid` and `ElmerSolver` on your `PATH`.

## 1. Stackup XML: thermal material properties

Every `<Material>` used in a thermal run needs **thermal conductivity** data, this is the only parameter evaluated for steady-state thermal simulation so far. Electrical parameters (as used for S-Parameter simulation) are not evaluated:

```xml
<Material Name="TopMetal2" Type="Conductor" Conductivity="30300000.0"
          Density="2700" ThermalConductivity="237" Color="ff8000"/>
```

- `Density` — kg/m³, optional, passed to Elmer but not used in steady state thermal simulation.
- `ThermalConductivity` — a single value in W/(m·K), for materials whose
  conductivity doesn't change meaningfully with temperature.
- `ThermalConductivityTable` — instead of a single value, point to a
  `<Table>` (defined in a `<Tables>` block) for temperature-dependent
  conductivity, e.g. silicon substrate:

```xml
<Material Name="HighResSubstrate" Type="Semiconductor" Conductivity="0.025"
          ThermalConductivityTable="SiliconThermalCond" Density="2329"/>
...
<Tables>
  <Table Name="SiliconThermalCond">
    <Point Temperature="280" Value="163.00"/>
    <Point Temperature="290" Value="155.20"/>
    ...
  </Table>
</Tables>
```

gds2palace writes this straight through as an Elmer temperature-dependent
material table — no manual `.sif` editing needed for this part. With a table,
Elmer solves the model nonlinearly: it starts at the lowest constant temperature
of the model and iterates until the temperatures and the conductivities agree.

## 2. Layout: heat sources and constant-temperature boundaries

In the model script, declare where heat enters and leaves the model:

```python
thermal_objects = simulation_setup.all_thermal_objects()
thermal_objects.add_heatsource(simulation_setup.heatsource(
    power=0.65, source_layernum=201, target_layername='TFR'))
thermal_objects.add_consttemp(simulation_setup.constanttemp(
    temp=298, source_layernum=202, target_layername='BACKSIDEGND'))
```

- `source_layernum` — a **GDSII layer number you draw in the layout**,
  purely as a footprint marker (ordinary polygons, datatype 0). It defines
  the *xy* shape of the source/boundary, not its z-position.
- `target_layername` — the name of an existing `<Layer>` from the stackup
  XML. Its z-range becomes the 3D volume the source/boundary is applied to.
  The marker polygon just needs to overlap that layer's footprint in xy.
- `heatsource(power, ...)` — dissipates `power` Watts, distributed as a
  volumetric heat source over that volume. In the example, 0.65 W is applied
  to the `TFR` resistor layer via marker layer 201. If the marker layer has
  several polygons, `power` is the total for all of them together, not the
  power per polygon. Overlapping or touching polygons are merged into one
  volume.
- `constanttemp(temp, ...)` — fixes that volume's temperature (Kelvin),
  acting as a heat sink/reference boundary. In the example, layer 202 pins
  the `BACKSIDEGND` layer to 298 K (25 °C) — a typical backside heatsink
  boundary.

Both marker layers (201 and 202 here) must actually be drawn as polygons
in the GDSII file, in the cell you're reading (`cellname` in the script) —
gds2palace only picks up what's physically there.

Any layer number that the stackup does not use works as a marker layer. If the same layout also has
EM ports (layers 201–299), put the thermal markers elsewhere, e.g. on 401–499, which none of the
stackups in this repository use; then the EM and the thermal model read their own layers only.

Target layer for **heat sources** must be **volumes** with non-zero thickness, i.e. Zmax 
value larger than Zmin.

Target layer for **constant temperature boundaries** is usually a **sheet** layer with zero thickness, i.e. Zmax=Zmin. This is the layer type also defined for sheet resistors in S-Parameter simulation. A sheet layer needs a resistor material or `PEC`; the example's `BACKSIDEGND` is a `PEC` sheet at the bottom of the substrate. In thermal models, PEC sheets are not meshed, so the layer only gives the z position of the boundary. If the target layer has finite thickness with Zmax different from Zmin, **two** constant temperature boundaries will be created, one at Zmax and the other at Zmin of that target layer.


## 3. Model script settings

Key `settings` for a thermal run (see `elmer_thermal_simplest_typicalvalues.py`):

```python
settings['unit']              = 1e-6   # geometry is in microns
settings['margin']            = 100    # air margin around the layout, in microns
settings['refined_cellsize']  = 5      # extra-fine mesh near heat sources
settings['meshsize_max']      = 100    # coarsest mesh size, in microns
settings['elmer_thermal']     = True   # this is what selects the thermal flow
```

Also set as usual: `gds_filename`, `XML_filename`, `cellname`,
`merge_polygon_size`, and `thermal_objects` (from step 2). The example script
still passes `preprocess_gds` to `read_gds()`; that argument is obsolete and
only prints a note.

Output goes to `elmer_model/<model>_data/`, created next to the script.

### Optional: skip the interactive mesh preview

By default, gmsh opens an interactive 3D viewer after meshing so you can
inspect the geometry before continuing — closing that window lets the script
proceed. For unattended/batch runs, set:

```python
settings['no_gui'] = True
```

### Optional: linear solver

```python
settings['iterative'] = True    # default for thermal models: iterative solver
settings['iterative'] = False   # direct solver (UMFPACK)
```

Thermal models use Elmer's iterative solver by default: BiCGStabl with an ILU3 preconditioner. It needs much less memory than a direct solver and was faster on the test models. The direct solver (UMFPACK) is the fallback if the iterative solver doesn't converge: Elmer then stops with `Too many iterations were needed`. Both give the same temperatures.

The matrix of a thermal model is hard to solve: the thermal conductivity of metal is several hundred times that of the oxide and passivation, and the mesh has thin, flat elements between thin layers. Before gds2palace 0.12.1, the default used an ILU1 preconditioner, which failed to converge on three of four test models.

The same setting has the opposite default for Elmer **EM** models: there, `iterative` is `False` by default, and the direct solver is MUMPS.

### Optional: heat flux and temperature gradient

```python
settings['heat_flux_output'] = True   # default False: temperature only
```

The result file then also holds the heat flux (W/m²) and the temperature gradient (K/m), both as vectors. See [Heat flux and temperature gradient](#heat-flux-and-temperature-gradient) below. It costs a few seconds of run time and makes the result file about 50 % larger.

### Optional: extruded mesh for whole chips

```python
settings['thermal_mesh'] = 'extruded'   # default 'tetrahedral'
```

gmsh's 3D mesher fills every volume with tetrahedra and then fits them to the triangles on the volume's faces. For
layers well under a micron thick that span hundreds of microns, such as the metal planes of a whole chip or
filler-equivalent slabs, this fitting often fails: the log shows `Could not recover boundary mesh`, and the model
stops with volumes without mesh. A finer mesh doesn't reliably help.

A chip is a stack of flat layers, so the extruded mesh skips that step:

1. The outlines of all layers, heat sources and boundaries are cut into faces that don't overlap.
2. gmsh meshes these faces in 2D.
3. The triangles are repeated at every height of the stackup. Each layer becomes one or more rows of prisms, finer
   near the heat sources. Each prism gets the material of what is drawn on its layer there, with the same rules as
   the normal mesh where layers overlap.

There is no 3D meshing step, so a thin layer can't make it fail; it is simply one row of flat prisms. The model files
are the same as with the normal mesh: bodies, materials, heat sources and boundaries.

**Use it for the temperature map of a whole chip with thin metal planes, when the normal mesh fails.** It is a
fallback, not a replacement: for most models the normal mesh is smaller and solves faster.

Limits:

- **Model size.** The cells in the plane are the same on every layer, so the fine cells at a heat source run through
  the whole stack, and the fine rows near the heat source's height run across the whole chip. The model grows with
  the number of heat sources and with how fine they are meshed. An interposer with two small heat sources far apart
  had 3.5 times the nodes of the normal mesh and took longer overall. A whole chip with 0.5 µm cells at 8 npn
  emitters had 2 million nodes; with the 0.1 µm such small heat sources need, 6 million.
- **So not for device temperatures on a whole chip.** The peak temperature of a transistor needs a fine mesh at its
  heat source, which an extruded whole-chip model can't afford. Use a small model of the device region with the
  normal mesh for that.
- **Solver.** Above roughly 1.2 million nodes, Elmer's ILU3 preconditioner (the default for thermal models) stops with
  "Number of nonzeros larger than HUGE(Integer)". Split the model with `settings['ELMER_MPI_THREADS']` and run
  `ElmerSolver_mpi`. The direct solver (`settings['iterative'] = False`) runs out of memory much earlier on this
  mesh.
- **Rare geometry.** Where edges of different layers almost meet, the 2D mesh can get triangles without area.
  gds2palace joins faces thinner than half the grid to a neighbour and repairs the case of a hole touching its
  outline at one point. If one is still left, the build stops with its location, and no mesh is written. Such cases
  turned up on new layouts in the tests, so expect that another one can.

Details:

- **Outlines are snapped to a grid first**, 0.1 µm by default, so that edges of different layers that almost
  coincide don't make tiny cells. `settings['thermal_mesh_grid']` changes it, in drawing units (e.g. `0.5` for
  0.5 µm). A coarser grid gives a smaller model, but also moves edges by up to half of it. Heat sources get a finer
  grid of their own if they are small: 1/20 of their smallest side, so an npn13G2 emitter keeps its size.
- **Heat sources are refined as boxes**: `refined_cellsize` at the source, growing by 0.3 per unit of distance, as in
  the normal mesh. `refined_cellsize_override` works the same way, for heat sources and for metal edges.
- `substrate_refinement` has no effect.

Checked on a whole chip (800 × 1100 µm, 100 mW in a 27 × 17 µm source, 200 µm silicon): without metal, the
temperature rise agrees with the normal mesh within 0.5 % away from the source. At the source, the extruded mesh
settles with fewer cells; the normal mesh rises towards that value as its cells get smaller and was still 1 % below
it at 0.25 µm cells. With all drawn metal and filler-equivalent slabs, which the normal mesh couldn't build, the
extruded model built in under a minute.

## 4. Run the script

```
python elmer_thermal_simplest_typicalvalues.py
```

This reads the layout and stackup, builds and meshes the 3D geometry, shows
the gmsh preview (unless `no_gui` is set — close the window to continue), and
then automatically converts the mesh to Elmer's native format via
`ElmerGrid`.

### Output files (in `elmer_model/<model>_data/`)

| File | What it is |
|---|---|
| `<basename>.msh` | Intermediate gmsh mesh |
| `mesh/` | Elmer-native mesh (produced by `ElmerGrid`) |
| `case.sif` | Elmer Solver Input File: steady-state Heat Equation, materials, body (volume) definitions, the heat source as a volumetric Body Force, the constant-temperature Boundary Condition, and the result output (temperature, min/max, heat flow per boundary; optionally heat flux and temperature gradient) |
| `ELMERSOLVER_STARTINFO` | Tells `ElmerSolver` to use `case.sif` |

It's worth a quick look at the generated `case.sif` before solving,
especially the first time you use a new stackup — it's plain text and easy
to sanity-check (materials, body forces, boundary conditions).

## 5. Run ElmerSolver

gds2palace does **not** launch the solver — run it yourself from the output
directory:

```
cd elmer_model/elmer_thermal_simplest_typicalvalues_data
ElmerSolver
```

`ElmerSolver` finds `case.sif` automatically via `ELMERSOLVER_STARTINFO`.

If you set `settings['ELMER_MPI_THREADS']` to more than 1 in the model
script, gds2palace also partitions the mesh for you (`ElmerGrid ... -metiskway`);
in that case run `ElmerSolver_mpi` instead (with your MPI launcher of choice)
rather than the single-threaded `ElmerSolver`.

### Results

- `thermal_results_t0001.vtu` — full 3D temperature field, open in ParaView.
  With MPI, one file per process and `thermal_results_t0001.pvtu`, which
  ties them together: open that one.
- `thermal_results.dat` — quick min/max temperature summary (plain text).
- `thermal_heatflow.dat` — the heat flow through each constant-temperature
  boundary, in W (gds2palace 0.13.0 and newer). The column names are in
  `thermal_heatflow.dat.names`.

All appear in the `elmer_model/<model>_data/` output directory once
`ElmerSolver` finishes. With MPI, the `.dat` files are summed over the
processes (gds2palace 0.13.0 and newer; before, each process wrote its own
`thermal_results.dat.0`, `.1`, ... and there was no `thermal_results.dat`).

To print a summary of these results:

```
python -m gds2palace.scripts.thermal_summary elmer_model/elmer_thermal_simplest_typicalvalues_data
```

In a clone of the repository, `python scripts/thermal_summary.py <path>` does
the same. Given a folder, it searches it for Elmer thermal models.

```
Elmer thermal results: ...\elmer_thermal_simplest_typicalvalues_data
  Min temperature : 298.00 K
  Max temperature : 346.19 K
  Input power     : 0.65 W

  Heat flow through the constant-temperature boundaries (negative: heat flows into the model)
  Boundary           T (K)  Heat out (W)    Share
  constanttemp_202  298.00        0.6501  100.0 %
  Total                           0.6501  100.0 %
```

### Heat flow through the constant-temperature boundaries

Each constant-temperature boundary removes heat from the model, or adds heat
if it is hotter than its surroundings. `thermal_heatflow.dat` gives this heat
flow for each boundary. With a single heat sink, it takes all the input power.
With several, the table shows where the heat goes, e.g. how much leaves through
the back side and how much through a heat sink on top.

The sign tells the direction. In `thermal_heatflow.dat`, Elmer writes heat that
leaves the model as a negative number; `thermal_summary` and setupThermal show
"heat out" with the sign reversed. In a test with two boundaries, a backside
sink at 298 K took 1.08 W out of the model and a top sink at 310 K put 0.43 W
in, for a 0.65 W heat source.

**This is not a check of the mesh.** The heat flow is computed from the
residual of the FEM equations at the boundary nodes. These residuals add up to
the input power on any mesh, however coarse, so the total always matches. To
find out whether the mesh is fine enough, rerun the model with a smaller
`refined_cellsize` and compare the temperatures.

### Heat flux and temperature gradient

With `settings['heat_flux_output'] = True`, the result file also has the
arrays `temperature flux` (heat flux density, W/m²) and `temperature grad`
(temperature gradient, K/m). Both are 3D vectors: ParaView or setupEM's field
viewer show their magnitude and can draw arrows.

At an interface between two materials, the two quantities behave differently.
The heat flux normal to the interface is the same on both sides: all heat that
leaves one material enters the other. The temperature gradient normal to the
interface jumps by the ratio of the two thermal conductivities: under a heat
source on oxide over silicon, the gradient in the oxide is about 150 times
the gradient in the silicon. Along the interface, it is the other way round:
the gradient is continuous, and the flux jumps.

So gds2palace computes both quantities per element and averages them only
within each body (each material region). At an interface, the result file has
two values at the same place, one for each body. Averaging across the
interface instead would smear these jumps over several elements. On the
example, that put the gradient in the silicon next to the oxide 17 times too
high, over several microns.

For this, the nodes on an interface are duplicated in the result file, once
for each body. The temperature is the same at both copies.

## Alternative: using setupThermal

[setupThermal](https://github.com/VolkerMuehlhaus/setupEM) is a desktop GUI
(from the sibling `setupEM` project) that drives this exact same flow without
writing a Python script by hand:

- **Input Files tab** — pick your GDSII layout and stackup XML, same as
  `gds_filename`/`XML_filename` above.
- **Thermal objects tab** — add one row per heat source or constant-temperature
  boundary: GDSII source layer, target stackup layer name, and power (W) or
  temperature (K). This is the GUI equivalent of the
  `thermal_objects.add_heatsource(...)` / `add_consttemp(...)` calls in
  step 2 above.
- **Create Model tab**:
  - **"⚙️ Create mesh and simulation settings file"** generates the
    equivalent Python model script from your GUI settings, then runs it —
    same mesh, `case.sif`, and `ELMERSOLVER_STARTINFO` as described above.
  - **"▶️ Start Simulation"** launches `ElmerSolver` directly from the app,
    streaming its output into the on-screen log — no separate terminal step.
- The **Model** tab shows the generated Python code, so you can inspect or
  export it if you'd rather take over from there manually (e.g. to hand-tune
  something the GUI doesn't expose).

Everything in the sections above about material thermal properties, marker
layers, and output files applies the same way whether the model was built by
hand or through setupThermal — it's the same gds2palace functions underneath.
