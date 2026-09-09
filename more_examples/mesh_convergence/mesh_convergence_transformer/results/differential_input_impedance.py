#!/usr/bin/env python
"""Differential input impedance at the primary (ports 1,2) of the
Transformer_IMN, for a REAL floating differential 100 ohm load placed
directly across the secondary (ports 4,5) -- not the mixed-mode Sdd11
assumption, which implicitly terminates ports 4 and 5 individually to
ground at 50 ohm each (a different, non-floating termination). 100 ohm
is used because a floating load bridging two ports that are each
individually referenced to 50 ohm has a *natural* differential impedance
of 2x50 = 100 ohm -- the same reasoning behind Z_DIFF_REF below.

Port 3 (primary center tap) is treated as AC-grounded (RF short, V3=0 --
e.g. a bypass capacitor to ground), per the actual application, NOT the
50 ohm reference termination used for the mixed-mode Sdd11 comparison
computed elsewhere in this study. It is eliminated from the full 5-port
Z-matrix exactly via the short-circuit port-elimination formula

    Z_reduced[i,j] = Z[i,j] - Z[i,p]*Z[p,j]/Z[p,p]

(p = port 3's index), before the secondary/primary reduction below.

Method: from the resulting 4-port Z-matrix on ports 1,2,4,5, analytically
eliminate the secondary pair under a floating load constraint
(V4-V5 = -I4*R_load, I5=-I4) and the primary pair under a floating
differential drive (I2=-I1). This reduces to the classic two-port
reflected-impedance formula

    Zin_diff = Zaa - Zab*Zba/(Zbb + R_load)

applied to the "differential-equivalent" 2-port (Zaa,Zab,Zba,Zbb) formed
from the 4x4 Z-matrix by antisymmetric combination across each pair:

    Zaa = Z11-Z12-Z21+Z22   (primary, using local 1-indexed labels 1,2,4,5 -> 1,2,3,4)
    Zab = Z13-Z14-Z23+Z24
    Zba = Z31-Z32-Z41+Z42   (== Zab by reciprocity -- used as a sanity check)
    Zbb = Z33-Z34-Z43+Z44

(derived by writing V=Z I with I1=1 (WLOG), I2=-1, I4=-I3=x, solving the
single linear equation from the load constraint for x, then evaluating
Zin_diff = V1-V2.)

For comparison, also computes the impedance implied by the mixed-mode
Sdd11 (ports 4,5 each individually grounded through 50 ohm, i.e. NOT the
floating-load scenario), via the standard Z0_diff=100 ohm normalization:

    Zin_naive = 100 * (1+Sdd11)/(1-Sdd11)

Both are plotted vs. frequency and on a Smith chart (normalized to a
100 ohm differential reference, the natural choice for a system built from
50 ohm single-ended ports).
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
    ("mesh4", "4 um (uniform)", "transformer_mesh4um.s5p"),
    ("mesh3", "3 um (uniform)", "transformer_mesh3um.s5p"),
    ("mesh2", "2 um (uniform)", "transformer_mesh2um.s5p"),
    ("mesh1", "1 um (uniform)", "transformer_mesh1um.s5p"),
    ("amr3", "AMR (2 um start, 3 it.)", "transformer_amr3_final.s5p"),
]

KEEP_PORTS_0IDX = [0, 1, 3, 4]  # ports 1,2,4,5; port 3 dropped (terminated 50 ohm)
Z_DIFF_REF = 100.0  # natural differential reference impedance for 50 ohm SE ports
R_LOAD = 100.0      # real floating differential load across the secondary (2x50 ohm, matches Z_DIFF_REF)


def load_sub(fname):
    path = os.path.join(SNP_DIR, fname)
    if not os.path.isfile(path):
        return None
    nw = rf.Network(path)
    # drop the two synthetic sub-1GHz points (0.01/0.02 GHz) injected by
    # gds2palace to replace a requested DC point -- not real solved frequencies
    nw = nw['1-200ghz']
    return nw.subnetwork(KEEP_PORTS_0IDX)


def eliminate_port_short(Z, p):
    """Exactly eliminate port index p from an (nfreq,N,N) Z-matrix under a
    short-circuit termination (V_p = 0). Returns an (nfreq,N-1,N-1) Z-matrix
    on the remaining ports, in their original relative order."""
    n = Z.shape[-1]
    keep = [i for i in range(n) if i != p]
    Zpp = Z[:, p, p]
    Z_rr = Z[np.ix_(range(Z.shape[0]), keep, keep)]
    Z_rp = Z[:, keep, :][:, :, p]      # (nfreq, N-1)
    Z_pr = Z[:, p, :][:, keep]         # (nfreq, N-1)
    correction = Z_rp[:, :, None] * Z_pr[:, None, :] / Zpp[:, None, None]
    return Z_rr - correction


def load_z4_port3_shorted(fname):
    """Full 5-port Z-matrix with port 3 (index 2) eliminated via a short
    circuit (V3=0), returning the resulting 4-port Z on ports 1,2,4,5 (in
    that order) plus the frequency array."""
    path = os.path.join(SNP_DIR, fname)
    if not os.path.isfile(path):
        return None, None
    nw = rf.Network(path)
    nw = nw['1-200ghz']  # drop the two synthetic sub-1GHz points, see load_sub()
    Z5 = nw.z  # (nfreq,5,5), ports 1,2,3,4,5 -> index 0,1,2,3,4
    Z4 = eliminate_port_short(Z5, 2)  # drop port3 (index2); keeps [0,1,3,4] order
    return nw.frequency.f, Z4


def zin_diff_floating_load_from_z4(Z, r_load):
    # local ports 0,1,2,3 = 1,2,4,5
    Zaa = Z[:, 0, 0] - Z[:, 0, 1] - Z[:, 1, 0] + Z[:, 1, 1]
    Zab = Z[:, 0, 2] - Z[:, 0, 3] - Z[:, 1, 2] + Z[:, 1, 3]
    Zba = Z[:, 2, 0] - Z[:, 2, 1] - Z[:, 3, 0] + Z[:, 3, 1]
    Zbb = Z[:, 2, 2] - Z[:, 2, 3] - Z[:, 3, 2] + Z[:, 3, 3]
    return Zaa - Zab * Zba / (Zbb + r_load)


def sdd11_naive_impedance(sub):
    Z = sub.z
    S = sub.s
    Sdd11 = 0.5 * (S[:, 0, 0] - S[:, 0, 1] - S[:, 1, 0] + S[:, 1, 1])
    return Z_DIFF_REF * (1 + Sdd11) / (1 - Sdd11), Sdd11


def to_gamma(z, z0):
    return (z - z0) / (z + z0)


def main():
    results = {}
    for key, label, fname in SERIES:
        freq, Z4_shorted = load_z4_port3_shorted(fname)
        sub = load_sub(fname)  # port3 terminated 50 ohm, for the naive Sdd11 comparison only
        if freq is None or sub is None:
            print(f"WARNING: missing {fname}, skipping")
            continue
        zin = zin_diff_floating_load_from_z4(Z4_shorted, R_LOAD)
        zin_naive, sdd11 = sdd11_naive_impedance(sub)
        results[key] = dict(label=label, freq=freq, zin=zin, zin_naive=zin_naive)

    if not results:
        print("No data found.")
        return

    colors = ["#4c72b0", "#dd8452", "#55a868", "#c44e52", "#8172b2"]

    # ---------------- Zin vs frequency (real/imag) ----------------
    fig, (ax_re, ax_im) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    for idx, (key, d) in enumerate(results.items()):
        color = colors[idx % len(colors)]
        style = "--" if key == "amr3" else "-"
        freq_ghz = d["freq"] / 1e9
        ax_re.plot(freq_ghz, d["zin"].real, color=color, linestyle=style, label=d["label"])
        ax_im.plot(freq_ghz, d["zin"].imag, color=color, linestyle=style, label=d["label"])
    ax_re.set_ylabel("Re(Zin,diff) (ohm)")
    ax_re.axhline(100, color='grey', lw=0.8, linestyle=':')
    ax_re.grid(True, alpha=0.3)
    ax_re.legend(fontsize=8)
    ax_re.set_title(f"Differential input impedance at primary (1,2), center tap AC-grounded\nwith floating {R_LOAD:.0f} ohm differential load on secondary (4,5)")
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
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    for ax, key_field, title in [
        (axes[0], "zin", f"True Zin,diff (center tap AC-grounded)\n(floating {R_LOAD:.0f} ohm diff. load on secondary)"),
        (axes[1], "zin_naive", "Mixed-mode Sdd11-implied Zin\n(center tap + secondary ports each terminated 50 ohm)"),
    ]:
        for idx, (key, d) in enumerate(results.items()):
            color = colors[idx % len(colors)]
            style = "--" if key == "amr3" else "-"
            gamma = to_gamma(d[key_field], Z_DIFF_REF)
            nw1 = rf.Network(frequency=rf.Frequency.from_f(d["freq"] / 1e9, unit="ghz"), s=gamma.reshape(-1, 1, 1), z0=Z_DIFF_REF)
            nw1.name = d["label"]
            nw1.plot_s_smith(0, 0, ax=ax, show_legend=False, draw_labels=True, color=color, linestyle=style, label=d["label"])
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=7, loc='upper right')
    fig.suptitle(f"Differential Smith chart (Z0 = {Z_DIFF_REF:.0f} ohm)", y=1.02)
    fig.tight_layout()
    out2 = os.path.join(PLOT_DIR, "zin_diff_smith.png")
    fig.savefig(out2, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Wrote plot: {out2}")

    # ---------------- summary table at a few frequencies ----------------
    finest_key = "mesh1" if "mesh1" in results else list(results)[-1]
    d = results[finest_key]
    freq = d["freq"]
    for f_ghz in [1, 55, 80, 200]:
        idx = int(np.argmin(np.abs(freq / 1e9 - f_ghz)))
        z_true = d["zin"][idx]
        z_naive = d["zin_naive"][idx]
        g_true = to_gamma(z_true, Z_DIFF_REF)
        g_naive = to_gamma(z_naive, Z_DIFF_REF)
        print(f"f={freq[idx]/1e9:6.2f} GHz  Zin,diff(floating {R_LOAD:.0f} ohm load) = {z_true.real:7.2f}{z_true.imag:+7.2f}j ohm "
              f"(|Gamma|={abs(g_true):.3f})   |   Sdd11-implied Zin = {z_naive.real:7.2f}{z_naive.imag:+7.2f}j ohm (|Gamma|={abs(g_naive):.3f})")


if __name__ == "__main__":
    main()
