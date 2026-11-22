#!/usr/bin/env python
"""Sketches for README.md, drawn from the XML files in this folder (no z value typed by hand).

  png/sketch_A_positioning.png  file 01 (absolute z + <Substrate Offset>) next to file 02
                                (Reference/ReferenceEdge): the same stack, two ways to position it
  png/sketch_B_thickness.png    file 04: what total_thickness, bulk_thickness and air_thickness
                                set, at the default and with total_thickness overridden to 500

z values come from gds2palace's stackup reader, the file-local values (Zmin/Zmax, Offset,
Reference, ReferenceEdge) from the XML attributes.

    python sketches.py
"""
import contextlib
import io
import os
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

from gds2palace import stackup_reader

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "png")
F01 = os.path.join(HERE, "01_legacy_absolute_positioning_schemaVersion2.0.xml")
F02 = os.path.join(HERE, "02_reference_relative_positioning_schemaVersion3.0.xml")
F04 = os.path.join(HERE, "04_full_featureset_schemaVersion3.1.xml")
OVERRIDE = 500.0          # the total_thickness override quoted in README.md


# ---------------- data from the files ----------------
def resolved(path, overrides=None):
    """absolute z of every dielectric and layer, as gds2palace resolves them"""
    with contextlib.redirect_stdout(io.StringIO()):
        _, d, m = stackup_reader.read_substrate(path, variable_overrides=overrides or {})
    diel = {x.name: (x.zmin, x.zmax) for x in d.dielectrics}
    lay = {x.name: (x.type, x.zmin, x.zmax) for x in m.metals}
    return diel, lay


def raw(path):
    """attributes as written in the file: Dielectric/Layer elements, Substrate Offset, Variables, colors"""
    root = ET.parse(path).getroot()
    diel = [e.attrib for e in root.iter("Dielectric")]
    lay = {e.get("Name"): e.attrib for e in root.iter("Layer")}
    off = next((float(e.get("Offset")) for e in root.iter("Substrate") if e.get("Offset")), None)
    var = {e.get("Name"): e.get("Value") for e in root.iter("Variable")}
    color = {e.get("Name"): "#" + e.get("Color") for e in root.iter("Material") if e.get("Color")}
    return diel, lay, off, var, color


D01, L01 = resolved(F01)
D02, L02 = resolved(F02)
RD01, RL01, OFFSET, _, COLOR = raw(F01)
RD02, RL02, _, _, _ = raw(F02)
RD04, RL04, _, VAR04, _ = raw(F04)
assert D01.keys() == D02.keys() and L01.keys() == L02.keys() and all(
    abs(a - b) < 1e-9 for k in D01 for a, b in zip(D01[k], D02[k])) and all(
    abs(a - b) < 1e-9 for k in L01 for a, b in zip(L01[k][1:], L02[k][1:])), "files 01 and 02 should resolve alike"
MAT = {e["Name"]: e["Material"] for e in RD01}
MAT.update({k: v["Material"] for k, v in RL01.items()})

# x columns of the stack sketches
COLS = {"diel": (0.0, 3.0), "CONDUCTOR": (3.6, 5.6), "VIA": (6.4, 7.6), "mim": (8.4, 9.6), "lbe": (6.4, 7.6)}
MIMS = ("MIM", "Vmim")


def column(name, typ):
    if name in MIMS:
        return COLS["mim"]
    if name == "LBE":
        return COLS["lbe"]
    return COLS.get(typ, COLS["CONDUCTOR"])


def fill(name):
    return COLOR.get(MAT.get(name, name), "#dddddd")


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, name), dpi=110, bbox_inches="tight")
    plt.close(fig)
    print("written png/" + name)


def dim_v(ax, x, z0, z1, text, side="right", fs=8.5, color="k", at=None):
    ax.add_patch(FancyArrowPatch((x, z0), (x, z1), arrowstyle="<->", mutation_scale=8, lw=0.9, color=color,
                                 shrinkA=0, shrinkB=0))
    dx = 0.012 * (ax.get_xlim()[1] - ax.get_xlim()[0])
    ax.text(x + (dx if side == "right" else -dx), 0.5 * (z0 + z1) if at is None else at, text,
            ha="left" if side == "right" else "right", va="center", fontsize=fs, color=color)


