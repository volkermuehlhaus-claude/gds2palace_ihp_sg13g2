# Mesh Convergence Study: D-Band Balun (RupokDas, IHP SG13G2)

- **Model:** `Balun_140-170G_RupokDas_with_ports.gds`, stackup `SG13G2_nosub.xml`
- **Solver:** AWS Palace (FEM), order 2, ABC boundaries, 50 µm air margin
- **Sweep:** 100–200 GHz, 1 GHz step, Palace's PROM-based adaptive frequency sweep (`adaptive_sweep=True`, default)
- **Ports:** 3 via ports (Metal3 → TopMetal2, Z0 = 50 Ω), de-embedded S-parameters used throughout (port parasitic inductance removed)
- **Execution:** remote solve on `hpz2` via `run_palace` (apptainer, Palace 0.17, `-np 16` of 32 cores, 109 GB RAM), jobs run sequentially

## 0. Layout

![Balun layout with port positions labeled, IHP SG13G2 pixel-accurate colors (gds_viewer)](plots/balun_layout_labeled.png)

Measured directly from the GDS (KLayout, layer 134/TopMetal2 and layer 30/Metal3): the balun is a folded edge-coupled line pair, 6-7 µm trace width with a 2 µm gap between the two coupled lines, routed as a rectangular loop with a ~182×201 µm bounding box inside an overall 223×225 µm cell. **Port 1** (bottom-left) feeds the primary line, which runs the full loop and is picked up by the coupled secondary line, brought out as **Port 2** and **Port 3** on the right side, only ~11 µm apart. **Metal3** is a ground/reference plane spanning the entire 223×225 µm cell footprint (aside from two small 5.6×5.6 µm cutouts) — exactly why `refined_cellsize_override` fixes it at a coarse 5 µm regardless of the main sweep setting (§1).

## 1. Method

Two studies were run from the common baseline `palace_balun_mesh2.py` (`refined_cellsize=2`):

- **Uniform mesh sweep:** `refined_cellsize` = 5, 4, 3, 2, 1 µm, `adaptive_mesh_iterations=0`.
- **Adaptive mesh refinement (AMR):** `refined_cellsize=5` (coarse starting mesh), `adaptive_mesh_iterations=5`, Palace's built-in error-indicator-driven AMR (`Tol=1e-2`).

In all runs, `refined_cellsize_override=[['Metal3', 5.0]]` was kept fixed at 5 µm regardless of the main cell size — Metal3 is a wide ground/reference plane that doesn't need fine local mesh, and fixing it keeps DOF growth concentrated on the layers that matter (signal traces, vias, ports) as the main sweep refines toward 1 µm.

Model files: `palace_balun_mesh5.py` … `palace_balun_mesh1.py`, `palace_balun_amr5.py` (all in `test_data/mesh_convergence_D-band_balun/`).

## 2. Uniform mesh sweep — results

| Mesh | DOF | Mesh elements | Solve time | Peak RAM | Error indicator norm |
|---|---:|---:|---:|---:|---:|
| 5 µm | 178,262 | 25,518 | 1m 42s | 2.54 GB | 2.505e-01 |
| 4 µm | 200,354 | 28,714 | 1m 55s | 2.77 GB | 2.325e-01 |
| 3 µm | 238,230 | 34,146 | 2m 16s | 3.15 GB | 2.090e-01 |
| 2 µm | 340,226 | 48,701 | 3m 14s | 4.17 GB | 1.731e-01 |
| 1 µm | 665,874 | 94,232 | 7m 11s | 7.22 GB | 1.175e-01 |

DOF, time, and RAM all grow smoothly and moderately (~3.7× DOF, ~4.2× time, ~2.8× RAM from 5 µm to 1 µm) — no blow-up, all runs comfortably cheap on this hardware.

## 3. Adaptive mesh refinement — results

Starting mesh: 5 µm (identical to the uniform 5 µm run — iteration 1 numbers match it exactly). `adaptive_mesh_iterations=5` was interpreted as a hard budget, not a target: the run used **all 5 iterations** and never dropped below the `Tol=1e-2` error-indicator target (it ended at 5.44e-02, still above tolerance).

