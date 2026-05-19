"""
Unit tests for apps/core/utils.py

Tests:
  - haversine_miles: known distances between real cities
  - compute_bbox: correct expansion with padding
  - make_cache_key: deterministic, case-insensitive, format
  - normalise_location: whitespace collapsing
  - min_distance_to_corridor: nearest-point selection
"""
import math
import pytest

from apps.core.utils import (
    BBox,
    compute_bbox,
    haversine_miles,
    make_cache_key,
    min_distance_to_corridor,
    normalise_location,
)


class TestHaversineMiles:
    def test_same_point_is_zero(self):
        assert haversine_miles(40.0, -74.0, 40.0, -74.0) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_dallas_to_la(self):
        # Dallas, TX  ≈ (32.776, -96.796)
        # Los Angeles, CA ≈ (34.052, -118.243)
        # Straight-line haversine ≈ 1242 miles
        dist = haversine_miles(32.776, -96.796, 34.052, -118.243)
        assert 1220 < dist < 1270, f"Expected ~1242 miles, got {dist:.1f}"

    def test_known_distance_nyc_to_la(self):
        # New York (40.713, -74.006) → Los Angeles (34.052, -118.243) ≈ 2446 miles
        dist = haversine_miles(40.713, -74.006, 34.052, -118.243)
        assert 2400 < dist < 2500, f"Expected ~2446 miles, got {dist:.1f}"

    def test_symmetric(self):
        d1 = haversine_miles(32.776, -96.796, 34.052, -118.243)
        d2 = haversine_miles(34.052, -118.243, 32.776, -96.796)
        assert d1 == pytest.approx(d2, rel=1e-6)

    def test_short_distance(self):
        # ~1 mile apart (approx 0.015° lat difference ≈ 1.03 miles)
        dist = haversine_miles(40.0, -74.0, 40.015, -74.0)
        assert 0.9 < dist < 1.2


class TestComputeBbox:
    def test_single_point_plus_padding(self):
        bbox = compute_bbox([(32.0, -97.0)], padding_deg=0.5)
        assert bbox.min_lat == pytest.approx(31.5)
        assert bbox.max_lat == pytest.approx(32.5)
        assert bbox.min_lng == pytest.approx(-97.5)
        assert bbox.max_lng == pytest.approx(-96.5)

    def test_multiple_points(self):
        points = [(30.0, -100.0), (35.0, -90.0), (32.0, -95.0)]
        bbox = compute_bbox(points, padding_deg=0.0)
        assert bbox.min_lat == pytest.approx(30.0)
        assert bbox.max_lat == pytest.approx(35.0)
        assert bbox.min_lng == pytest.approx(-100.0)
        assert bbox.max_lng == pytest.approx(-90.0)

    def test_padding_is_applied_symmetrically(self):
        points = [(32.0, -96.0)]
        bbox_no_pad = compute_bbox(points, padding_deg=0.0)
        bbox_padded = compute_bbox(points, padding_deg=1.0)
        assert bbox_padded.min_lat == bbox_no_pad.min_lat - 1.0
        assert bbox_padded.max_lat == bbox_no_pad.max_lat + 1.0
        assert bbox_padded.min_lng == bbox_no_pad.min_lng - 1.0
        assert bbox_padded.max_lng == bbox_no_pad.max_lng + 1.0

    def test_zero_padding(self):
        points = [(32.0, -96.0), (33.0, -95.0)]
        bbox = compute_bbox(points, padding_deg=0.0)
        assert isinstance(bbox, BBox)
        assert bbox.min_lat < bbox.max_lat
        assert bbox.min_lng < bbox.max_lng


class TestMakeCacheKey:
    def test_is_64_char_hex(self):
        key = make_cache_key("Dallas, TX", "Los Angeles, CA")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_case_insensitive(self):
        k1 = make_cache_key("Dallas, TX", "Los Angeles, CA")
        k2 = make_cache_key("dallas, tx", "los angeles, ca")
        k3 = make_cache_key("DALLAS, TX", "LOS ANGELES, CA")
        assert k1 == k2 == k3

    def test_strips_whitespace(self):
        k1 = make_cache_key("Dallas, TX", "Los Angeles, CA")
        k2 = make_cache_key("  Dallas, TX  ", "  Los Angeles, CA  ")
        assert k1 == k2

    def test_different_pairs_different_keys(self):
        k1 = make_cache_key("Dallas, TX", "Los Angeles, CA")
        k2 = make_cache_key("Houston, TX", "Los Angeles, CA")
        k3 = make_cache_key("Dallas, TX", "Phoenix, AZ")
        assert k1 != k2
        assert k1 != k3
        assert k2 != k3

    def test_reversed_pair_is_different(self):
        # Start and finish are not interchangeable
        k1 = make_cache_key("Dallas, TX", "Los Angeles, CA")
        k2 = make_cache_key("Los Angeles, CA", "Dallas, TX")
        assert k1 != k2

    def test_deterministic(self):
        k1 = make_cache_key("Dallas, TX", "Los Angeles, CA")
        k2 = make_cache_key("Dallas, TX", "Los Angeles, CA")
        assert k1 == k2


class TestNormaliseLocation:
    def test_strips_leading_trailing_whitespace(self):
        assert normalise_location("  Dallas, TX  ") == "Dallas, TX"

    def test_collapses_internal_spaces(self):
        assert normalise_location("Dallas,   TX") == "Dallas, TX"

    def test_collapses_tabs_and_newlines(self):
        assert normalise_location("Dallas,\tTX\n") == "Dallas, TX"

    def test_already_clean(self):
        assert normalise_location("Dallas, TX") == "Dallas, TX"


class TestMinDistanceToCorridor:
    def test_returns_minimum_distance(self):
        # Station exactly on one of the corridor points
        station_lat, station_lng = 32.0, -96.0
        corridor = [(32.0, -96.0), (33.0, -97.0), (34.0, -98.0)]
        dist = min_distance_to_corridor(station_lat, station_lng, corridor)
        assert dist == pytest.approx(0.0, abs=1e-6)

    def test_picks_closest_point(self):
        station_lat, station_lng = 32.0, -96.0
        near = (32.01, -96.0)   # ~0.7 miles away
        far = (35.0, -100.0)    # very far
        corridor = [near, far]
        dist = min_distance_to_corridor(station_lat, station_lng, corridor)
        assert dist < 2.0  # must pick the nearby point, not the far one
