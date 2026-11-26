#!/usr/bin/env python
"""Figures for "Priority: overlapping volumes" (doc/XML_stackup_format/XML_stackup_format.md and the user's guide),
drawn from the geometry gds2palace actually builds, not from the rules.

For each use case, a small stackup and layout go through gds2palace's Elmer thermal setup (all conductors are
volumes there) up to the point where meshing would start. Every volume is then cut with the plane y = 0, and the
cross-section is drawn. The left panel shows the stackup boxes and drawn layers as written, overlapping; the other
panels show the model, one per Priority setting. Output in doc/userguide_md_format/images/:

  priority_a_mold.png        a die in mold compound: example file 05 in more_examples/XML_stackup_format_examples/
                             and its layout layout/05_die_in_mold.gds
  priority_b_pillars.png     copper pillars in underfill: metals win over dielectrics, nothing to set
  priority_c_cavity.png      an air cavity in the substrate: a drawn dielectric layer wins, nothing to set
                                 (and what Priority="-1" on the cavity would do)
  priority_d_fillet.png      an underfill fillet drawn larger than the die: Priority="-1" on the drawn layer
  priority_e_via.png         a via drawn into its landing pad: Priority="1" on the via

    python priority_sketches.py
"""
import contextlib
import io
import math
import os
import tempfile
import xml.etree.ElementTree as ET

import gdstk
import gmsh
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.patches import Patch, Rectangle

from gds2palace import gds_reader, simulation_setup, stackup_reader

HERE = os.path.dirname(os.path.abspath(__file__))
# in the user's guide folder: its PDF build only takes images from there
OUT = os.path.join(HERE, "..", "userguide_md_format", "images")
EXAMPLES = os.path.join(HERE, "..", "..", "more_examples", "XML_stackup_format_examples")
FILE05 = os.path.join(EXAMPLES, "05_priority_and_directional_k_schemaVersion3.2.xml")
GDS05 = os.path.join(EXAMPLES, "layout", "05_die_in_mold.gds")


# ---------------- use cases: stackup (with {placeholders} for the Priority settings) and layout ----------------
def stackup(dielectrics, layers, materials):
    """A minimal thermal stackup; every material gets a thermal conductivity (the values don't matter here)."""
    mats = "\n".join(f'<Material Name="{n}" Type="{t}" ThermalConductivity="1" Color="{c}" />' for n, t, c in materials)
    return (f'<Stackup schemaVersion="3.2"><Materials>{mats}</Materials><ELayers LengthUnit="um">'
            f'<Dielectrics>{dielectrics}</Dielectrics><Layers>{layers}'
            '<Layer Name="BOTTOM" Type="sheet" Material="PEC" Layer="99" Zmin="0" Zmax="0" /></Layers>'
            '</ELayers></Stackup>')


