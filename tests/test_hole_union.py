"""gdstk unions and offsets (via array merging, derived layers) must keep holes. gdstk 1.0.2 normally links a hole to
its outline (a keyhole polygon), but in some unions of many shapes it returns the hole as a separate polygon that only
runs clockwise, which fracture() made solid: a 7350 um2 cut-out of a Metal1 plane came out filled. The 29 shapes are
the smallest set from a real layout (FMD_QNC_amps_filled.gds, Metal1) that shows it. The same code is in gds2openEMS
(tests/test_sibling_copies.py) and the same fix in gds_prepare_for_EM 1.9.1.

    python -m pytest tests/test_hole_union.py
"""
import gdstk
import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from gds2palace import util_gds_reader as reader

SHAPES = [(-200.0, -366.0, -197.0, 306.0), (-159.205, 240.0, -91.505, 261.5), (-197.505, -305.0, -195.005, -300.0),
          (-193.005, -310.7, -132.705, -307.0), (-193.405, -333.9, -79.675, -310.7), (-197.505, 211.8, -91.505, 234.9),
          (-159.205, 261.5, -91.505, 266.4), (-132.39, 266.4, -130.805, 269.85), (-125.89, 266.4, -124.305, 269.85),
          [(-143.555, 268.6), (-142.555, 268.6), (-142.555, 274.6), (-120.605, 274.6), (-120.605, 268.5),
           (-119.605, 268.5), (-119.605, 275.6), (-143.555, 275.6)],
          (-118.405, -310.7, -79.675, -308.4), (-118.405, -308.4, -113.505, -302.1), (-195.005, -360.0, -193.005, -300.0),
          (-87.5, 222.5, -57.5, 252.5), (-92.5, 247.5, -87.5, 252.5), (-92.5, 222.5, -87.5, 227.5),
          (-92.5, 257.5, -87.5, 262.5), (-77.5, -312.5, -47.5, -282.5), (-82.5, -282.5, -72.5, -277.5),
          (-82.5, -312.5, -77.5, -307.5), (-122.5, -242.5, -92.5, -212.5), (-127.5, -242.5, -122.5, -237.5),
          (-192.5, -242.5, -162.5, -212.5), (-197.5, -242.5, -192.5, -237.5), (-157.5, -242.5, -127.5, -212.5),
          (-162.5, -242.5, -157.5, -237.5), (-92.5, -242.5, -87.5, -237.5), (-87.5, -277.5, -57.5, -247.5),
          (-92.5, -247.5, -82.5, -242.5)]
IN_THE_HOLE = Point(-142.25, -262.5)
ISLAND = (-180.0, -300.0, -170.0, -290.0)       # a shape inside the hole: it must stay


def points(shapes):
    return [np.array([(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]) if isinstance(r, tuple) else np.array(r)
            for r in shapes]


def expected(shapes):
    return unary_union([box(*r) if isinstance(r, tuple) else Polygon(r) for r in shapes])


def as_read(pieces):
    """the fractured pieces as every GDSII reader takes them: each one is metal, whatever its direction"""
    return [Polygon(p).buffer(0) for p in pieces]


def test_gdstk_still_returns_the_hole_separately():
    """if this fails, gdstk links the hole now and the repair is no longer exercised by these shapes"""
    result = gdstk.boolean(points(SHAPES), [], 'or')
    assert any(reader._signed_area(p.points) < 0 for p in result)


def test_union_keeps_its_hole():
    pieces = as_read(reader._fracture(gdstk.boolean(points(SHAPES), [], 'or')))
    assert not any(p.contains(IN_THE_HOLE) for p in pieces), "the hole was filled"
    assert unary_union(pieces).area == pytest.approx(expected(SHAPES).area, rel=1e-9)
    assert sum(p.area for p in pieces) == pytest.approx(expected(SHAPES).area, rel=1e-9), "pieces overlap"


def test_island_inside_the_hole_stays():
    shapes = SHAPES + [ISLAND]
    pieces = as_read(reader._fracture(gdstk.boolean(points(shapes), [], 'or')))
    assert any(p.contains(Point(-175, -295)) for p in pieces), "the island was cut out with the hole"
    assert not any(p.contains(IN_THE_HOLE) for p in pieces)
    assert unary_union(pieces).area == pytest.approx(expected(shapes).area, rel=1e-9)


def test_via_array_merge_keeps_the_hole():
    """merge_via_array() grows, unites and shrinks: the same union, on the via layers"""
    merged = as_read(reader.merge_via_array([p for p in points(SHAPES)], 0.0))
    assert not any(p.contains(IN_THE_HOLE) for p in merged)


def test_usual_results_are_left_alone():
    frame = points([(0, 0, 10, 2), (0, 8, 10, 10), (0, 0, 2, 10), (8, 0, 10, 10)])
    result = gdstk.boolean(frame, [], 'or')
    assert reader._with_holes_cut(result) is result