# =====================================================================================================
# A. absolute (file 01) vs. reference-relative (file 02) positioning, broken z axis
# =====================================================================================================
TOP = (D01["EPI"][0] - 0.6, D01["Passive"][1] + 1.2)          # BEOL window
BOT = (L01["BACKSIDEGND"][1] - 1.0, 2.2)                       # bottom of the substrate
fig = plt.figure(figsize=(17, 13))
gs = fig.add_gridspec(2, 2, height_ratios=[TOP[1] - TOP[0], BOT[1] - BOT[0]], hspace=0.06, wspace=0.42)
axes = {(c, r): fig.add_subplot(gs[r, c]) for c in (0, 1) for r in (0, 1)}


def draw_stack(ax_top, ax_bot, labels, arrows=None):
    """dielectric column plus layer columns, in both z windows; labels: name -> text"""
    for ax, (z_lo, z_hi) in ((ax_top, TOP), (ax_bot, BOT)):
        for name, (z0, z1) in D01.items():
            a, b = max(z0, z_lo), min(z1, z_hi)
            if b > a:
                x0, x1 = COLS["diel"]
                ax.add_patch(Rectangle((x0, a), x1 - x0, b - a, fc=fill(name), ec="#666666", lw=0.6, alpha=0.55))
        for name, (typ, z0, z1) in L01.items():
            a, b = max(z0, z_lo), min(z1, z_hi)
            if b > a:
                x0, x1 = column(name, typ)
                hatch = "//" if typ == "DIELECTRIC" else None
                ax.add_patch(Rectangle((x0, a), x1 - x0, b - a, fc=fill(name), ec="k", lw=0.6,
                                       alpha=0.35 if hatch else 0.9, hatch=hatch))
        ax.set_xlim(-0.2, 17.5)
        ax.set_ylim(z_lo, z_hi)
        ax.set_xticks([])
    # labels: dielectrics left inside the column, layers on the right (spread so they don't overlap)
    spread = []
    for name, text in labels.items():
        if name in D01:
            z0, z1 = D01[name]
            zt = 0.5 * (max(z0, TOP[0]) + min(z1, TOP[1]))
            ax = ax_top
            if name == "Substrate":
                ax, zt = ax_bot, 0.55 * BOT[1]
            ax.text(COLS["diel"][0] + 0.1, zt, text, fontsize=8, va="center")
        else:
            typ, z0, z1 = L01[name]
            ax = ax_top if z1 > TOP[0] + 0.5 and name != "LBE" else ax_bot
            zt = 0.5 * (max(z0, (TOP if ax is ax_top else BOT)[0]) + min(z1, (TOP if ax is ax_top else BOT)[1]))
            if name == "LBE":
                zt = 1.1
            spread.append([zt, ax, text, (column(name, typ)[1], zt)])
    for ax in (ax_top, ax_bot):
        items = sorted((it for it in spread if it[1] is ax), key=lambda it: it[0])
        gap = 0.36 if ax is ax_top else 0.5
        for _ in range(50):                      # push neighbours apart, symmetric
            for a, b in zip(items, items[1:]):
                d = b[0] - a[0]
                if d < gap:
                    a[0] -= 0.5 * (gap - d)
                    b[0] += 0.5 * (gap - d)
        for zt, _, text, anchor in items:
            ax.annotate(text, anchor, (10.0, zt), fontsize=7.5, va="center",
                        arrowprops=dict(arrowstyle="-", lw=0.4, color="#888888"))
    # reference arrows (file 02): from the layer's bottom to the edge it references
    for name, (ref, edge) in (arrows or {}).items():
        typ, z0, _ = L01[name]
        if ref in D01:
            zr = D01[ref][0] if edge == "Bottom" else D01[ref][1]
            xr = COLS["diel"][1]
        else:
            rtyp, r0, r1 = L01[ref]
            zr = r0 if edge == "Bottom" else r1
            xr = 0.5 * sum(column(ref, rtyp))
        ax = ax_top if zr > TOP[0] else ax_bot
        x0 = column(name, typ)[0] + 0.25
        ax.add_patch(FancyArrowPatch((x0, z0 + 0.12), (xr, zr), arrowstyle="-|>", mutation_scale=7, lw=0.9,
                                     color="#1f4fd8", connectionstyle="arc3,rad=0.25", shrinkA=0, shrinkB=0))
    # break marks
    for ax, where in ((ax_top, 0), (ax_bot, 1)):
        ax.spines["bottom" if where == 0 else "top"].set_visible(False)
        y = 0 if where == 0 else 1
        ax.plot([-0.012, 0.012], [y - 0.008, y + 0.008], transform=ax.transAxes, color="k", lw=1, clip_on=False)