CASES = {
    "b_pillars": dict(
        title="b  Copper pillars in underfill: metals always win over dielectrics, no Priority needed",
        xml=stackup('<Dielectric Name="Die" Material="Silicon" Zmin="130" Zmax="230" Boundary="302" />'
                    '<Dielectric Name="Underfill" Material="Underfill" Zmin="100" Zmax="130" />'
                    '<Dielectric Name="Interposer" Material="Silicon" Zmin="0" Zmax="100" />',
                    '<Layer Name="Pillar" Type="conductor" Material="Copper" Layer="20" Zmin="100" Zmax="130" />',
                    [("Silicon", "Semiconductor", "01e0ff"), ("Underfill", "Dielectric", "d8c890"),
                     ("Copper", "Conductor", "e07b39")]),
        shapes=[(302, -200, -200, 200, 200)] + [(20, x - 20, -20, x + 20, 20) for x in (-150, -50, 50, 150)],
        variants=[("in the model", {})]),
    "c_cavity": dict(
        title="c  An air cavity in the substrate: a drawn dielectric layer wins over a <Dielectric> at equal Priority",
        xml=stackup('<Dielectric Name="Oxide" Material="SiO2" Zmin="200" Zmax="215" />'
                    '<Dielectric Name="Substrate" Material="Silicon" Zmin="0" Zmax="200" />',
                    '<Layer Name="Cavity" Type="dielectric" Material="AIR" Layer="157" Zmin="0" Zmax="120" {cavity} />',
                    [("Silicon", "Semiconductor", "01e0ff"), ("SiO2", "Dielectric", "fffcad"),
                     ("AIR", "Dielectric", "e8e8e8")]),
        shapes=[(157, -100, -100, 100, 100)],
        extent=(-300, 300),
        variants=[("equal Priority: the cavity replaces the substrate", {}),
                  ('Cavity Priority="-1": the substrate keeps it, no cavity', {"cavity": 'Priority="-1"'})]),
    "d_fillet": dict(
        title="d  An underfill fillet drawn larger than the die: Priority=\"-1\" keeps the die complete",
        xml=stackup('<Dielectric Name="Die" Material="Silicon" Zmin="140" Zmax="340" Boundary="302" />'
                    '<Dielectric Name="Interposer" Material="Silicon" Zmin="0" Zmax="100" />',
                    '<Layer Name="Underfill" Type="dielectric" Material="Underfill" Layer="160" Zmin="100" Zmax="200" '
                    '{underfill} />',
                    [("Silicon", "Semiconductor", "01e0ff"), ("Underfill", "Dielectric", "d8c890")]),
        shapes=[(302, -200, -200, 200, 200), (160, -260, -260, 260, 260)],
        extent=(-400, 400),
        variants=[("equal Priority: the underfill replaces the die's bottom", {"underfill": ""}),
                  ('Underfill Priority="-1": the die stays complete', {"underfill": 'Priority="-1"'})]),
    "e_via": dict(
        title="e  A via drawn into its landing pad: Priority=\"1\" gives the overlap to the via",
        xml=stackup('<Dielectric Name="Oxide" Material="SiO2" Zmin="0" Zmax="20" />',
                    '<Layer Name="Pad" Type="conductor" Material="Aluminium" Layer="30" Zmin="10" Zmax="13" />'
                    '<Layer Name="Via" Type="via" Material="Tungsten" Layer="31" Zmin="5" Zmax="12" {via} />'
                    '<Layer Name="Metal" Type="conductor" Material="Aluminium" Layer="32" Zmin="3" Zmax="5" />',
                    [("SiO2", "Dielectric", "fffcad"), ("Aluminium", "Conductor", "39bfff"),
                     ("Tungsten", "Conductor", "c03030")]),
        shapes=[(30, -30, -30, 30, 30), (31, -6, -6, 6, 6), (32, -30, -30, 30, 30)],
        extent=(-45, 45),
        variants=[("equal Priority: the pad fills the overlap", {"via": ""}),
                  ('Via Priority="1": the via fills its full height', {"via": 'Priority="1"'})]),
}


# ---------------- gds2palace geometry ----------------
class _Stop(Exception):
    pass


def _section_mesh(surfaces):
    """Triangles and outline segments (x, z) of planar surfaces in the plane y = 0, from a 2D mesh of them."""
    triangles, segments = [], []
    for surface in surfaces:
        tags, coords, _ = gmsh.model.mesh.getNodes(2, surface, includeBoundary=True)
        xyz = {t: (coords[3 * i], coords[3 * i + 2]) for i, t in enumerate(tags)}
        types, _, nodes = gmsh.model.mesh.getElements(2, surface)
        for element_type, node_tags in zip(types, nodes):
            n = gmsh.model.mesh.getElementProperties(element_type)[3]
            for k in range(0, len(node_tags), n):
                triangles.append([xyz[t] for t in node_tags[k:k + 3]])
        for _, curve in gmsh.model.getBoundary([(2, surface)], oriented=False):
            ctags, ccoords, _ = gmsh.model.mesh.getNodes(1, abs(curve), includeBoundary=True)
            cxyz = {t: (ccoords[3 * i], ccoords[3 * i + 2]) for i, t in enumerate(ctags)}
            ctypes, _, cnodes = gmsh.model.mesh.getElements(1, abs(curve))
            for node_tags in cnodes:
                for k in range(0, len(node_tags), 2):
                    segments.append((cxyz[node_tags[k]], cxyz[node_tags[k + 1]]))
    return triangles, segments


