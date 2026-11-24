import unittest

from proofmarket.intervals import (
    cells_between,
    contains_union,
    first_gap,
    intersect_all_unions,
    normalize,
    subtract_union,
)


class IntervalTests(unittest.TestCase):
    def test_adjacent_half_open_intervals_merge(self):
        self.assertEqual(normalize([[0, 40], [40, 100]]), [(0, 100)])

    def test_overlap_and_union(self):
        self.assertEqual(normalize([(60, 100), (0, 70), (20, 30)]), [(0, 100)])

    def test_intersection_and_subtraction(self):
        a = normalize([(0, 60), (80, 100)])
        b = normalize([(40, 90)])
        self.assertEqual(intersect_all_unions(a, b), [(40, 60), (80, 90)])
        self.assertEqual(subtract_union(a, b), [(0, 40), (90, 100)])

    def test_contains_and_gap(self):
        required = [(0, 1_000_000_000)]
        covered = [(0, 400_000_000), (600_000_000, 1_000_000_000)]
        self.assertFalse(contains_union(required, covered))
        self.assertEqual(first_gap(required, covered), (400_000_000, 600_000_000))

    def test_only_endpoint_cells_are_created(self):
        cells = cells_between(0, 10**9, [400_000_000, 600_000_000])
        self.assertEqual(
            cells,
            [(0, 400_000_000), (400_000_000, 600_000_000), (600_000_000, 1_000_000_000)],
        )


if __name__ == "__main__":
    unittest.main()
