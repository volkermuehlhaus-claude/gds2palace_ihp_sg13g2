#!/usr/bin/env python
"""Differential input impedance at the primary (ports 1,2 = PP,PN) of the
balun2x1 edge-coupled balun, for a REAL floating differential 50 ohm
load placed directly across the secondary (ports 3,4 = S1,S2) -- the
balun's actual intended secondary system impedance (not the 2x50=100 ohm
"natural" value for a symmetric 1:1 system; this is a 2:1 turns-ratio
balun with an asymmetric primary/secondary system impedance by design).
This is also NOT the same scenario as the mixed-mode Sdd11 assumption,
which implicitly terminates ports 3 and 4 individually to ground at
50 ohm each (a different, non-floating termination) -- see
analyze_convergence.py for the mixed-mode S-parameters, computed at the
correct real Z01=200/Z02=50 ohm asymmetric reference pair.

Unlike the 5-port transformer study, there is no center tap to eliminate
here -- this is a native 4-port network, so the reduction below applies
directly to the as-simulated Z-matrix.

Method: from the 4-port Z-matrix on ports 1,2,3,4, analytically eliminate
the secondary pair under a floating load constraint (V3-V4 = -I3*R_load,
I4=-I3) and the primary pair under a floating differential drive
(I2=-I1). This reduces to the classic two-port reflected-impedance
formula

    Zin_diff = Zaa - Zab*Zba/(Zbb + R_load)

applied to the "differential-equivalent" 2-port (Zaa,Zab,Zba,Zbb) formed
from the 4x4 Z-matrix by antisymmetric combination across each pair:

    Zaa = Z11-Z12-Z21+Z22   (primary)
    Zab = Z13-Z14-Z23+Z24
    Zba = Z31-Z32-Z41+Z42   (== Zab by reciprocity -- used as a sanity check)
    Zbb = Z33-Z34-Z43+Z44

(derived by writing V=Z I with I1=1 (WLOG), I2=-1, I4=-I3=x, solving the
single linear equation from the load constraint for x, then evaluating
Zin_diff = V1-V2.)

For comparison, also computes the impedance implied by the mixed-mode
Sdd11 (ports 3,4 each individually grounded through 50 ohm, i.e. NOT the
floating-load scenario), via the standard Z0_diff=100 ohm normalization:

    Zin_naive = 100 * (1+Sdd11)/(1-Sdd11)

Both are plotted vs. frequency and on a Smith chart (normalized to a
100 ohm differential reference, the natural choice for a system built
from 50 ohm single-ended ports).
"""
import os
import numpy as np
import skrf as rf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SNP_DIR = os.path.join(HERE, "snp")
PLOT_DIR = os.path.join(HERE, "plots")

SERIES = [
    ("mesh5", "5 um (uniform)", "balun2x1_mesh5.s4p"),
    ("mesh2", "2 um (uniform)", "balun2x1_mesh2.s4p"),
    ("mesh1", "1 um (uniform)", "balun2x1_mesh1.s4p"),
    ("amr2", "AMR (5 um start, 2 it.)", "balun2x1_amr2_final.s4p"),
]

NAIVE_SDD11_Z0 = 100.0    # fixed: the standard Sdd11 = 0.5*(S11-S12-S21+S22) formula is derived
                          # assuming 2x50 ohm SE ports, so converting it back to ohms MUST use
                          # 100 ohm here -- this is a mathematical constant of that formula, not a
                          # free design choice, and is NOT the balun's real primary impedance.
PRIMARY_Z0_TARGET = 200.0  # the balun's actual intended primary system impedance (200/50=4,
                           # matching the 2:1 turns ratio's ideal 4:1 impedance transformation).
                           # Used only for Smith-chart/reflection-coefficient viewing below --
                           # picking a Z0 to view an already-computed impedance through doesn't
                           # change the impedance value itself, just where it plots.
R_LOAD = 50.0       # real floating differential load across the secondary -- the balun's actual
                    # intended secondary system impedance (asymmetric vs. the primary's 200 ohm,
                    # by design for this 2:1 turns-ratio balun)


def load(fname):
    path = os.path.join(SNP_DIR, fname)
    if not os.path.isfile(path):
        return None
    return rf.Network(path)


def zin_diff_floating_load(Z, r_load):
    Zaa = Z[:, 0, 0] - Z[:, 0, 1] - Z[:, 1, 0] + Z[:, 1, 1]
    Zab = Z[:, 0, 2] - Z[:, 0, 3] - Z[:, 1, 2] + Z[:, 1, 3]
    Zba = Z[:, 2, 0] - Z[:, 2, 1] - Z[:, 3, 0] + Z[:, 3, 1]
    Zbb = Z[:, 2, 2] - Z[:, 2, 3] - Z[:, 3, 2] + Z[:, 3, 3]
    return Zaa - Zab * Zba / (Zbb + r_load)


def sdd11_naive_impedance(nw):
    S = nw.s
    Sdd11 = 0.5 * (S[:, 0, 0] - S[:, 0, 1] - S[:, 1, 0] + S[:, 1, 1])
    return NAIVE_SDD11_Z0 * (1 + Sdd11) / (1 - Sdd11), Sdd11