# ---- file 01 ----
ax_t, ax_b = axes[(0, 0)], axes[(0, 1)]
order = [e["Name"] for e in RD01]
lab01 = {e["Name"]: f"{e['Name']}  Thickness {float(e['Thickness']):g}  (#{order.index(e['Name']) + 1} in file)"
         for e in RD01}
lab01["Substrate"] = lab01["Substrate"].replace("in file)", "in file: last = bottom)")
for name, a in RL01.items():
    lab01[name] = f"{name}  Zmin {float(a['Zmin']):g}, Zmax {float(a['Zmax']):g}"
draw_stack(ax_t, ax_b, lab01)
for ax in (ax_t, ax_b):
    ax.axhline(OFFSET if ax is ax_t else 0.0, color="#c0392b", lw=1.2, ls="--", xmin=0, xmax=0.56)
ax_t.text(10.0, OFFSET - 0.35,f"Layers' z = 0 here: <Substrate Offset=\"{OFFSET:g}\"/>\n"
          f"= Substrate {D01['Substrate'][1] - D01['Substrate'][0]:g} + EPI {D01['EPI'][1] - D01['EPI'][0]:g}",
          color="#c0392b", fontsize=8.5, va="top")
ax_b.text(0.1, 0.25, "z = 0: bottom of the Substrate (dielectrics start here)", color="#c0392b", fontsize=8.5,
          va="bottom")
# second axis: z as written in the file's <Layers>
for ax in (ax_t, ax_b):
    sec = ax.secondary_yaxis("right", functions=(lambda z: z - OFFSET, lambda z: z + OFFSET))
    sec.set_ylabel("Zmin/Zmax as written in <Layers>", fontsize=8.5, color="#c0392b")
    sec.tick_params(colors="#c0392b", labelsize=8)
ax_t.set_title("File 01 (schema 2.0): Dielectrics stack in file order from the top;\n"
               "Layers have absolute z, all shifted by one <Substrate Offset>", fontsize=10.5)
ax_t.set_ylabel("z (µm), resolved")
ax_b.set_ylabel("z (µm)")

# ---- file 02 ----
ax_t, ax_b = axes[(1, 0)], axes[(1, 1)]
lab02, arr02 = {}, {}
for e in RD02:
    lab02[e["Name"]] = (f"{e['Name']}  on {e['Reference']} {e['ReferenceEdge']}" if e.get("Reference")
                        else f"{e['Name']}  no Reference: z = 0 at its bottom")
for name, a in RL02.items():
    lab02[name] = f"{name}  → {a['Reference']} {a['ReferenceEdge']}"
    if float(a["Zmin"]) != 0:
        lab02[name] += f", Zmin {float(a['Zmin']):g}"
    arr02[name] = (a["Reference"], a["ReferenceEdge"])
draw_stack(ax_t, ax_b, lab02, arr02)
ax_t.set_title("File 02 (schema 3.0): every Dielectric and Layer names the edge it sits on\n"
               "(blue arrows); no <Substrate Offset>, same resolved z as file 01", fontsize=10.5)
for ax in (ax_t, ax_b):
    ax.tick_params(labelsize=8)
fig.suptitle("A  Two ways to write the same SG13G2 stack. Each half is to scale in z; the middle of the "
             f"{D01['Substrate'][1]:g} µm substrate is cut out.", fontsize=12, y=0.93)
save(fig, "sketch_A_positioning.png")