### What Palace's `Tol` actually measures (vs. HFSS's "Delta S")

Palace's AMR stopping criterion and HFSS's classic "Delta S" criterion are **not the same kind of quantity**, even though both are configured as a single scalar tolerance:

- **Palace `Tol` (here 1e-2)** is compared against the **error indicator norm** — a residual-/flux-jump-based *a posteriori* estimate of the FEM discretization error in the field solution itself, computed and summed per mesh element (the `Norm`/`Maximum` columns in `error-indicators.csv`, also shown in §3's table). It says nothing directly about S-parameters: it's a statement about how well the mesh resolves the electromagnetic field everywhere in the domain. Each iteration, Palace refines the elements responsible for the largest share of that error (Dörfler marking, `UpdateFraction=0.7`) and re-checks the global norm against `Tol`.
- **HFSS's "Delta S"** is defined directly on the *output quantity of interest*: the maximum change in the S-matrix between two successive adaptive passes. It stops refining as soon as the S-parameters themselves stop moving by more than the threshold (typically 2%) — regardless of how much residual field error remains elsewhere in the mesh.

The practical consequence shows up directly in this study: Palace kept refining for all 5 iterations chasing a field-error target that never fully converged, growing to 4.65M DOF — but the **S-parameter-based** Max ΔS between the last two iterations was already down to 0.0093 (§3 table, "Max ΔS vs. prev.") — smaller than the ΔS between our 2 µm and 1 µm *uniform* mesh points (0.0187, §5b). In other words: by an HFSS-style Delta-S criterion this AMR run was already well converged after iteration 4 (Max ΔS = 0.0212), but Palace's own field-error-based `Tol` had no way to know that and kept going. This is the likely root cause of §6's finding that AMR's cost is out of proportion to its S-parameter accuracy gain for this model.

| Iteration | DOF | Mesh elements | Error norm | Max \|ΔS\| vs. prev. | Solve time | Peak RAM |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 178,262 | 25,518 | 2.505e-01 | n/a | 1m 44s | 2.66 GB |
| 2 | 237,178 | 37,530 | 1.897e-01 | 0.0609 | 4m 21s | 3.42 GB |
| 3 | 583,164 | 100,635 | 1.324e-01 | 0.0406 | 12m 48s | 7.37 GB |
| 4 | 1,679,078 | 299,505 | 8.504e-02 | 0.0212 | 44m 18s | 19.35 GB |
| **Final** | **4,654,886** | **852,533** | **5.439e-02** | **0.0093** | **2h 22m 31s** | **50.97 GB** |

![AMR convergence: error indicator norm and max ΔS per iteration](plots/amr5_convergence.png)

By the final iteration the AMR mesh reached **7× the DOF of the finest uniform mesh (1 µm)**, took **20× longer** than the 1 µm uniform run, and used **7× the peak RAM** — on a 32-core/109 GB machine that's still fine, but it would not fit comfortably on a smaller workstation. Per-iteration Max ΔS (Palace's own linear delta-S vs. the previous iteration) does show real, monotonic convergence (0.061 → 0.041 → 0.021 → 0.009), just not fast enough to reach the 1% target within 5 iterations for this geometry.

## 4. S-parameter overlays (all mesh variants + AMR final)

![S11 magnitude and phase vs. mesh](plots/s11_convergence.png)
![S21 magnitude and phase vs. mesh](plots/s21_convergence.png)
![S23 magnitude and phase vs. mesh](plots/s23_convergence.png)

The curves visually converge as the mesh refines. S11 shows the largest spread — expected, since it's a return-loss trace with a deep null that moves in frequency as the mesh changes (see §5 for why this makes raw dB deltas misleading).

## 5. Delta-S tables

**Metric:** `Max|ΔS|` is the standard HFSS-style convergence metric — the maximum **linear** complex-magnitude difference `|S_b − S_a|` over the common frequency band (same convention `palace_summary.py` uses for AMR iterations). This is deliberately *not* a dB-of-S(a) minus dB-of-S(b) difference: near an S-parameter null (S11 dips to −20…−40 dB in this band), a tiny absolute error produces a huge, physically meaningless dB swing. The `|dS_dB|` columns are a secondary, intuitive readout of the dB change at three specific frequencies: the two band edges (100, 200 GHz) and the 130 GHz design frequency. Tables are grouped by S-parameter first, then by mesh comparison, so each parameter's convergence trend reads top-to-bottom without interleaving.

