from __future__ import annotations

import unittest

from core.api.http_validators import if_none_match_matches, if_range_matches, parse_entity_tag_list, strong_etag


class HttpValidatorsTestCase(unittest.TestCase):
    def test_if_none_match_matches_single_tag(self) -> None:
        self.assertTrue(if_none_match_matches('"revision-1"', '"revision-1"'))
        self.assertFalse(if_none_match_matches('"revision-2"', '"revision-1"'))

    def test_if_none_match_uses_weak_comparison_for_lists(self) -> None:
        self.assertTrue(if_none_match_matches('"older", W/"revision-1", "newer"', '"revision-1"'))
        self.assertTrue(if_none_match_matches('"name,with,commas"', 'W/"name,with,commas"'))

    def test_if_none_match_supports_wildcard(self) -> None:
        self.assertTrue(if_none_match_matches("*", '"revision-1"'))

    def test_malformed_if_none_match_is_ignored(self) -> None:
        for value in ('revision-1', '"unterminated', '*, "revision-1"', '"one",'):
            with self.subTest(value=value):
                self.assertIsNone(parse_entity_tag_list(value))
                self.assertFalse(if_none_match_matches(value, '"revision-1"'))

    def test_if_range_requires_matching_strong_tag(self) -> None:
        self.assertTrue(if_range_matches('"revision-1"', '"revision-1"'))
        self.assertFalse(if_range_matches('"revision-2"', '"revision-1"'))
        self.assertFalse(if_range_matches('W/"revision-1"', '"revision-1"'))
        self.assertFalse(if_range_matches('"revision-1"', 'W/"revision-1"'))

    def test_if_range_rejects_lists_dates_and_malformed_values(self) -> None:
        for value in ('"one", "two"', "Wed, 21 Oct 2015 07:28:00 GMT", "revision-1", "*"):
            with self.subTest(value=value):
                self.assertFalse(if_range_matches(value, '"revision-1"'))

    def test_strong_etag_normalizes_backend_values(self) -> None:
        self.assertEqual(strong_etag("revision-1"), '"revision-1"')
        self.assertEqual(strong_etag('W/"revision-1"'), '"revision-1"')
        self.assertEqual(strong_etag("bad\r\nvalue"), '"badvalue"')


if __name__ == "__main__":
    unittest.main()