# =====================================================================================================
# B. file 04: substrate height as a variable, default and total_thickness override
# =====================================================================================================
cases = [(None, float(VAR04["total_thickness"])), ({"total_thickness": OVERRIDE}, OVERRIDE)]
zmax_all = max(resolved(F04, ov)[0]["AIR"][1] for ov, _ in cases)
fig, axs = plt.subplots(1, 2, figsize=(15, 10), sharey=True)
for ax, (ov, total) in zip(axs, cases):
    D, L = resolved(F04, ov)
    bulk = D["Substrate"][1] - D["Substrate"][0]
    beol = D["Passive"][1] - D["EPI"][0]
    air = D["AIR"][1] - D["AIR"][0]
    parts = " + ".join(f"{n} {D[n][1] - D[n][0]:g}" for n in ("EPI", "SiO2", "Passive"))
    for name, (z0, z1) in D.items():
        ax.add_patch(Rectangle((0, z0), 5, z1 - z0, fc=fill(name), ec="#666666", lw=0.6, alpha=0.55))
    for name in ("LBE", "BACKSIDEGND", "SUBGND"):
        typ, z0, z1 = L[name]
        x0 = 5.4 if name == "LBE" else 0
        w = 0.7 if name == "LBE" else 5
        ax.add_patch(Rectangle((x0, z0), w, z1 - z0, fc=fill(name), ec="k", lw=0.6,
                               alpha=0.35 if name == "LBE" else 0.9, hatch="//" if name == "LBE" else None))
    ax.text(2.5, 0.5 * bulk, f"Substrate\nThickness = bulk_thickness\n= total_thickness − 20 = {bulk:g}",
            ha="center", va="center", fontsize=9)
    ax.text(2.5, D["AIR"][0] + 0.5 * air, "AIR\nThickness = air_thickness", ha="center", va="center", fontsize=9)
    dim_v(ax, 7.0, 0, bulk, f"bulk_thickness {bulk:g}", at=0.6 * bulk)
    dim_v(ax, 7.0, D["EPI"][0], D["Passive"][1], "")
    ax.annotate(f"EPI + SiO2 + Passive = {beol:.4f}\n({parts})", (7.0, 0.5 * (D["EPI"][0] + D["Passive"][1])),
                (7.6, D["EPI"][0] - 45), fontsize=8, va="center", arrowprops=dict(arrowstyle="->", lw=0.8))
    dim_v(ax, 7.0, D["AIR"][0], D["AIR"][1], f"air_thickness {air:g}")
    dim_v(ax, 15.5, 0, total, f"total_thickness\n{total:g}", at=0.45 * total)
    ax.plot([0, 15.5], [total, total], color="#c0392b", lw=0.8, ls=":")
    ax.text(15.8, total - 12, f"chip top at {D['Passive'][1]:.4f}:\n{total - D['Passive'][1]:.4f} µm below\n"
            "total_thickness", fontsize=8, color="#c0392b", va="top")
    lbe = L["LBE"]
    ax.annotate(f"LBE (layer 157): Zmax = bulk_thickness + 3.75\n= {lbe[2] - lbe[1]:g}, Substrate + EPI",
                (6.1, 0.2 * bulk), (7.6, 0.2 * bulk), fontsize=8, va="center",
                arrowprops=dict(arrowstyle="->", lw=0.8))
    bs = L["BACKSIDEGND"]
    ax.annotate(f"BACKSIDEGND {bs[1]:g} … {bs[2]:g}", (2.5, bs[1]), (7.6, -45), fontsize=8, va="center",
                arrowprops=dict(arrowstyle="->", lw=0.8))
    ax.set_xlim(-0.3, 21)
    ax.set_xticks([])
    ax.set_title("file default: total_thickness = " + VAR04["total_thickness"].strip() if ov is None
                 else f"variable_overrides={{'total_thickness': {OVERRIDE:g}}}", fontsize=10.5)
ax.set_ylim(-70, zmax_all + 15)
axs[0].set_ylabel("z (µm), resolved")
fig.suptitle("B  File 04: one variable sets the chip height. The substrate takes total_thickness − 20; "
             "everything above it moves with it (to scale)", fontsize=12)
save(fig, "sketch_B_thickness.png")
