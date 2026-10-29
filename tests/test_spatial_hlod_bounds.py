"""The polygon bounds pre-check never changes a brush-region membership answer."""
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import rebuild_spatial_hlod
from rebuild_spatial_hlod import bounded_contains, polygon_bounds, polygon_contains


def polygons(rng):
    yield [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]                  # axis-aligned, shared y values
    yield [(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (4.0, 2.0), (0.0, 8.0)]          # concave
    yield [(0.0, 0.0), (5.0, 5.0), (10.0, 10.0)]                                # collinear
    yield [(4095.75, 4095.5), (4095.875, 4095.5), (4095.8125, 4095.625)]        # tiny, at map scale
    for _ in range(300):
        cx, cy, r = rng.uniform(0, 4096), rng.uniform(0, 4096), rng.uniform(.01, 200)
        count = rng.randint(3, 12)
        angles = sorted(rng.uniform(0, 2 * math.pi) for _ in range(count))
        poly = [(cx + r * rng.uniform(.2, 1) * math.cos(a), cy + r * rng.uniform(.2, 1) * math.sin(a)) for a in angles]
        if rng.random() < .3:   # snap to a coarse grid: repeated x/y values and on-edge points
            poly = [(round(x), round(y)) for x, y in poly]
        yield [(float(x), float(y)) for x, y in poly]


def points(rng, poly, bounds):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    yield from poly
    for a, b in zip(poly, poly[1:] + poly[:1]):
        yield ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    lo_x, hi_x, lo_y, hi_y = bounds
    for x in (lo_x, hi_x, min(xs), max(xs), math.nextafter(lo_x, -math.inf), math.nextafter(hi_x, math.inf)):
        for y in (lo_y, hi_y, math.nextafter(lo_y, -math.inf), math.nextafter(hi_y, -math.inf), (lo_y + hi_y) / 2):
            yield (x, y)
    for _ in range(60):
        yield (rng.uniform(min(xs) - 5, max(xs) + 5), rng.uniform(min(ys) - 5, max(ys) + 5))


class PolygonBoundsTests(unittest.TestCase):
    def test_bounded_check_matches_the_edge_walk(self):
        rng = random.Random(20261028); checked = 0
        for poly in polygons(rng):
            bounds = polygon_bounds(poly)
            for point in points(rng, poly, bounds):
                self.assertEqual(bounded_contains(point, poly, bounds), polygon_contains(point, poly), (poly, point))
                checked += 1
        self.assertGreater(checked, 25_000)

    def test_far_points_skip_the_edge_walk(self):
        poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        with patch.object(rebuild_spatial_hlod, 'polygon_contains', wraps=polygon_contains) as walk:
            for point in [(-1.0, 5.0), (11.0, 5.0), (5.0, -1.0), (5.0, 10.0), (500.0, 500.0)]:
                self.assertFalse(bounded_contains(point, poly, polygon_bounds(poly)))
            self.assertEqual(walk.call_count, 0)
            self.assertTrue(bounded_contains((5.0, 5.0), poly, polygon_bounds(poly)))
            self.assertEqual(walk.call_count, 1)

    def test_non_finite_polygon_keeps_the_full_test(self):
        poly = [(0.0, 0.0), (math.nan, 0.0), (10.0, 10.0)]
        self.assertIsNone(polygon_bounds(poly))
        self.assertEqual(bounded_contains((5.0, 5.0), poly, None), polygon_contains((5.0, 5.0), poly))


if __name__ == '__main__':
    unittest.main()
