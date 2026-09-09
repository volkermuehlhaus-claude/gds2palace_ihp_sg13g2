#!/usr/bin/env python
"""Mesh convergence analysis for the Transformer_IMN 5-port structure.

Reads de-embedded 5-port Touchstone files from results/snp/, reduces each to
the 4-port subnetwork on ports 1,2,4,5 (port 3, the primary center tap, is
dropped -- equivalent to leaving it terminated in its 50 ohm reference
impedance), computes mixed-mode Sdd11/Sdd21/Sdd22 (primary differential pair
= ports 1,2; secondary differential pair = ports 4,5) via the classical
Bockelman-Eisenstadt formulas, then computes delta-S tables and overlay plots
across mesh variants.

Mixed-mode formulas (derived directly, not via skrf.se2gmm, to avoid any
ambiguity in that API's port-ordering convention for a 2-pair network):
given the 4-port subnetwork with local port order [1:primary+, 2:primary-,
3:secondary+, 4:secondary-] (0-indexed 0,1,2,3):

    Sdd11 = 0.5 * (S11 - S12 - S21 + S22)   # primary differential return loss
    Sdd21 = 0.5 * (S31 - S32 - S41 + S42)   # primary -> secondary diff. transmission
    Sdd22 = 0.5 * (S33 - S34 - S43 + S44)   # secondary differential return loss

(derivation: apply a1=1, a2=-1, a3=a4=0 unit differential stimulus at the
primary pair; b_d1 = b1-b2, b_d2 = b3-b4; Sdd_i1 = b_di / (a1-a2).)
"""
import os
import csv
import numpy as np
import skrf as rf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SNP_DIR = os.path.join(HERE, "snp")
PLOT_DIR = os.path.join(HERE, "plots")

UNIFORM_SERIES = [
    # mesh5 (5 um) omitted: Palace crashes (GetMaxSingularValue NaN) at this
    # cell size for this geometry -- see report for details.
    ("mesh4", "4 um (uniform)", "transformer_mesh4um.s5p"),
    ("mesh3", "3 um (uniform)", "transformer_mesh3um.s5p"),
    ("mesh2", "2 um (uniform)", "transformer_mesh2um.s5p"),
    ("mesh1", "1 um (uniform)", "transformer_mesh1um.s5p"),
]
AMR_ENTRY = ("amr3", "AMR (2 um start, 3 it.)", "transformer_amr3_final.s5p")

# ports 1,2,4,5 (1-indexed) = 0,1,3,4 (0-indexed); port 3 (center tap) dropped
KEEP_PORTS_0IDX = [0, 1, 3, 4]


def find_design_freq_hz(freq, sdd21):
    """Center of the minimum-insertion-loss band (peak |Sdd21|'s -3dB band),
    rounded to the nearest 10 GHz. Determined from the finest-mesh result."""
    mag_db = db(sdd21)
    peak_idx = int(np.argmax(mag_db))
    peak_db = mag_db[peak_idx]
    above = mag_db >= (peak_db - 3.0)
    # contiguous run of 'above' that contains peak_idx
    lo = peak_idx
    while lo > 0 and above[lo - 1]:
        lo -= 1
    hi = peak_idx
    while hi < len(above) - 1 and above[hi + 1]:
        hi += 1
    center_hz = 0.5 * (freq[lo] + freq[hi])
    return round(center_hz / 10e9) * 10e9


def delta_db_at_freq(fa, xa, fb, xb, freq_hz):
    ia = int(np.argmin(np.abs(fa - freq_hz)))
    ib = int(np.argmin(np.abs(fb - freq_hz)))
    if abs(fa[ia] - freq_hz) > 0.6e9 or abs(fb[ib] - freq_hz) > 0.6e9:
        return None
    return float(abs(db(xb[ib]) - db(xa[ia])))