def model_sections(xml_path, gds_path, extent):
    """Cross-section y = 0 of every physical volume group of the gds2palace model: name -> list of loops."""
    materials, dielectrics, metals = stackup_reader.read_substrate(xml_path)
    thermal_objects = simulation_setup.all_thermal_objects()
    thermal_objects.add_consttemp(simulation_setup.constanttemp(temp=300.0, source_layernum=98, target_layername="BOTTOM"))
    layernumbers = metals.getlayernumbers() + thermal_objects.layers
    polygons = gds_reader.read_gds(gds_path, layernumbers, purposelist=[0], metals_list=metals,
                                   gds_boundary_layers=dielectrics.get_boundary_layers())
    sim_path = tempfile.mkdtemp()
    settings = {"unit": 1e-6, "margin": 0.0, "refined_cellsize": 50.0, "meshsize_max": 1000.0, "no_gui": True,
                "thermal_objects": thermal_objects, "materials_list": materials, "dielectrics_list": dielectrics,
                "metals_list": metals, "layernumbers": layernumbers, "allpolygons": polygons, "sim_path": sim_path,
                "model_basename": "sketch"}
    sections = {}

    def cut_and_stop(*args, **kwargs):
        x0, x1 = extent
        zs = [d.zmin for d in dielectrics.dielectrics] + [d.zmax for d in dielectrics.dielectrics] + \
             [m.zmin for m in metals.metals] + [m.zmax for m in metals.metals]
        z0, z1 = min(zs) - 1, max(zs) + 1
        plane = gmsh.model.occ.addRectangle(x0 - 1, z0, 0, x1 - x0 + 2, z1 - z0)
        gmsh.model.occ.rotate([(2, plane)], 0, 0, 0, 1, 0, 0, math.pi / 2)    # into the plane y = 0
        surfaces_by_name = {}
        for dim, group in gmsh.model.getPhysicalGroups(3):
            name = gmsh.model.getPhysicalName(dim, group)
            for tag in gmsh.model.getEntitiesForPhysicalGroup(dim, group):
                cut, _ = gmsh.model.occ.intersect([(3, tag)], [(2, plane)], removeObject=False, removeTool=False)
                surfaces_by_name.setdefault(name, []).extend(s for d, s in cut if d == 2)
        gmsh.model.occ.synchronize()
        original(2)     # a 2D mesh of everything, including the cut surfaces
        for name, surfaces in surfaces_by_name.items():
            sections[name] = _section_mesh(surfaces)
        raise _Stop

    original = gmsh.model.mesh.generate
    gmsh.model.mesh.generate = cut_and_stop
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            simulation_setup.create_elmer_thermal(settings)
    except _Stop:
        pass
    finally:
        gmsh.model.mesh.generate = original
        if gmsh.isInitialized():
            gmsh.finalize()
    return sections


# ---------------- as written ----------------
def as_written(xml_path, gds_path, extent):
    """Boxes of the <Dielectric>s and drawn layers at y = 0, as written: (name, material, x0, x1, z0, z1, priority)."""
    with contextlib.redirect_stdout(io.StringIO()):
        _, dielectrics, metals = stackup_reader.read_substrate(xml_path)
    lib = gdstk.read_gds(gds_path)
    shapes = {}
    for polygon in lib.top_level()[0].polygons:
        (x0, y0), (x1, y1) = polygon.bounding_box()
        if y0 <= 0 <= y1:
            shapes.setdefault(polygon.layer, []).append((x0, x1))
    boxes = []
    for d in dielectrics.dielectrics:
        spans = shapes.get(int(d.gdsboundary), []) if d.gdsboundary is not None else [extent]
        for x0, x1 in spans:
            boxes.append((d.name, d.material, x0, x1, d.zmin, d.zmax, d.priority))
    for m in metals.metals:
        if not m.is_sheet:
            for x0, x1 in shapes.get(int(m.layernum), []):
                boxes.append((m.name, m.material, x0, x1, m.zmin, m.zmax, m.priority))
    return boxes


