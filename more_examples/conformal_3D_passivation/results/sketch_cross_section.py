#!/usr/bin/env python
"""Cross-section sketches of the coupled TopMetal2 lines for README.md, to scale.

A vertical cut through the middle of the balun's upper coupled section (x = center of the layout),
once with the planar stackup of the mesh study (SG13G2_nosub.xml) and once with the conformal
stackup of this study (SG13G2_200um_3D_passivation.xml). The z values come from gds2palace's
stackup reader, the line edges from the GDS file, the side walls and the cover from the
DerivedLayer oversize in the conformal XML. Writes to results/plots/:

  cross_section_planar.png
  cross_section_conformal.png

    python sketch_cross_section.py
"""
import contextlib
import io
import os
import xml.etree.ElementTree as ET

import gdstk
import matplotlib
from shapely.geometry import LineString, Polygon

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

from gds2palace import stackup_reader

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.join(HERE, "..")
GDS = os.path.join(STUDY, "Balun_140-170G_RupokDas_with_ports.gds")
XML_CONFORMAL = os.path.join(STUDY, "SG13G2_200um_3D_passivation.xml")
XML_PLANAR = os.path.join(STUDY, "..", "mesh_convergence", "mesh_convergence_D-band_balun", "SG13G2_nosub.xml")
PLOT_DIR = os.path.join(HERE, "plots")

TM2_LAYER = 134
FILL = {"SiO2": "#cfdbe6", "Passive": "#8fa9c2", "AIR": "#ffffff", "TopMetal2": "#e8a13c", "Metal3": "#c0504d"}
EPS = {"SiO2": 4.1, "Passive": 6.6, "AIR": 1.0}


# ---------------- data from the files ----------------
def read_stackup(path):
    with contextlib.redirect_stdout(io.StringIO()):
        materials, dielectrics, metals = stackup_reader.read_substrate(path)
    bands = {d.name: (d.material, d.zmin, d.zmax) for d in dielectrics.dielectrics}
    layers = {m.name: (m.material, m.zmin, m.zmax) for m in metals.metals}
    eps = {m.name: float(m.eps) for m in materials.materials if getattr(m, "eps", None) is not None}
    return bands, layers, eps


lib = gdstk.read_gds(GDS)
top = max(lib.top_level(), key=lambda c: (c.bounding_box()[1][0] - c.bounding_box()[0][0]))
(X0, Y0), (X1, Y1) = top.bounding_box()
XC = 0.5 * (X0 + X1)
CUT = LineString([(XC, Y0 - 1), (XC, Y1 + 1)])
TM2 = [Polygon(p.points) for p in top.get_polygons() if p.layer == TM2_LAYER]


def intervals(geoms):
    """y intervals where the cut line crosses the given shapes (upper coupled section only)"""
    out = []
    for g in geoms:
        s = g.intersection(CUT)
        for part in getattr(s, "geoms", [s]):
            if not part.is_empty and part.bounds[1] > 0:
                out.append((part.bounds[1], part.bounds[3]))
    return sorted(out)


LINES = intervals(TM2)                                       # the two coupled lines
OVERSIZE = float(next(e.get("Oversize") for e in ET.parse(XML_CONFORMAL).getroot().iter("DerivedLayer")
                      if e.get("Operation") == "SIZE"))
COVER = intervals([g.buffer(OVERSIZE, join_style="mitre") for g in TM2])   # layer 900, TM2 sized
WIDTHS = [b - a for a, b in LINES]
GAP = LINES[1][0] - LINES[0][1]
YLO, YHI = LINES[0][0] - 8, LINES[-1][1] + 8


# ---------------- drawing ----------------
def dim_v(ax, y, z0, z1, text, side="right", fs=8.5, color="k"):
    ax.add_patch(FancyArrowPatch((y, z0), (y, z1), arrowstyle="<->", mutation_scale=7, lw=0.8, color=color,
                                 shrinkA=0, shrinkB=0))
    ax.text(y + (0.35 if side == "right" else -0.35), 0.5 * (z0 + z1), text, ha="left" if side == "right" else "right",
            va="center", fontsize=fs, color=color)