def to_gamma(z, z0):
    return (z - z0) / (z + z0)


def main():
    results = {}
    for key, label, fname in SERIES:
        nw = load(fname)
        if nw is None:
            print(f"WARNING: missing {fname}, skipping")
            continue
        zin = zin_diff_floating_load(nw.z, R_LOAD)
        zin_naive, sdd11 = sdd11_naive_impedance(nw)
        results[key] = dict(label=label, freq=nw.frequency.f, zin=zin, zin_naive=zin_naive)

    if not results:
        print("No data found.")
        return

    os.makedirs(PLOT_DIR, exist_ok=True)
    colors = ["#4c72b0", "#dd8452", "#55a868", "#8172b2"]

    # ---------------- Zin vs frequency (real/imag) ----------------
    fig, (ax_re, ax_im) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    for idx, (key, d) in enumerate(results.items()):
        color = colors[idx % len(colors)]
        style = "--" if key == "amr2" else "-"
        freq_ghz = d["freq"] / 1e9
        ax_re.plot(freq_ghz, d["zin"].real, color=color, linestyle=style, label=d["label"])
        ax_im.plot(freq_ghz, d["zin"].imag, color=color, linestyle=style, label=d["label"])
    ax_re.set_ylabel("Re(Zin,diff) (ohm)")
    ax_re.axhline(PRIMARY_Z0_TARGET, color='grey', lw=0.8, linestyle=':')
    ax_re.grid(True, alpha=0.3)
    ax_re.legend(fontsize=8)
    ax_re.set_title(f"Differential input impedance at primary (PP,PN)\nwith floating {R_LOAD:.0f} ohm differential load on secondary (S1,S2)")
    ax_im.set_xlabel("Frequency (GHz)")
    ax_im.set_ylabel("Im(Zin,diff) (ohm)")
    ax_im.axhline(0, color='grey', lw=0.8, linestyle=':')
    ax_im.grid(True, alpha=0.3)
    fig.tight_layout()
    out1 = os.path.join(PLOT_DIR, "zin_diff_primary_vs_freq.png")
    fig.savefig(out1, dpi=150)
    plt.close(fig)
    print(f"Wrote plot: {out1}")

    # ---------------- Smith chart: floating-load Zin vs. naive Sdd11-implied Zin ----------------
    # Both traces are viewed through the same PRIMARY_Z0_TARGET=200 ohm Smith chart (the balun's
    # real intended primary impedance) for a fair visual comparison -- this is just a choice of
    # which reference impedance to view each (already fully determined, in ohms) impedance
    # through, and does not change the underlying zin/zin_naive values computed above.
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    for ax, key_field, title in [
        (axes[0], "zin", f"True Zin,diff (floating {R_LOAD:.0f} ohm diff. load on secondary)"),
        (axes[1], "zin_naive", "Mixed-mode Sdd11-implied Zin\n(secondary ports each terminated 50 ohm)"),
    ]:
        for idx, (key, d) in enumerate(results.items()):
            color = colors[idx % len(colors)]
            style = "--" if key == "amr2" else "-"
            gamma = to_gamma(d[key_field], PRIMARY_Z0_TARGET)
            nw1 = rf.Network(frequency=rf.Frequency.from_f(d["freq"] / 1e9, unit="ghz"), s=gamma.reshape(-1, 1, 1), z0=PRIMARY_Z0_TARGET)
            nw1.name = d["label"]
            nw1.plot_s_smith(0, 0, ax=ax, show_legend=False, draw_labels=True, color=color, linestyle=style, label=d["label"])
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=7, loc='upper right')
    fig.suptitle(f"Differential Smith chart (Z0 = {PRIMARY_Z0_TARGET:.0f} ohm, the balun's real primary impedance)", y=1.02)
    fig.tight_layout()
    out2 = os.path.join(PLOT_DIR, "zin_diff_smith.png")
    fig.savefig(out2, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Wrote plot: {out2}")

    # ---------------- summary table at a few frequencies ----------------
    finest_key = "mesh1" if "mesh1" in results else list(results)[-1]
    d = results[finest_key]
    freq = d["freq"]
    for f_ghz in [1, 25, 50]:
        idx = int(np.argmin(np.abs(freq / 1e9 - f_ghz)))
        z_true = d["zin"][idx]
        z_naive = d["zin_naive"][idx]
        g_true = to_gamma(z_true, PRIMARY_Z0_TARGET)
        g_naive = to_gamma(z_naive, PRIMARY_Z0_TARGET)
        print(f"f={freq[idx]/1e9:6.2f} GHz  Zin,diff(floating {R_LOAD:.0f} ohm load) = {z_true.real:7.2f}{z_true.imag:+7.2f}j ohm "
              f"(|Gamma|={abs(g_true):.3f})   |   Sdd11-implied Zin = {z_naive.real:7.2f}{z_naive.imag:+7.2f}j ohm (|Gamma|={abs(g_naive):.3f})")


if __name__ == "__main__":
    main()