### 5a. Successive uniform-mesh steps

| Param | Comparison | Max\|ΔS\| (linear) | \|ΔS\|@100GHz (dB) | \|ΔS\|@130GHz (dB) | \|ΔS\|@200GHz (dB) |
|---|---|---:|---:|---:|---:|
| S11 | 5→4 µm | 0.0183 | 0.426 | 1.991 | 0.051 |
| S11 | 4→3 µm | 0.0233 | 0.489 | 3.367 | 0.019 |
| S11 | 3→2 µm | 0.0290 | 0.420 | 5.651 | 0.226 |
| S11 | 2→1 µm | 0.0359 | 0.578 | 4.340 | 0.062 |
| S11 | 1µm→AMR final | 0.0243 | 0.378 | 3.887 | 0.065 |
| S21 | 5→4 µm | 0.0102 | 0.058 | 0.010 | 0.049 |
| S21 | 4→3 µm | 0.0132 | 0.077 | 0.007 | 0.055 |
| S21 | 3→2 µm | 0.0145 | 0.052 | 0.034 | 0.061 |
| S21 | 2→1 µm | 0.0187 | 0.072 | 0.030 | 0.086 |
| S21 | 1µm→AMR final | 0.0150 | 0.058 | 0.016 | 0.079 |
| S23 | 5→4 µm | 0.0093 | 0.182 | 0.129 | 0.083 |
| S23 | 4→3 µm | 0.0126 | 0.264 | 0.191 | 0.097 |
| S23 | 3→2 µm | 0.0147 | 0.324 | 0.253 | 0.154 |
| S23 | 2→1 µm | 0.0169 | 0.360 | 0.283 | 0.166 |
| S23 | 1µm→AMR final | 0.0117 | 0.264 | 0.202 | 0.071 |

Two things stand out here, for different reasons:

- The step-to-step Max\|ΔS\| slightly *increases* as the mesh gets finer (5→4 µm is a 20% cell-size reduction; 2→1 µm is a 50% reduction) — that's the relative refinement step getting larger each time, not divergence. §5b isolates true convergence behavior against a fixed reference.
- **S11 @ 130 GHz shows large, non-monotonic dB deltas (2–5.6 dB)** while S21/S23 at the same frequency stay small (≤0.03–0.28 dB). This is the null-crossing artifact described above, not a sign of poor convergence: S11 has a return-loss null that sits right around 125–135 GHz and shifts slightly with mesh (§2 error-indicator behavior), so 130 GHz lands close to that null for every mesh variant, where a small absolute error in a near-zero complex quantity produces an outsized dB swing. The linear `Max|ΔS|` column (0.018–0.036, in line with S21/S23) is the trustworthy read on S11's actual convergence at this frequency.

### 5b. Every mesh vs. the finest uniform mesh (1 µm) as reference

| Param | Mesh | Max\|ΔS\| vs. 1 µm (linear) | \|ΔS\|@100GHz (dB) | \|ΔS\|@130GHz (dB) | \|ΔS\|@200GHz (dB) |
|---|---|---:|---:|---:|---:|
| S11 | 5 µm | 0.1052 | 1.913 | 6.670 | 0.255 |
| S11 | 4 µm | 0.0870 | 1.487 | 4.679 | 0.306 |
| S11 | 3 µm | 0.0642 | 0.998 | 1.311 | 0.287 |
| S11 | 2 µm | 0.0359 | 0.578 | 4.340 | 0.062 |
| S11 | AMR final | 0.0243 | 0.378 | 3.887 | 0.065 |
| S21 | 5 µm | 0.0554 | 0.259 | 0.081 | 0.252 |
| S21 | 4 µm | 0.0455 | 0.202 | 0.071 | 0.203 |
| S21 | 3 µm | 0.0331 | 0.124 | 0.064 | 0.148 |
| S21 | 2 µm | 0.0187 | 0.072 | 0.030 | 0.086 |
| S21 | AMR final | 0.0150 | 0.058 | 0.016 | 0.079 |
| S23 | 5 µm | 0.0530 | 1.129 | 0.857 | 0.499 |
| S23 | 4 µm | 0.0439 | 0.948 | 0.727 | 0.417 |
| S23 | 3 µm | 0.0314 | 0.684 | 0.536 | 0.320 |
| S23 | 2 µm | 0.0169 | 0.360 | 0.283 | 0.166 |
| S23 | AMR final | 0.0117 | 0.264 | 0.202 | 0.071 |

