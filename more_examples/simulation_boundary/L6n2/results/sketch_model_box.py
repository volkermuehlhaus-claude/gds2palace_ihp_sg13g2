#!/usr/bin/env python
"""Side view of the L6n2 simulation model, to scale: where the absorbing boundary sits.

Draws the model box as gds2palace builds it (util_simulation_setup.add_dielectrics):
every dielectric of the stackup, including the stackup's own AIR layer above the
passivation, is a box that extends `margin` beyond the layout; `air_around` of air
follows outside all of them; the absorbing boundary (ABC) is the outer face.

Two panels, same scale: margin 400 um with air_around 50 um (earlier L6n2 versions,
step 2 of this study) and with air_around 800 um (L6n2 v5). Layout extent from
read_gds() (all stackup and port layers, as in the models), z values from the stackup
reader, margin and air_around from the model scripts in the folder above.

    python sketch_model_box.py      (writes plots/model_box.png)
"""
import contextlib
import io
import os
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

from gds2palace import gds_reader, stackup_reader

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "..")
XML = os.path.join(MODEL_DIR, "SG13G2_200um_conformal.xml")
GDS = os.path.join(MODEL_DIR, "L6n2_with_ports.gds")
RUNS = ("L6n2_2um_passi3D_margin400_air50.py", "L6n2_2um_passi3D_margin400_air800.py")

FILL = {"Substrate": "#9fb3c4", "EPI": "#7f97ad", "SiO2": "#cfdbe6", "Passive": "#8fa9c2", "AIR": "#eef4fb"}
ABC = "#c0392b"
GUIDE = dict(color="#777777", lw=0.6, ls=":")


def setting(script, key):
    text = open(os.path.join(MODEL_DIR, script), encoding="utf-8").read()
    return float(re.search(rf"settings\['{key}'\]\s*=\s*([0-9.]+)", text).group(1))


with contextlib.redirect_stdout(io.StringIO()):
    materials, dielectrics, metals = stackup_reader.read_substrate(XML)
    layers = metals.getlayernumbers() + [201, 202]
    polys = gds_reader.read_gds(GDS, layers, purposelist=[0], metals_list=metals)
XMIN, XMAX, YMIN, YMAX = polys.get_bounding_box()
D = {d.name: (d.zmin, d.zmax) for d in dielectrics.dielectrics}
ZBOT = min(z0 for z0, _ in D.values())
ZPASS = D["Passive"][1]                         # top of the chip
ZTOP = max(z1 for _, z1 in D.values())          # top of the stackup's own AIR layer
TM2 = next(m for m in metals.metals if m.name == "TopMetal2")


def dim_v(ax, x, z0, z1, text, fs=8.5, color="k"):
    ax.add_patch(FancyArrowPatch((x, z0), (x, z1), arrowstyle="<->", mutation_scale=8, lw=0.9, color=color,
                                 shrinkA=0, shrinkB=0))
    ax.text(x + 25, 0.5 * (z0 + z1), text, ha="left", va="center", fontsize=fs, color=color)


def dim_h(ax, z, x0, x1, text, fs=8.5, color="k"):
    ax.add_patch(FancyArrowPatch((x0, z), (x1, z), arrowstyle="<->", mutation_scale=8, lw=0.9, color=color,
                                 shrinkA=0, shrinkB=0))
    ax.text(0.5 * (x0 + x1), z + 18, text, ha="center", va="bottom", fontsize=fs, color=color)