def load(entry):
    key, label, fname = entry
    path = os.path.join(SNP_DIR, fname)
    if not os.path.isfile(path):
        return None
    nw5 = rf.Network(path)
    # drop the two synthetic sub-1GHz points (0.01/0.02 GHz) that gds2palace
    # injects to replace a requested DC (0 Hz) point -- not real solved
    # frequencies of interest, and not part of the 1-200 GHz linear sweep
    nw5 = nw5['1-200ghz']
    sub = nw5.subnetwork(KEEP_PORTS_0IDX)
    sub.name = label
    return key, label, sub


def sdd_traces(sub):
    """Return (Sdd11, Sdd21, Sdd22) complex arrays vs. frequency for a 4-port
    subnetwork ordered [primary+, primary-, secondary+, secondary-]."""
    s = sub.s
    S11, S12, S21, S22 = s[:, 0, 0], s[:, 0, 1], s[:, 1, 0], s[:, 1, 1]
    S31, S32, S41, S42 = s[:, 2, 0], s[:, 2, 1], s[:, 3, 0], s[:, 3, 1]
    S33, S34, S43, S44 = s[:, 2, 2], s[:, 2, 3], s[:, 3, 2], s[:, 3, 3]
    Sdd11 = 0.5 * (S11 - S12 - S21 + S22)
    Sdd21 = 0.5 * (S31 - S32 - S41 + S42)
    Sdd22 = 0.5 * (S33 - S34 - S43 + S44)
    return Sdd11, Sdd21, Sdd22


def db(x):
    return 20 * np.log10(np.abs(x))


def deg(x):
    return np.angle(x, deg=True)


def max_delta_linear(fa, xa, fb, xb):
    common = np.intersect1d(fa, fb)
    if common.size == 0:
        return None
    ia = np.searchsorted(fa, common)
    ib = np.searchsorted(fb, common)
    return float(np.max(np.abs(xb[ib] - xa[ia])))


def band_edge_delta_db(fa, xa, fb, xb):
    common = np.intersect1d(fa, fb)
    if common.size == 0:
        return None, None
    lo, hi = common[0], common[-1]
    ia_lo, ib_lo = np.searchsorted(fa, lo), np.searchsorted(fb, lo)
    ia_hi, ib_hi = np.searchsorted(fa, hi), np.searchsorted(fb, hi)
    d_lo = abs(db(xb[ib_lo]) - db(xa[ia_lo]))
    d_hi = abs(db(xb[ib_hi]) - db(xa[ia_hi]))
    return float(d_lo), float(d_hi)


PARAMS = ["Sdd11", "Sdd21", "Sdd22"]


