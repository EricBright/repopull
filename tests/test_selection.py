"""Tests for the menu selection parser."""

from __future__ import annotations

import unittest

from repopull.menu import SelectionError, parse_selection


class ParseSelectionTests(unittest.TestCase):
    def test_individual_numbers(self) -> None:
        self.assertEqual(parse_selection("1,3,5", 10), [1, 3, 5])

    def test_ranges_and_numbers(self) -> None:
        self.assertEqual(parse_selection("1,3,5-7", 10), [1, 3, 5, 6, 7])

    def test_all(self) -> None:
        self.assertEqual(parse_selection("all", 3), [1, 2, 3])

    def test_none_and_empty(self) -> None:
        self.assertEqual(parse_selection("none", 3), [])
        self.assertEqual(parse_selection("", 3), [])

    def test_duplicates_collapse(self) -> None:
        self.assertEqual(parse_selection("2,2,2-2", 3), [2])

    def test_out_of_range(self) -> None:
        with self.assertRaises(SelectionError):
            parse_selection("0", 3)
        with self.assertRaises(SelectionError):
            parse_selection("4", 3)

    def test_reversed_range(self) -> None:
        with self.assertRaises(SelectionError):
            parse_selection("5-3", 10)

    def test_garbage(self) -> None:
        with self.assertRaises(SelectionError):
            parse_selection("alpha", 3)