This view shows clean, monotonic convergence toward the 1 µm result as the uniform mesh refines (S11 linear: 0.105 → 0.087 → 0.064 → 0.036; S21/S23 and their 130 GHz dB deltas similarly monotonic). The AMR final result sits slightly *closer* to the 1 µm reference than the 2 µm uniform mesh does on every parameter — but note this comparison is somewhat circular, since neither AMR nor 1 µm is an independent "truth." S11 @ 130 GHz again breaks the monotonic dB trend (6.67 → 4.68 → 1.31 → 4.34 → 3.89) purely because of the null-crossing effect described above; its linear `Max|ΔS|` (rightmost numeric column) converges cleanly instead.

## 6. Discussion / recommendation

- **Uniform mesh converges smoothly and cheaply.** Going from 2 µm → 1 µm only changes Max\|ΔS\| by ~0.02–0.04 (linear), at a cost of ~3m14s→7m11s and 4.2GB→7.2GB — a reasonable, bounded cost for the accuracy gained.
- **2 µm (the original template's setting) looks like a good working point**: it differs from the 1 µm result by only 0.02–0.04 linear ΔS, at less than half the runtime and RAM of the 1 µm mesh.
- **AMR was not cost-effective here.** With this geometry, a 5 µm start, and a 5-iteration budget, AMR consumed **the entire iteration budget** without reaching its own 1% error-indicator target, ballooning to 4.65M DOF, 2h22m, and 51GB RAM — while landing at an S-parameter accuracy comparable to (not clearly better than) the much cheaper 2 µm uniform mesh. The via-port/seal-ring geometry likely produces sharp, localized error indicators that keep triggering refinement without global convergence. If AMR is worth revisiting, capping it at 2–3 iterations (stopping around 583k–1.68M DOF, 13–44 min) would likely capture most of the benefit at a fraction of the cost — but for this model, plain uniform refinement at 2 µm is simpler, cheaper, and already close to the finest-mesh answer.

## 7. Where everything lives

```
test_data/mesh_convergence_D-band_balun/
├── palace_balun_mesh5.py … palace_balun_mesh1.py   # uniform mesh model scripts
├── palace_balun_amr5.py                            # AMR model script
├── palace_model/palace_balun_<name>_data/           # generated mesh/config + full Palace output
│     (config.json, .msh, palace.json, port-S.csv, error-indicators.csv, ...)
└── results/
    ├── mesh_convergence_report.md                  # this report
    ├── delta_S_table.csv                           # §5a
    ├── delta_S_vs_finest.csv                       # §5b
    ├── analyze_convergence.py                      # regenerates the CSVs/plots above
    ├── render_labeled_layout.py                    # regenerates the labeled layout picture (§0)
    ├── snp/                                        # de-embedded (and raw) Touchstone files, one per mesh point
    │     balun_mesh5um.s3p … balun_mesh1um.s3p
    │     balun_amr5_iter1.s3p … balun_amr5_iter4.s3p, balun_amr5_final.s3p
    │     (each also has a _raw.s3p sibling without port de-embedding)
    └── plots/
          balun_layout.png, balun_layout_labeled.png   # §0
          s11_convergence.png, s21_convergence.png, s23_convergence.png
          amr5_convergence.png
```

All `.s3p` files are de-embedded (port parasitic inductance removed) unless suffixed `_raw`. Re-run `python results/analyze_convergence.py` from `test_data/mesh_convergence_D-band_balun/` (in the `d:\venv\palace` venv) any time to regenerate the tables and plots from the archived `.snp` files.