def main():
    loaded = []
    for entry in UNIFORM_SERIES:
        result = load(entry)
        if result:
            loaded.append(result)
        else:
            print(f"WARNING: missing {entry[2]}, skipping")
    amr_result = load(AMR_ENTRY)

    if len(loaded) < 2:
        print("Need at least two uniform-mesh results; exiting.")
        return

    traces = {}  # key -> (freq, {param: complex array})
    for key, label, sub in loaded + ([amr_result] if amr_result else []):
        sdd11, sdd21, sdd22 = sdd_traces(sub)
        traces[key] = (sub.frequency.f, {"Sdd11": sdd11, "Sdd21": sdd21, "Sdd22": sdd22})

    # design frequency: center of the finest uniform mesh's minimum-insertion-loss
    # (-3dB around peak |Sdd21|) band, rounded to the nearest 10 GHz
    finest_key = loaded[-1][0]
    finest_freq, finest_sdd21 = traces[finest_key][0], traces[finest_key][1]["Sdd21"]
    design_freq_hz = find_design_freq_hz(finest_freq, finest_sdd21)
    design_freq_col = f"|dS_dB| at {design_freq_hz/1e9:.0f}GHz (design freq.)"
    print(f"Design frequency (center of min. insertion loss band, from {loaded[-1][1]}): {design_freq_hz/1e9:.0f} GHz")

    def fmt(x):
        return f"{x:.4f}" if x is not None else "n/a"

    comparisons = [(loaded[i - 1], loaded[i]) for i in range(1, len(loaded))]
    if amr_result:
        comparisons.append((loaded[-1], amr_result))

    # ---------------- successive comparisons, grouped by param ----------------
    csv_path = os.path.join(HERE, "delta_S_table.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Param", "Comparison", "Max|dS| (linear)",
                          "|dS_dB| at f_low", design_freq_col, "|dS_dB| at f_high"])
        for pname in PARAMS:
            for (key_a, label_a, _), (key_b, label_b, _) in comparisons:
                fa, xa = traces[key_a][0], traces[key_a][1][pname]
                fb, xb = traces[key_b][0], traces[key_b][1][pname]
                max_d = max_delta_linear(fa, xa, fb, xb)
                d_lo, d_hi = band_edge_delta_db(fa, xa, fb, xb)
                d_design = delta_db_at_freq(fa, xa, fb, xb, design_freq_hz)
                writer.writerow([pname, f"{label_a} -> {label_b}", fmt(max_d), fmt(d_lo), fmt(d_design), fmt(d_hi)])
    print(f"Wrote delta-S table: {csv_path}")

    # ---------------- every mesh vs. finest (1um) ----------------
    ref_key, ref_label, _ = loaded[-1]
    vs_finest = list(loaded[:-1])
    if amr_result:
        vs_finest.append(amr_result)

    csv_path_ref = os.path.join(HERE, "delta_S_vs_finest.csv")
    with open(csv_path_ref, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Param", "Mesh", f"Max|dS| vs. {ref_label} (linear)",
                          "|dS_dB| at f_low", design_freq_col, "|dS_dB| at f_high"])
        for pname in PARAMS:
            for key, label, _ in vs_finest:
                fa, xa = traces[key][0], traces[key][1][pname]
                fb, xb = traces[ref_key][0], traces[ref_key][1][pname]
                max_d = max_delta_linear(fa, xa, fb, xb)
                d_lo, d_hi = band_edge_delta_db(fa, xa, fb, xb)
                d_design = delta_db_at_freq(fa, xa, fb, xb, design_freq_hz)
                writer.writerow([pname, label, fmt(max_d), fmt(d_lo), fmt(d_design), fmt(d_hi)])
    print(f"Wrote delta-S-vs-finest table: {csv_path_ref}")

    # ---------------- overlay plots ----------------
    os.makedirs(PLOT_DIR, exist_ok=True)
    colors = ["#4c72b0", "#dd8452", "#55a868", "#c44e52", "#8172b2", "#937860"]
    all_keys = [k for k, _, _ in loaded] + (["amr3"] if amr_result else [])
    all_labels = {k: l for k, l, _ in loaded}
    if amr_result:
        all_labels[amr_result[0]] = amr_result[1]

    for pname in PARAMS:
        fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
        for idx, key in enumerate(all_keys):
            freq, pdict = traces[key]
            color = colors[idx % len(colors)]
            style = "--" if key == "amr3" else "-"
            freq_ghz = freq / 1e9
            ax_mag.plot(freq_ghz, db(pdict[pname]), color=color, linestyle=style, label=all_labels[key])
            ax_phase.plot(freq_ghz, deg(pdict[pname]), color=color, linestyle=style, label=all_labels[key])
        ax_mag.set_ylabel(f"|{pname}| (dB)")
        ax_mag.grid(True, alpha=0.3)
        ax_mag.legend(fontsize=8)
        ax_mag.set_title(f"{pname} vs. mesh refinement")
        ax_phase.set_xlabel("Frequency (GHz)")
        ax_phase.set_ylabel(f"arg({pname}) (deg)")
        ax_phase.grid(True, alpha=0.3)
        fig.tight_layout()
        out_path = os.path.join(PLOT_DIR, f"{pname.lower()}_convergence.png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"Wrote plot: {out_path}")


if __name__ == "__main__":
    main()