def colors_of(xml_path):
    root = ET.parse(xml_path).getroot()
    material = {e.get("Name"): "#" + e.get("Color") for e in root.iter("Material") if e.get("Color")}
    by_name = {e.get("Name"): material.get(e.get("Material"), "#dddddd") for tag in ("Dielectric", "Layer")
               for e in root.iter(tag)}
    return by_name


# ---------------- drawing ----------------
def draw_written(ax, boxes, colors):
    for name, _, x0, x1, z0, z1, priority in boxes:
        ax.add_patch(Rectangle((x0, z0), x1 - x0, z1 - z0, fc=colors[name], alpha=0.45, ec="k", lw=1.0, ls="--"))
    ax.set_title("as written (boxes overlap)", fontsize=10)


def draw_model(ax, sections, colors, title):
    for name, (triangles, segments) in sections.items():
        color = colors.get(name, "#dddddd")
        ax.add_collection(PolyCollection(triangles, facecolors=color, edgecolors=color, linewidths=0.4))
        ax.add_collection(LineCollection(segments, colors="k", linewidths=0.8))
    ax.set_title(title, fontsize=10)


def legend_entries(boxes, colors):
    """One entry per material: "Silicon: Die, Interposer"."""
    names_by_material = {}
    for name, material, *_rest in boxes:
        names = names_by_material.setdefault(material, [])
        if name not in names:
            names.append(name)
    return [Patch(fc=colors[names[0]], ec="k", label=f"{material}: {', '.join(names)}")
            for material, names in names_by_material.items()]


def figure(name, title, xml_text_by_variant, gds_path, extent, variants, z_limits=None):
    xml_paths = {}
    for label, xml_text in xml_text_by_variant.items():
        if os.path.isfile(xml_text):
            xml_paths[label] = xml_text
        else:
            path = os.path.join(tempfile.mkdtemp(), "stackup.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml_text)
            xml_paths[label] = path
    first = xml_paths[variants[0][0]]
    colors = colors_of(first)
    panels = 1 + len(variants)
    fig, axes = plt.subplots(1, panels, figsize=(4.6 * panels, 3.6), sharey=True)
    boxes = as_written(first, gds_path, extent)
    draw_written(axes[0], boxes, colors)
    entries = legend_entries(boxes, colors)
    for ax, (label, _) in zip(axes[1:], variants):
        draw_model(ax, model_sections(xml_paths[label], gds_path, extent), colors, label)
    zs = [b[4] for b in boxes] + [b[5] for b in boxes]
    for ax in axes:
        ax.set_xlim(*extent)
        ax.set_ylim(*(z_limits or (min(zs), max(zs))))
        ax.set_xlabel("x (µm)")
    axes[0].set_ylabel("z (µm)")
    fig.legend(handles=entries, loc="lower center", ncol=len(entries), fontsize=9, frameon=False,
               bbox_to_anchor=(0.5, -0.04))
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, f"priority_{name}.png"), dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"written doc/userguide_md_format/images/priority_{name}.png")


def main():
    # a: the example file 05 and its layout
    figure("a_mold", 'a  A die in mold compound (file 05): Mold Priority="-1", the die keeps the overlap',
           {"in the model": FILE05}, GDS05, (-2200, 2200), [("in the model", {})])
    # b to e: small stackups and layouts written here
    for name, case in CASES.items():
        gds_path = os.path.join(tempfile.mkdtemp(), "layout.gds")
        lib = gdstk.Library()
        cell = lib.new_cell("top")
        extent = case.get("extent", (-300, 300))
        cell.add(gdstk.rectangle((extent[0], extent[0]), (extent[1], extent[1]), layer=98))   # constant temperature
        for layer, x0, y0, x1, y1 in case["shapes"]:
            cell.add(gdstk.rectangle((x0, y0), (x1, y1), layer=layer))
        lib.write_gds(gds_path)
        xml_text = {label: case["xml"].format(**{"underfill": "", "via": "", "cavity": "", **values})
                    for label, values in case["variants"]}
        figure(name, case["title"], xml_text, gds_path, extent, case["variants"])


if __name__ == "__main__":
    main()
