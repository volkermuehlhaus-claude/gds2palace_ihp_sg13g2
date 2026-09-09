# Choosing a mesh for your Palace simulation

If you're not sure how fine to mesh your gds2palace model, or whether adaptive mesh refinement (AMR) is worth turning on, this page summarizes what we found across three mesh convergence studies on real IHP SG13G2 structures: a spiral inductor, a transformer, and a D-band coupled-line balun. Each study reruns the same layout at several mesh settings and compares the results, so you can see directly what accuracy you get for what runtime/memory cost.

## Quick recommendations

- **Start with a mesh cell size that gives you at least 2-3 cells across your narrowest trace or gap.** All three structures here have trace widths and gaps in the 2-7 µm range, and a 2 µm cell size consistently gave results within a percent or two of the finest mesh tried, at a fraction of the runtime. Going much coarser than that risks losing accuracy — or, in one case, causing the solver to crash outright on a poorly resolved feature.
- **Use order 2 (Palace's default) for any result you plan to report or trust.** Order 1 runs several times faster, but in our tests it converged to a slightly wrong answer no matter how fine the mesh — refining an order-1 mesh doesn't fix it, only switching to order 2 does. Order 1 is fine for a quick rough look (e.g. checking your port setup or layout), not for final numbers.
- **Don't assume AMR will "just work" if you give it enough iterations.** In two of our three studies, AMR kept refining well past the point where the answer had already stopped changing, burning much more time and memory for no real accuracy gain — and even after using its entire iteration budget, it still hadn't satisfied its own ultra-accurate convergence target. If you use AMR, cap it at around 2 iterations and check whether that's actually better than just picking a uniform mesh directly; it sometimes is, but often isn't worth the extra cost.
- **When in doubt, run two mesh sizes and compare.** That's really all a convergence study is — if your result doesn't change much between a medium and a fine mesh, you're probably fine; if it does, go finer.

## The three studies

- **[Spiral inductor](mesh_convergence_inductor/mesh_convergence_report.md)** — a simple 2-port coil. Inductance and Q factor were evaluated directly, alongside S-parameters. This is the easiest case: even a fairly coarse mesh gets inductance right to within about 1%, and it's the study that also compares FEM order 1 vs. order 2.  
Note this is a single-ended inductor, where current in neighboring turns flows in a similar direction. This means that the local field between adjacent traces changes less sharply than in a differential (symmetric) inductor, where neighboring traces of the two half-coils carry opposite-phase current. That likely makes this structure gentler on the mesh than a differential inductor of similar dimensions would be.
- **[Transformer](mesh_convergence_transformer/mesh_convergence_report.md)** — a 5-port coupled-coil transformer with a center tap. Covers mixed-mode S-parameters and the real input impedance seen under a floating differential load.
- **[D-band balun](mesh_convergence_D-band_balun/mesh_convergence_report.md)** — a compact edge-coupled-line balun for 140-170 GHz. The smallest, most tightly-coupled geometry of the three, and the one where mesh choice mattered most.

## Bottom line

These are three different structures at three different frequency ranges, so the exact numbers won't transfer directly to your design — but the pattern was consistent across all of them: a moderately fine uniform mesh (order 2) got close to the best achievable answer quickly and predictably, while chasing AMR's default convergence target or dropping to order 1 for speed both came with real trade-offs. If your structure is broadly similar in scale to one of these three, start from that study's recommended mesh settings and verify with one finer run before trusting the result.