def panel(ax, margin, air, title, limits):
    x0, x1 = XMIN - margin, XMAX + margin
    lx = limits[0][0] + 40                       # left edge of the leader labels
    small = air < 150                            # thin air: dimensions outside the box
    # air box: outside all dielectrics
    ax.add_patch(Rectangle((x0 - air, ZBOT - air), (x1 - x0) + 2 * air, (ZTOP - ZBOT) + 2 * air, fc="white",
                           ec=ABC, lw=2.2, zorder=1))
    for name in ("Substrate", "EPI", "SiO2", "Passive", "AIR"):
        z0, z1 = D[name]
        ax.add_patch(Rectangle((x0, z0), x1 - x0, z1 - z0, fc=FILL[name], ec="#888888", lw=0.5, zorder=2))
    ax.add_patch(Rectangle((XMIN, TM2.zmin), XMAX - XMIN, TM2.zmax - TM2.zmin + 6, fc="#e8a13c", ec="k", lw=0.6,
                           zorder=3))
    arrow = dict(arrowstyle="->", lw=0.8, color="#333333")
    ax.annotate(f"stackup layer AIR, {D['AIR'][1] - D['AIR'][0]:g} µm (in the XML,\n"
                "extends by margin like the chip)",
                (x0 + 60, ZTOP - 40), (lx, ZTOP + 620), fontsize=8.5, va="center", arrowprops=arrow, zorder=5)
    ax.annotate(f"coil, {XMAX - XMIN:.0f} µm, on the {ZPASS - D['EPI'][0]:.0f} µm BEOL",
                (0.5 * (XMIN + XMAX), ZPASS), (lx, ZTOP + 420), fontsize=8.5, va="center", arrowprops=arrow,
                zorder=5)
    ax.annotate(f"silicon substrate, {D['Substrate'][1] - D['Substrate'][0]:g} µm",
                (x0 + 60, 0.5 * D["Substrate"][1]), (lx, ZBOT - 380), fontsize=8.5, va="center",
                arrowprops=arrow, zorder=5)
    # margin and air at the side
    zd = ZTOP + air + 90 if small else ZTOP + 150
    for xx in (x0 - air, x0, XMIN):
        ax.plot([xx, xx], [ZTOP + air if xx == x0 - air else ZTOP, zd + 15], **GUIDE)
    dim_h(ax, zd, x0, XMIN, f"margin {margin:g}")
    dim_h(ax, zd, x0 - air, x0, f"{air:g}", color=ABC)
    # distances to the boundary above the chip and below the substrate
    xd = x1 + air + 80 if small else XMAX + 0.4 * margin
    if small:
        for zz in (ZPASS, ZTOP + air, ZBOT, ZBOT - air):
            ax.plot([XMAX, xd + 15], [zz, zz], **GUIDE)
    dim_v(ax, xd, ZPASS, ZTOP + air, f"{ZTOP + air - ZPASS:g} µm from the chip\ntop to the boundary\n"
          f"= {ZTOP - ZPASS:g} (AIR layer) + {air:g}", color=ABC)
    dim_v(ax, xd, ZBOT - air, ZBOT, f"{air:g} µm below\nthe substrate", color=ABC)
    if small:
        ax.text(x1 + air, ZBOT - air - 15, "ABC", ha="right", va="top", color=ABC, fontsize=9, weight="bold")
    else:
        ax.text(x1 + air - 15, ZBOT - air + 15, "ABC", ha="right", va="bottom", color=ABC, fontsize=9,
                weight="bold")
    ax.set_title(title, fontsize=10)
    ax.set_xlim(*limits[0])
    ax.set_ylim(*limits[1])
    ax.set_aspect("equal")
    ax.set_xlabel("x (µm)")
    ax.set_ylabel("z (µm)")


m_a, a_a = setting(RUNS[0], "margin"), setting(RUNS[0], "air_around")
m_b, a_b = setting(RUNS[1], "margin"), setting(RUNS[1], "air_around")
pad = 60
lim = ((XMIN - m_b - a_b - pad, XMAX + m_b + a_b + 380), (ZBOT - a_b - pad, ZTOP + a_b + pad))

fig, axs = plt.subplots(1, 2, figsize=(17, 7.6))
panel(axs[0], m_a, a_a, f"margin {m_a:g} µm, air_around {a_a:g} µm (earlier versions of the L6n2 study)", lim)
panel(axs[1], m_b, a_b, f"margin {m_b:g} µm, air_around {a_b:g} µm (L6n2 v5)", lim)
fig.suptitle("L6n2 model, side view to scale: the stackup's dielectrics extend by margin, "
             "air_around follows outside all of them, then the absorbing boundary (ABC)", fontsize=11, y=0.93)
os.makedirs(os.path.join(HERE, "plots"), exist_ok=True)
fig.savefig(os.path.join(HERE, "plots", "model_box.png"), dpi=110, bbox_inches="tight")
print(f"layout x {XMIN:g}..{XMAX:g}, y {YMIN:g}..{YMAX:g}; z bottom {ZBOT:g}, chip top {ZPASS:g}, "
      f"AIR layer top {ZTOP:g}")
print("written plots/model_box.png")
