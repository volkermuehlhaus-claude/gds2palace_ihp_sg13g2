# EM simulation tools for IHP SG13G2: which tool for what

These open-source tools take an RFIC layout from KLayout to S-parameters, and from there back
into the circuit simulation. Each tool is its own package: install only what you use. They are
made for IHP SG13G2 and SG13CMOS5L, but the solver workflows read any GDSII layout with a
matching stackup file.

## The flow at a glance

![From a KLayout layout to the circuit testbench: klayout_em_export, gds_prepare_for_EM, then setupEM or a model script with gds2palace and AWS Palace (FEM), or a model script with gds2openEMS and openEMS (FDTD), then S-parameters, plot_snp, snp2le and lumpedmodel, and the testbench in ngspice, Xyce or VACASK](png/toolchain_flow.svg)

The layout gets its ports in KLayout, with the plug-in or drawn by hand on GDS layers 201 and
up. One of the two solver workflows turns it into S-parameters, and a circuit model of these
goes into the testbench.

A thermal simulation of the same layout (temperature of each device) uses the FEM side:
setupThermal builds the model with gds2palace, and Elmer solves it.

## Which tool do I need?

| I want to ... | Tool | How to get it |
|---|---|---|
| Set up an EM simulation where I draw: ports, the region, transistors and resistors as ports | [klayout_em_export](https://github.com/VolkerMuehlhaus/klayout_em_export), a KLayout plug-in. It hands the model to setupEM | KLayout: Tools > Manage Packages |
| Simulate a layout without writing Python: settings, Palace run, result plots, field viewer | [setupEM](https://github.com/VolkerMuehlhaus/setupEM) | [install script](#installing), or `pip install setupEM` |
| Write models as Python scripts: sweeps, automation, full control | [gds2palace](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2) (FEM) or [gds2openEMS](https://github.com/VolkerMuehlhaus/gds2openEMS) (FDTD) | [install script](#installing), or `pip install gds2palace`; gds2openEMS: see [below](#installing) |
| Find the temperature of transistors and resistors | setupThermal, part of setupEM, with the [Elmer](https://www.elmerfem.org/) solver | with setupEM; Elmer separately |
| Make a tape-out layout simulation-ready: remove dummy fill, merge via arrays | [gds_prepare_for_EM](https://github.com/VolkerMuehlhaus/gds_prepare_for_EM). Also in setupEM (Tools > Simplify GDS) and in the KLayout plug-in | `pip install gds_prepare_for_EM` |
| Create or change a stackup file for another technology or chip thickness | Stackup Editor: in setupEM under Tools > Edit Stackup XML, and the `stackupEditor` command of gds2openEMS | with setupEM or gds2openEMS |
| Look at a GDSII file, or make a picture of it, without KLayout | [gds_viewer](https://github.com/VolkerMuehlhaus/gds_viewer) | `pip install gds_viewer` |
| Plot S-parameters: dB, phase, Smith chart | [plot_snp](https://github.com/VolkerMuehlhaus/plot_snp), or setupEM's result viewer | `pip install plot_snp` |
| Use the EM result in ngspice, Xyce or VACASK | Create Circuit in the KLayout plug-in, or Model Fit in setupEM. Both use [snp2le](https://github.com/iic-jku/snp2le) | `pip install snp2le` |
| Extract L, Q, C or line parameters, or a wideband inductor model | [lumpedmodel](https://github.com/VolkerMuehlhaus/lumpedmodel): scripts for inductors, MIM capacitors and lines | clone the repository |
| Let an AI assistant build, check and run models | [gds2palace_mcp](https://github.com/VolkerMuehlhaus/gds2palace_mcp), an MCP server for gds2palace | `pip install gds2palace_mcp` |

## Palace or openEMS?

Both workflows start from the same layout and give Touchstone files. What differs:

| | gds2palace with AWS Palace | gds2openEMS with openEMS |
|---|---|---|
| Method | FEM, frequency domain | FDTD, time domain |
| Where the solver runs | Linux. On Windows in WSL, or on a remote Linux machine | Windows, Linux and macOS |
| User interface | setupEM, or Python model scripts | Python model scripts |
| From the KLayout plug-in | the export opens in setupEM | the model script is written by hand from the export |
| One simulation gives | all excited ports | one excited port: a full S-matrix needs one run per port |
| Also there | thermal simulation (Elmer), calibrated ports at the layout edge (port walls), large regions simulated in pieces | antenna far field, GPU engine |

**Each solver has its own stackup files.** Take the stackup from the repository of the workflow
you use: gds2palace stackups for Palace and Elmer, gds2openEMS stackups for openEMS. They model
some layers differently, e.g. the MIM dielectric, and the wrong one gives meshing errors or wrong
results.

## Installing

**gds2palace, setupEM and the Palace solver, in one step.** One script creates a Python
environment with gds2palace and setupEM, installs AWS Palace as a ready-made container image and
sets up the scripts that run a model. No clone of a repository is needed:

- Linux: [`install_gds2palace.sh`](../scripts/install_linux/README.md)
- Windows: [`install_gds2palace.bat`](../scripts/install_windows/README.md). gds2palace and
  setupEM run on Windows, Palace runs in WSL.

**Only the Python packages**, e.g. when Palace runs on another machine: `pip install setupEM`
(installs gds2palace too) or `pip install gds2palace`.

**gds2openEMS** needs openEMS with its Python modules first, in the same Python environment:
see "System requirements" in the
[gds2openEMS README](https://github.com/VolkerMuehlhaus/gds2openEMS#system-requirements).
Then `pip install gds2openEMS`.

**The KLayout plug-in** comes from KLayout's package manager and uses a setupEM installation:
see its [README](https://github.com/VolkerMuehlhaus/klayout_em_export#install).

## Where to start

| Starting point | First steps |
|---|---|
| A layout open in KLayout | "A first run in 15 minutes" in the [user's guide of the KLayout plug-in](https://github.com/VolkerMuehlhaus/klayout_em_export/blob/main/doc/userguide/klayout_em_export_userguide.md) |
| A GDSII file, with the GUI | the [setupEM user's guide](https://github.com/VolkerMuehlhaus/setupEM/blob/main/doc/setupEM_userguide.md) |
| A GDSII file, with a Python script for Palace | the [gds2palace user's guide](userguide_md_format/gds2palace_workflow_userguide.md) and the examples in [`workflow/`](../workflow/) |
| A GDSII file, with a Python script for openEMS | the [gds2openEMS user's guide](https://github.com/VolkerMuehlhaus/gds2openEMS/blob/main/doc/userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md) |
| Questions on mesh, ports, conductor models, run times | the [gds2palace FAQ](FAQ.md) and the measured advice in [`more_examples/mesh_convergence/`](../more_examples/mesh_convergence/README.md) |