def dim_h(ax, z, y0, y1, text, above=True, fs=8.5, color="k"):
    ax.add_patch(FancyArrowPatch((y0, z), (y1, z), arrowstyle="<->", mutation_scale=7, lw=0.8, color=color,
                                 shrinkA=0, shrinkB=0))
    ax.text(0.5 * (y0 + y1), z + (0.25 if above else -0.25), text, ha="center", va="bottom" if above else "top",
            fontsize=fs, color=color)


def rect(ax, y0, y1, z0, z1, material, lw=0.6, ec="k", **kw):
    ax.add_patch(Rectangle((y0, z0), y1 - y0, z1 - z0, fc=FILL.get(material, "#dddddd"), ec=ec, lw=lw, **kw))


def sketch(conformal):
    bands, layers, _ = read_stackup(XML_CONFORMAL if conformal else XML_PLANAR)
    zref = layers["Metal3"][2]                       # z = 0 at the top of the Metal3 ground plane
    z = {k: (v[0], v[1] - zref, v[2] - zref) for k, v in {**bands, **layers}.items()}
    tm_lo, tm_hi = z["TopMetal2"][1:]
    zmin, zmax = z["Metal3"][1] - 0.6, tm_hi + 4.2

    fig, ax = plt.subplots(figsize=(11, 5.6))
    # background dielectric bands, cut to the window
    for name in ("SiO2", "Passive", "AIR"):
        mat, a, b = z[name]
        a, b = max(a, zmin), min(b, zmax)
        if b > a:
            rect(ax, YLO, YHI, a, b, mat, lw=0.4, ec="#777777")
    # conformal: SiO2 cover (layer 900 = TM2 sized) and side walls (901 = 900 NOT TM2)
    if conformal:
        mat, a, b = z["SiO2_above"]
        for c0, c1 in COVER:
            rect(ax, c0, c1, a, b, mat, ec="#555555", lw=0.6)
        mat, a, b = z["SiO2_sides"]
        for (c0, c1), (l0, l1) in zip(COVER, LINES):
            rect(ax, c0, l0, a, b, mat, ec="#555555", lw=0.6)
            rect(ax, l1, c1, a, b, mat, ec="#555555", lw=0.6)
    # metals
    _, a, b = z["Metal3"]
    rect(ax, YLO, YHI, a, b, "Metal3", lw=0.6)
    for l0, l1 in LINES:
        rect(ax, l0, l1, tm_lo, tm_hi, "TopMetal2", lw=0.8)

    # labels of the regions
    ym = 0.5 * (LINES[0][1] + LINES[1][0])
    y_right = LINES[1][1] + 1.6
    ax.text(YLO + 0.5, 0.5 * (z["Metal3"][1] + z["Metal3"][2]), "Metal3 ground plane", va="center", fontsize=8.5,
            color="white", weight="bold")
    for (l0, l1) in LINES:
        ax.text(0.5 * (l0 + l1), 0.5 * (tm_lo + tm_hi), "TopMetal2", ha="center", va="center", fontsize=9, weight="bold")
    ax.text(YLO + 0.5, 0.3 * tm_lo, f"SiO2 (εr = {EPS['SiO2']:g})", va="center", fontsize=8.5)
    _, p0, p1 = z["Passive"]
    _, s0, s1 = z["SiO2"]
    _, a0, a1 = z["AIR"]

    if not conformal:
        ax.text(YLO + 0.5, 0.5 * (p0 + p1), f"Passive (εr = {EPS['Passive']:g})", va="center", fontsize=8)
        ax.text(YLO + 0.5, 0.5 * (a0 + zmax), "air", va="center", fontsize=8.5)
        dim_v(ax, y_right + 3.6, tm_hi, s1, f"{s1 - tm_hi:.1f} µm SiO2")
        dim_v(ax, y_right + 3.6, p0, p1, f"{p1 - p0:.1f} µm Passive", fs=8)
        ax.annotate("gap filled with SiO2", (ym, tm_hi - 0.4), (ym - 4, tm_hi + 2.6), fontsize=8.5, ha="right",
                    arrowprops=dict(arrowstyle="->", lw=0.8))
        title = ("Planar stackup (SG13G2_nosub.xml, mesh study): flat SiO2 and passivation cover the lines,\n"
                 "the gap between the lines is filled with SiO2")
        name = "cross_section_planar.png"
    else:
        ax.text(YLO + 0.5, 0.5 * (p0 + p1), f"Passive (εr = {EPS['Passive']:g})", va="center", fontsize=8)
        ax.text(YLO + 0.5, zmax - 0.6, "air", va="center", fontsize=8.5)
        _, c0, c1 = z["SiO2_above"]
        dim_v(ax, y_right + 3.6, c0, c1, f"{c1 - c0:.1f} µm SiO2 cover\n(SiO2 + passivation, as SiO2)", fs=8)
        dim_v(ax, y_right + 3.6, tm_lo, s1, f"{s1 - tm_lo:.1f} µm SiO2", fs=8)
        dim_v(ax, y_right + 3.6, p0, p1, f"{p1 - p0:.1f} µm Passive", fs=8)
        slot = COVER[1][0] - COVER[0][1]
        ax.annotate(f"air slot {slot:.1f} µm", (ym, tm_hi + 0.6), (ym - 4, tm_hi + 3.2), fontsize=8.5, ha="right",
                    arrowprops=dict(arrowstyle="->", lw=0.8))
        ax.annotate(f"SiO2 side walls and cover\noverhang: {OVERSIZE:g} µm", (LINES[0][0] - OVERSIZE / 2, tm_hi - 0.5),
                    (YLO + 0.5, tm_hi + 1.2), fontsize=8.5, ha="left", va="center",
                    arrowprops=dict(arrowstyle="->", lw=0.8))
        title = ("Conformal stackup (SG13G2_200um_3D_passivation.xml, this study): SiO2 and passivation end\n"
                 f"{p1 - tm_lo:.1f} µm above the bottom of the lines; side walls and a cover follow each line")
        name = "cross_section_conformal.png"

    # common dimensions
    dim_h(ax, tm_lo - 0.45, *LINES[0], f"{WIDTHS[0]:g} µm", above=False)
    dim_h(ax, tm_lo - 0.45, *LINES[1], f"{WIDTHS[1]:g} µm", above=False)
    dim_h(ax, tm_lo - 1.5, LINES[0][1], LINES[1][0], f"gap {GAP:g} µm", above=False)
    dim_v(ax, LINES[0][0] - 1.0, 0, tm_lo, f"{tm_lo:.2f} µm", side="right")
    dim_v(ax, y_right, tm_lo, tm_hi, f"{tm_hi - tm_lo:g} µm")

    ax.set_xlim(YLO, YHI + 9)
    ax.set_ylim(zmin, zmax)
    ax.set_aspect("equal")
    ax.set_xlabel(f"y (µm), cut at x = {XC:g} µm through the upper coupled section")
    ax.set_ylabel("z above Metal3 (µm)")
    ax.set_title(title, fontsize=10)
    os.makedirs(PLOT_DIR, exist_ok=True)
    fig.savefig(os.path.join(PLOT_DIR, name), dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("written plots/" + name)


if __name__ == "__main__":
    print(f"lines {LINES}, widths {WIDTHS}, gap {GAP:g} um, oversize {OVERSIZE:g} um, cover {COVER}")
    sketch(conformal=False)
    sketch(conformal=True)
