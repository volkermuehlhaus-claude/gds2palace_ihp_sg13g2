# EM model limitations with Elmer FEM output

gds2palace builds EM models for two solvers from the same layout, stackup and model script: AWS Palace (`create_palace()`) and Elmer FEM (`create_elmer()`). Palace is the main target. The Elmer output supports fewer features, and some settings behave differently. This document lists the differences, for gds2palace 0.12.1. How to create and run an Elmer EM model is described in the user's guide, chapter "Using gds2palace with Elmer FEM for EM simulation".

## Overview

| Feature | Palace | Elmer |
|---|---|---|
| Direct linear solver on Windows | not applicable (Palace runs on Linux) | **fails** with the Elmer Windows build: MUMPS is missing, see section 1 |
| Conductor model `'surface'` | surface impedance that includes the metal thickness | impedance of a thick conductor, metal thickness not used, see section 2 |
| Conductor models `'solve_inside'`, `'solve_inside_skin'` | yes | yes |
| Sheet resistors (`Type="sheet"`, Resistor material) | yes | **no**: left out of the model, the resistor is open (section 3) |
| PEC layers (`Material="PEC"`) | yes | yes |
| Via ports and in-plane ports | yes | yes |
| Multielement ports (several shapes on one port layer) | yes | **no**: the model stops with an error |
| Tube ports (via port shape with an area) | yes | **no**: the model stops with an error |
| Port walls (`'PORTWALL'`, calibrated de-embedding) | yes | **no**: the model stops with an error |
| Excite only some ports (`voltage=0`) | yes | no: all ports are always solved (section 4) |
| Estimated port inductance in the `_deembedded` file, `_dc` file | yes | yes (`combine_snp`) |
| FEM order | 1, 2, 3 | 1, 2; order 3 runs as order 2, with a warning (section 5) |
| Adaptive frequency sweep | yes (default) | no: every frequency point is solved |
| Adaptive mesh refinement (AMR) | yes | no |
| Absorbing boundary (`'ABC'`) | second order | first order (section 6) |
| PEC and PMC boundaries | yes | yes |
| Field dumps (`fdump`) | at the `fdump` frequencies | at every solved frequency |
| Mesh elements with zero volume | warning | the model stops with an error |
| Parallel solving | `run_palace` (MPI processes) | `settings['ELMER_MPI_THREADS']` |

Palace solver settings have no effect on Elmer models: `adaptive_sweep`, `adaptive_mesh_iterations`, `amr_tol`, `amr_max_dof`, `save_adaptive_mesh`, `adaptive_mesh_conformal`, `complex_coarse_solve`, `solver_tol` and `solver_maxits`. The settings that only Elmer uses are `iterative` and `ELMER_MPI_THREADS`.

## 1. Linear solver: no MUMPS in the Elmer Windows build

All Elmer EM solver recipes that gds2palace writes use the direct solver MUMPS (`Linear System Direct Method = zmumps`):

- `settings['iterative'] = False` (the default): `quadratic-direct.sif` for order 2 and `first-order.sif` for order 1, both direct.
- `settings['iterative'] = True`: `quadratic-iterative.sif`, an iterative solver with a multigrid preconditioner, which also uses MUMPS on its lowest level.

The Windows build of Elmer (tested: Elmer 26.2) has no MUMPS. `ElmerSolver` then stops at once with

```
ERROR:: CheckLinearSolverOptions: MUMPS solver has not been installed.
```

So on Windows, no Elmer EM model created by gds2palace runs as written. Run Elmer EM models with an Elmer build that has MUMPS, e.g. on Linux or in WSL on Windows; if `ElmerSolver` doesn't print the error above, MUMPS is there.

The direct solver that the Windows build has, UMFPACK, is not a full replacement. In a test with `workflow/palace_line_viaport.py` turned into an Elmer model (2 µm mesh, one frequency), with `zmumps` replaced by `umfpack` in the solver files:

