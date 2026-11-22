#!/usr/bin/env python
"""Sketches of the three conductor models and of the two loss errors of the surface model, for README.md.

Cross sections to scale. Thickness and conductivity come from the stackup of the line models
(lines/SG13G2_FEM_200um_passi3D.xml), the skin layer depths from gds2palace's skin_layer_depths(),
the surface impedance from the formula Palace uses for its Conductivity boundary,
Zs = (gamma/sigma) coth(gamma h/2) per face, and (gamma/sigma) coth(gamma h) with "External" (one face).
Writes to results/plots/:

  sketch_conductor_models.png       - 'surface', 'solve_inside', 'solve_inside_skin' on one TopMetal2 trace
  sketch_surface_model_errors.png   - too little loss in a narrow thick trace, too much in a thin ground plane

    python sketch_conductor_models.py
"""
import contextlib
import io
import math
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

from gds2palace import stackup_reader
from gds2palace.util_simulation_setup import skin_layer_depths

HERE = os.path.dirname(os.path.abspath(__file__))
XML = os.path.join(HERE, "..", "lines", "SG13G2_FEM_200um_passi3D.xml")
PLOT_DIR = os.path.join(HERE, "plots")

MU0 = 4e-7 * math.pi
FMAX = 150e9                # highest frequency of the line models and the D-band balun
CELL = 2.0                  # refined_cellsize of the study (um)
W_TRACE = 4.5               # one of the line widths of the study (um)
W_NARROW = 2.01             # the narrowest line of the study (um)

C = dict(metal="#e8a13c", metal_dark="#b86e0c", zs="#c62828", ox="#e3eaf1", cur="#1f5fbf", gnd="#9e9e9e",
         mesh="#6d4c1d", txt="#222222")

# ---------------- data from the files ----------------
with contextlib.redirect_stdout(io.StringIO()):
    MATERIALS, DIELECTRICS, METALS = stackup_reader.read_substrate(XML)


def layer(name):
    m = next(x for x in METALS.metals if x.name == name)
    return m.thickness, MATERIALS.get_by_name(m.material).sigma, m.zmin, m.zmax


T_TM2, SIG_TM2, Z0_TM2, _ = layer("TopMetal2")
T_M1, SIG_M1, _, Z1_M1 = layer("Metal1")
T_MIM, SIG_MIM, _, _ = layer("MIM")
DEPTHS = skin_layer_depths(METALS, MATERIALS, FMAX, 1e-6)[0]["TopMetal2"]     # um, from the surface inward


def skin_depth(f, sigma):
    return 1 / np.sqrt(np.pi * f * MU0 * sigma) * 1e6     # um


F_NO_SKIN = 1 / (math.pi * MU0 * SIG_TM2 * (T_TM2 / 4 * 1e-6) ** 2)    # below this, TopMetal2 is thinner than 4 delta
F_NO_SKIN_M1 = 1 / (math.pi * MU0 * SIG_M1 * (T_M1 / 4 * 1e-6) ** 2)


def zs(f, sigma, h_um, external=False):
    """surface impedance of Palace's Conductivity boundary with Thickness h (one face)"""
    gamma = (1 + 1j) / (skin_depth(f, sigma) * 1e-6)
    h = h_um * 1e-6 * (2 if external else 1)
    return gamma / sigma / np.tanh(gamma * h / 2)


# ---------------- drawing helpers ----------------
def dim_h(ax, z, x0, x1, text, above=True, fs=8.5, color="k"):
    ax.add_patch(FancyArrowPatch((x0, z), (x1, z), arrowstyle="<->", mutation_scale=7, lw=0.8, color=color,
                                 shrinkA=0, shrinkB=0))
    ax.text(0.5 * (x0 + x1), z + (0.12 if above else -0.12), text, ha="center", va="bottom" if above else "top",
            fontsize=fs, color=color)


