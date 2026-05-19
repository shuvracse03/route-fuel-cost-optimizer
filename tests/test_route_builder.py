"""
Unit tests for apps/route/services/route_builder.py

Tests:
  - build_mile_markers: coordinate → cumulative mileage
  - build_mile_markers: edge cases (empty, single point)
"""
import pytest

from apps.route.services.route_builder import build_mile_markers
from apps.core.utils import haversine_miles


class TestBuildMileMarkers:
    def test_empty_coords_returns_empty(self):
        assert build_mile_markers([]) == []

    def test_single_coord_returns_zero_miles(self):
        markers = build_mile_markers([[-96.796, 32.776]])
        assert len(markers) == 1
        lat, lng, miles = markers[0]
        assert lat == pytest.approx(32.776)
        assert lng == pytest.approx(-96.796)
        assert miles == pytest.approx(0.0)

    def test_two_coords_accumulate_correctly(self):
        # Dallas to a point ~50 miles north
        coord_a = [-96.796, 32.776]   # [lng, lat]
        coord_b = [-96.796, 33.500]   # [lng, lat]  ~50 miles north
        markers = build_mile_markers([coord_a, coord_b])

        assert len(markers) == 2
        assert markers[0][2] == pytest.approx(0.0)

        expected = haversine_miles(32.776, -96.796, 33.500, -96.796)
        assert markers[1][2] == pytest.approx(expected, rel=1e-4)

    def test_three_coords_are_cumulative(self):
        # Three points: A → B → C
        # Mileage at C should be dist(A,B) + dist(B,C)
        coord_a = [-96.796, 32.776]
        coord_b = [-97.000, 32.900]
        coord_c = [-97.500, 33.100]
        markers = build_mile_markers([coord_a, coord_b, coord_c])

        assert len(markers) == 3
        assert markers[0][2] == pytest.approx(0.0)
        assert markers[1][2] > 0.0
        assert markers[2][2] > markers[1][2]

        # Verify cumulative: C's mileage = A→B + B→C
        ab = haversine_miles(32.776, -96.796, 32.900, -97.000)
        bc = haversine_miles(32.900, -97.000, 33.100, -97.500)
        assert markers[2][2] == pytest.approx(ab + bc, rel=1e-4)

    def test_lat_lng_are_swapped_from_geojson(self):
        # GeoJSON uses [lng, lat]; markers should store (lat, lng, miles)
        coord = [-118.243, 34.052]   # [lng=−118.243, lat=34.052]
        markers = build_mile_markers([coord])
        lat, lng, _ = markers[0]
        assert lat == pytest.approx(34.052)
        assert lng == pytest.approx(-118.243)

    def test_mileage_strictly_increasing(self):
        # All distinct points moving west across the US
        coords = [
            [-96.796, 32.776],
            [-100.000, 32.776],
            [-104.000, 32.776],
            [-110.000, 32.776],
            [-118.243, 34.052],
        ]
        markers = build_mile_markers(coords)
        miles = [m[2] for m in markers]
        for i in range(1, len(miles)):
            assert miles[i] > miles[i - 1], f"Miles not increasing at index {i}"

    def test_long_route_reasonable_total(self):
        # Dallas → El Paso → Los Angeles — rough checkpoints
        coords = [
            [-96.796, 32.776],   # Dallas
            [-106.489, 31.760],  # El Paso (~620 mi from Dallas)
            [-118.243, 34.052],  # Los Angeles
        ]
        markers = build_mile_markers(coords)
        total_miles = markers[-1][2]
        # Straight-line haversine Dallas→LA ≈ 1242 mi; with detour via El Paso, ~1380 mi
        assert 1200 < total_miles < 1500, f"Unexpected total: {total_miles:.1f} mi"