- order 1, direct: solved, in 145 s;
- order 2, direct: UMFPACK stops in the factorization with status -1 (out of memory);
- order 2, iterative: the same error on the lowest multigrid level.

Elmer thermal models are not affected: they use BiCGStabl with an ILU3 preconditioner by default, and UMFPACK with `settings['iterative'] = False`.

## 2. Conductor loss with the surface model

With `settings['conductor_model'] = 'surface'` (the default), the conductors are not meshed, and their faces get a surface impedance. The two solvers get different surface impedances:

- **Palace:** the surface impedance of a layer with the metal's thickness. At low frequency, where the skin depth is larger than the metal, this gives the resistance of the full cross section.
- **Elmer:** the impedance of a thick conductor (`Good Conductor BC`), from the conductivity alone. The thickness is written into the file only as a comment. This is right where the metal is several skin depths thick. Below that frequency, the impedance keeps falling with the square root of frequency, so the conductor loss is too low and goes to zero towards DC.

For SG13G2, TopMetal2 (3 µm) is four skin depths thick from about 15 GHz, Metal2 to Metal5 only from about 700 GHz and Metal1 from about 1 THz. With Elmer, use `'solve_inside'` or `'solve_inside_skin'` when the conductor loss matters: these mesh the conductors as volumes with their bulk conductivity, the same way as for Palace.

## 3. Sheet resistors

Sheet layers with a Resistor material (in the latest IHP stackups the derived layers `RSIL`, `RPPD` and `RHIGH`) are not supported. gds2palace prints `Sheet resistors not supported yet for Elmer model output!` and writes the model without them: the resistor is then an open circuit. PEC sheets, such as `SUBGND`, `BACKSIDEGND` and `REF_FOR_TRANSISTOR`, work.

## 4. Ports

Elmer solves all ports in one run (a "constraint modes" analysis). Every port defined in the model is part of the S-matrix, whatever its `voltage`, so the Palace way to save time by exciting only some ports doesn't exist.

Only simple lumped ports are supported: one sheet per port, a via port drawn as a line or an in-plane port drawn as a rectangle. These stop the model with an error:

- several shapes on one port layer (a multielement port);
- a via port shape with an area, which gds2palace 0.12.0 and newer turns into a tube port;
- `'PORTWALL'` in `settings['boundary']` (port walls with calibrated de-embedding).

`combine_snp` converts Elmer's `scalar_results` to Touchstone and writes the `_deembedded` file with the estimated port inductance removed and the `_dc` file, as for Palace.

## 5. FEM order

Elmer has recipes for order 1 and order 2. `order = 3`, which is valid for Palace, runs as order 2, and gds2palace prints a warning when the model is created (gds2palace 0.12.1 and newer; before, order 3 got the order-1 recipe without a message). Use order 2 for Elmer results.

## 6. Absorbing boundary

`'ABC'` (and `'PML'`, which gds2palace treats as `'ABC'`) gives Palace a second-order absorbing boundary and Elmer `Absorbing BC = True`, a first-order condition. A first-order boundary reflects more of a wave that doesn't hit it head-on. The distances recommended in [`more_examples/simulation_boundary`](../more_examples/simulation_boundary/README.md) were found with Palace; check them for an Elmer model by moving the boundary out and comparing.

## 7. Frequencies and field dumps

Palace's adaptive frequency sweep solves a few frequencies and interpolates the rest. Elmer solves every frequency in `frequencies.dat`, so the run time grows with the number of points: choose `fstep` and `fpoint` accordingly. Field dumps are written at every solved frequency as soon as `fdump` is set, not only at the `fdump` frequencies.

## 8. Mesh quality

Mesh elements with zero volume (flat tetrahedra, e.g. in a thin dielectric between two close metals) make Elmer stop with "Degenerate 3D element" and a NaN result. gds2palace checks for them before the mesh is written: for Palace it prints a warning, for Elmer it stops with an error and lists where they are. A smaller `refined_cellsize` or `meshsize_max` there usually helps.