def dim_v(ax, x, z0, z1, text, side="right", fs=8.5, color="k"):
    ax.add_patch(FancyArrowPatch((x, z0), (x, z1), arrowstyle="<->", mutation_scale=7, lw=0.8, color=color,
                                 shrinkA=0, shrinkB=0))
    ax.text(x + (0.15 if side == "right" else -0.15), 0.5 * (z0 + z1), text, ha="left" if side == "right" else "right",
            va="center", fontsize=fs, color=color)


def tri_grid(ax, x0, x1, z0, z1, cell, **kw):
    """schematic triangle mesh of a rectangle, cells of about `cell`"""
    nx, nz = max(1, round((x1 - x0) / cell)), max(1, round((z1 - z0) / cell))
    xs, zs_ = np.linspace(x0, x1, nx + 1), np.linspace(z0, z1, nz + 1)
    for i in range(nx):
        for k in range(nz):
            a, b, c, d = (xs[i], zs_[k]), (xs[i + 1], zs_[k]), (xs[i + 1], zs_[k + 1]), (xs[i], zs_[k + 1])
            for tri in ((a, b, c), (a, c, d)):
                p = np.array(tri + (tri[0],))
                ax.plot(p[:, 0], p[:, 1], **kw)


def save(fig, name):
    os.makedirs(PLOT_DIR, exist_ok=True)
    fig.savefig(os.path.join(PLOT_DIR, name), dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("written plots/" + name)


# =====================================================================================================
# A. the three conductor models on one TopMetal2 trace
# =====================================================================================================
def sketch_models():
    w, t = W_TRACE, T_TM2
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.6))
    mesh_kw = dict(color=C["mesh"], lw=0.5, alpha=0.7)
    titles = ("'surface' (default)", "'solve_inside'", "'solve_inside_skin'")
    for ax, title in zip(axs, titles):
        ax.add_patch(Rectangle((-2.2, -1.6), w + 4.4, t + 3.2, fc=C["ox"], ec="none"))
        ax.set_xlim(-2.2, w + 2.2)
        ax.set_ylim(-1.6, t + 1.6)
        ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(title, fontsize=11, family="monospace")
        ax.text(-2.0, t + 1.4, "oxide: meshed in all three models", fontsize=7.5, va="top", color="#555555")

    # surface: hollow, Zs on every face
    ax = axs[0]
    ax.add_patch(Rectangle((0, 0), w, t, fc="white", ec="none", hatch="////", lw=0))
    ax.add_patch(Rectangle((0, 0), w, t, fc="none", ec=C["zs"], lw=4))
    ax.text(w / 2, t / 2, "not meshed:\nno field inside", ha="center", va="center", fontsize=9,
            bbox=dict(fc="white", ec="none", pad=1.5))
    ax.text(w / 2, -0.35, "Zs on all four faces,\nside walls included", ha="center", va="top", fontsize=8.5, color=C["zs"])
    ax.text(w / 2, t + 0.3, f"Zs = (γ/σ)·coth(γh/2), h = {t:g} µm", ha="center", va="bottom", fontsize=8.5,
            color=C["zs"])

    # solve_inside: volume meshed with cells of about refined_cellsize
    ax = axs[1]
    ax.add_patch(Rectangle((0, 0), w, t, fc=C["metal"], ec="k", lw=0.8))
    tri_grid(ax, 0, w, 0, t, CELL, **mesh_kw)
    ax.text(w / 2, -0.35, f"meshed as a volume, cells of about\nrefined_cellsize = {CELL:g} µm "
            f"({round(t / CELL)} across {t:g} µm)", ha="center", va="top", fontsize=8.5)
    ax.text(w / 2, t + 0.3, f"conductivity σ = {SIG_TM2 / 1e7:.2f}e7 S/m inside", ha="center", va="bottom", fontsize=8.5)

    # solve_inside_skin: volume plus nested cores at the skin layer depths
    ax = axs[2]
    ax.add_patch(Rectangle((0, 0), w, t, fc=C["metal"], ec="k", lw=0.8))
    for d in DEPTHS:
        ax.add_patch(Rectangle((d, d), w - 2 * d, t - 2 * d, fc="none", ec=C["metal_dark"], lw=0.7))
    dmax = DEPTHS[-1]
    tri_grid(ax, dmax, w - dmax, dmax, t - dmax, CELL, **mesh_kw)
    # cells in the shells: thin, but as long as refined_cellsize along the surface
    for x in np.linspace(0, w, round(w / CELL) + 1):
        ax.plot([x, x], [0, dmax], **mesh_kw); ax.plot([x, x], [t - dmax, t], **mesh_kw)
    for z in np.linspace(0, t, round(t / CELL) + 1):
        ax.plot([0, dmax], [z, z], **mesh_kw); ax.plot([w - dmax, w], [z, z], **mesh_kw)
    delta = skin_depth(FMAX, SIG_TM2)
    ax.text(w / 2, -0.35, f"skin layers along all faces at {DEPTHS[0]:g} and {DEPTHS[1]:g} µm\n"
            f"(0.4δ and 1δ, δ = {delta:.3f} µm at fstop = {FMAX / 1e9:g} GHz)", ha="center", va="top", fontsize=8.5)
    ax.text(w / 2, t + 0.3, f"none if the metal is thinner than 4δ:\nTopMetal2 below {F_NO_SKIN / 1e9:.0f} GHz, "
            f"Metal1 below {F_NO_SKIN_M1 / 1e12:.1f} THz", ha="center", va="bottom", fontsize=8.5)
    # zoom on a corner
    ins = ax.inset_axes([1.02, 0.30, 0.42, 0.62])
    ins.add_patch(Rectangle((0, 0), w, t, fc=C["metal"], ec="k", lw=0.8))
    for d in DEPTHS:
        ins.add_patch(Rectangle((d, d), w - 2 * d, t - 2 * d, fc="none", ec=C["metal_dark"], lw=0.9))
    for z in (0, CELL):
        ins.plot([0, dmax], [z, z], **mesh_kw)
    ins.plot([dmax, dmax + 0.3], [CELL, CELL], **mesh_kw)
    ins.set_xlim(-0.1, 0.65); ins.set_ylim(-0.1, 0.65); ins.set_aspect("equal")
    ins.set_xticks([]); ins.set_yticks([])
    ins.set_title("corner, zoomed", fontsize=8)
    for d, zt in zip(DEPTHS, (0.33, 0.47)):
        ins.annotate(f"{d:g} µm", (d, zt), (0.36, zt), fontsize=7.5, va="center",
                     arrowprops=dict(arrowstyle="->", lw=0.6))
    ax.add_patch(Rectangle((-0.1, -0.1), 0.75, 0.75, fc="none", ec="#555555", lw=0.8))

    dim_v(axs[0], -0.6, 0, t, f"{t:g} µm", side="left")
    axs[0].text(w / 2, t - 0.25, f"{w:g} µm", ha="center", va="top", fontsize=8.5,
                bbox=dict(fc="white", ec="none", pad=1))
    fig.suptitle(f"The three conductor models on a {w:g} µm wide TopMetal2 trace (cross section to scale, "
                 "mesh schematic)", fontsize=12, y=0.93)
    save(fig, "sketch_conductor_models.png")


# =====================================================================================================
# B. the two loss errors of the surface model
# =====================================================================================================
def sketch_errors():
    fig = plt.figure(figsize=(15, 9.2))
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1.05], width_ratios=[1, 1, 1.05], hspace=0.45, wspace=0.25)

    # (a) narrow thick trace at low frequency
    w, t = W_NARROW, T_TM2
    r_real = 1 / (SIG_TM2 * w * t * 1e-12) / 1e3                 # Ohm/mm
    r_model = 1 / (SIG_TM2 * t * 1e-6 * (w + t) * 1e-6) / 1e3     # four faces with Zs = 2/(sigma t) in parallel
    for k, (title, model) in enumerate((("real conductor", False), ("surface model", True))):
        ax = fig.add_subplot(gs[0, k])
        ax.add_patch(Rectangle((-1.5, -1.9), w + 3, t + 2.9, fc=C["ox"], ec="none"))
        if not model:
            ax.add_patch(Rectangle((0, 0), w, t, fc=C["cur"], alpha=0.55, ec="k", lw=0.8))
            ax.text(w / 2, t / 2, "current fills\nw × t", ha="center", va="center", fontsize=9, color="white",
                    weight="bold")
            txt = f"R' = 1/(σ·w·t)\n= {r_real:.2f} Ω/mm"
        else:
            ax.add_patch(Rectangle((0, 0), w, t, fc="white", ec="none", hatch="////"))
            band = 0.13
            for (x, z, ww, hh) in ((0, 0, w, band), (0, t - band, w, band), (0, 0, band, t), (w - band, 0, band, t)):
                ax.add_patch(Rectangle((x, z), ww, hh, fc=C["cur"], ec="none"))
            ax.add_patch(Rectangle((0, 0), w, t, fc="none", ec=C["zs"], lw=1.2))
            ax.text(w / 2, t / 2, "each face:\nZs → 2/(σ·t)", ha="center", va="center", fontsize=8.5,
                    bbox=dict(fc="white", ec="none", pad=1.5))
            txt = (f"4 faces in parallel, total width\n2w + 2t: R' = 1/(σ·t·(w + t))\n"
                   f"= {r_model:.2f} Ω/mm = {r_model / r_real:.0%} of real")
        ax.text(w / 2, -0.25, txt, ha="center", va="top", fontsize=8.5)
        dim_h(ax, t + 0.25, 0, w, f"w = {w:g} µm")
        dim_v(ax, -0.4, 0, t, f"t = {t:g} µm", side="left")
        ax.set_xlim(-1.5, w + 1.5); ax.set_ylim(-1.9, t + 1.0); ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(title, fontsize=10)
    ax = fig.add_subplot(gs[0, 2]); ax.axis("off")
    ratios = "\n".join(f"   w = {ww:>4g} µm:  {ww / (ww + t):.0%}" for ww in (2.01, 4.5, 10, 20))
    ax.text(0, 0.95, "(a) Too little loss in a narrow, thick trace", fontsize=11, weight="bold", va="top")
    ax.text(0, 0.80, "At low frequency, the skin depth is larger than the\n"
            "thickness, and the current fills the whole cross section.\n"
            "The surface model gives every face the sheet impedance\n"
            "of the full thickness, the side walls too. The trace\n"
            "conducts as if it were w + t wide.\n\n"
            f"R' of the model / real R', TopMetal2 ({t:g} µm), DC:\n{ratios}\n\n"
            "Narrow traces suffer most. At high frequency, the\n"
            "missing current crowding at the corners keeps the\n"
            "model's loss too low (README section 4).", fontsize=9, va="top", family="sans-serif")

    # (b) thin ground plane with current on one face
    ax = fig.add_subplot(gs[1, 0:2])
    gap = Z0_TM2 - Z1_M1                    # TopMetal2 bottom above Metal1 top
    wl, xg = 10.0, 22.0
    ax.add_patch(Rectangle((-xg, -0.6), 2 * xg, gap + T_TM2 + 2.2, fc=C["ox"], ec="none"))
    # left half real, right half model: draw the same structure twice side by side
    for off, model in ((-xg / 2, False), (xg / 2, True)):
        x0, x1 = off - xg / 2 + 0.6, off + xg / 2 - 0.6
        ax.add_patch(Rectangle((x0, -T_M1), x1 - x0, T_M1, fc=C["gnd"], ec="k", lw=0.6))
        ax.add_patch(Rectangle((off - wl / 4, gap), wl / 2, T_TM2, fc=C["metal"], ec="k", lw=0.6))
        ax.text(off, gap + T_TM2 / 2, "TopMetal2", ha="center", va="center", fontsize=8)
        ax.text(x1 - 0.3, 0.35, "Metal1 ground plane", ha="right", va="bottom", fontsize=8)
        xs = np.linspace(x0, x1, 200)
        dens = 1 / (1 + ((xs - off) / (gap / 1.2)) ** 2)            # return current under the line, schematic
        if not model:
            for xa, da in zip(xs[:-1], dens[:-1]):
                ax.add_patch(Rectangle((xa, -T_M1), xs[1] - xs[0], T_M1, fc=C["cur"], alpha=0.9 * da, ec="none"))
            ax.text(off, -T_M1 - 0.5, "return current under the line, through the whole\n"
                    f"plane thickness h = {T_M1:.2f} µm: sheet resistance 1/(σ·h)", ha="center", va="top", fontsize=8.5)
        else:
            for xa, da in zip(xs[:-1], dens[:-1]):
                ax.add_patch(Rectangle((xa, -0.16), xs[1] - xs[0], 0.16, fc=C["cur"], alpha=0.9 * da, ec="none"))
            ax.plot([x0, x1], [0, 0], color=C["zs"], lw=2)
            ax.plot([x0, x1], [-T_M1, -T_M1], color=C["zs"], lw=2, ls=":")
            ax.text(off, -T_M1 - 0.5, "all current on the top face, Zs → 2/(σ·h):\ntwice the real sheet resistance. "
                    "The bottom face\n(dotted) has no field below it and carries nothing", ha="center", va="top",
                    fontsize=8.5)
        ax.text(off, gap + T_TM2 + 0.9, "real conductor" if not model else "surface model", ha="center",
                fontsize=10)
    ax.plot([0, 0], [-3.2, gap + T_TM2 + 1.6], color="#888888", lw=0.8, ls="--")
    dim_v(ax, -xg + 1.4, 0, gap, f"{gap:.2f} µm", side="right")
    ax.set_xlim(-xg, xg); ax.set_ylim(-3.4, gap + T_TM2 + 1.6); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("(b) Too much loss in a thin layer with current on one face (to scale)", loc="left", fontsize=11,
                 weight="bold", pad=8)

    # factor against frequency, from Palace's Zs with and without External
    ax = fig.add_subplot(gs[1, 2])
    f = np.logspace(8, np.log10(200e9), 200)
    for name, sigma, h, col in (("Metal1", SIG_M1, T_M1, C["gnd"]), ("MIM plate", SIG_MIM, T_MIM, C["metal_dark"])):
        ratio = np.real(zs(f, sigma, h)) / np.real(zs(f, sigma, h, external=True))
        ax.semilogx(f / 1e9, ratio, color=col, lw=2, label=f"{name}, {h:.2f} µm")
    ax.set_ylim(0.9, 2.1); ax.set_xlim(0.1, 200)
    ax.grid(True, which="both", color="#e4e3de", lw=0.6)
    ax.set_xlabel("frequency (GHz)")
    ax.set_ylabel("loss of the face: model / real")
    ax.set_title("loss factor of the surface model, current on one face:\nRe Zs / Re Zs with Palace's External",
                 fontsize=9.5, pad=8)
    ax.legend(fontsize=8.5, loc="lower left")
    fig.suptitle("The two loss errors of the surface model", fontsize=13, y=0.97)
    save(fig, "sketch_surface_model_errors.png")


if __name__ == "__main__":
    print(f"TopMetal2 {T_TM2:g} um, sigma {SIG_TM2:.3g}; skin layers at {FMAX / 1e9:g} GHz: {DEPTHS}; "
          f"no skin layers below {F_NO_SKIN / 1e9:.1f} GHz; Metal1 {T_M1:.2f} um, below {F_NO_SKIN_M1 / 1e12:.2f} THz")
    sketch_models()
    sketch_errors()
