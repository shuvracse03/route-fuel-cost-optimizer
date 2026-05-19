"""
Unit tests for apps/route/services/cost_calculator.py

Tests per-segment cost calculation, edge cases (no stops, single stop),
and aggregate totals.
"""
import pytest

from apps.route.services.cost_calculator import (
    FuelCostSummary,
    FuelSegment,
    calculate_fuel_cost,
)
from apps.route.services.fuel_selector import SelectedStop


def _make_stop(miles_from_start: float, price: float, miles_from_last: float = None) -> SelectedStop:
    if miles_from_last is None:
        miles_from_last = miles_from_start
    return SelectedStop(
        opis_id=1,
        name="Test Station",
        address="Test Rd",
        city="Testville",
        state="TX",
        lat=32.0,
        lng=-96.0,
        price_per_gallon=price,
        miles_from_start=miles_from_start,
        miles_from_last_stop=miles_from_last,
    )


class TestCalculateFuelCostNoStops:
    def test_no_stops_returns_correct_gallons(self):
        result = calculate_fuel_cost([], total_distance_miles=400.0)
        assert result.total_gallons == pytest.approx(40.0)

    def test_no_stops_cost_is_zero(self):
        # Without stops we cannot price the fuel
        result = calculate_fuel_cost([], total_distance_miles=300.0)
        assert result.total_cost_usd == pytest.approx(0.0)

    def test_no_stops_num_stops_is_zero(self):
        result = calculate_fuel_cost([], total_distance_miles=400.0)
        assert result.num_stops == 0

    def test_no_stops_segments_empty(self):
        result = calculate_fuel_cost([], total_distance_miles=400.0)
        assert result.segments == []


class TestCalculateFuelCostOneStop:
    def test_one_stop_two_segments(self):
        stops = [_make_stop(miles_from_start=300.0, price=3.00)]
        result = calculate_fuel_cost(stops, total_distance_miles=600.0)
        assert len(result.segments) == 2

    def test_segment_distances_sum_to_total(self):
        stops = [_make_stop(miles_from_start=300.0, price=3.00)]
        result = calculate_fuel_cost(stops, total_distance_miles=600.0)
        total = sum(s.distance_miles for s in result.segments)
        assert total == pytest.approx(600.0, abs=0.1)

    def test_known_cost_one_stop(self):
        """
        Route: 600 miles total, stop at 300 mi at $3.00/gal, 10 MPG.
          Segment 1: 300 miles → 30 gallons × $3.00 = $90
          Segment 2: 300 miles → 30 gallons × $3.00 = $90
          Total: $180
        """
        stops = [_make_stop(miles_from_start=300.0, price=3.00)]
        result = calculate_fuel_cost(stops, total_distance_miles=600.0)
        assert result.total_cost_usd == pytest.approx(180.0, abs=0.01)

    def test_total_gallons_equals_total_distance_over_mpg(self):
        stops = [_make_stop(miles_from_start=300.0, price=3.00)]
        result = calculate_fuel_cost(stops, total_distance_miles=600.0)
        assert result.total_gallons == pytest.approx(60.0, abs=0.01)


class TestCalculateFuelCostMultipleStops:
    def test_three_stops_four_segments(self):
        stops = [
            _make_stop(200.0, 2.50),
            _make_stop(500.0, 3.00),
            _make_stop(800.0, 2.80),
        ]
        result = calculate_fuel_cost(stops, total_distance_miles=1000.0)
        assert len(result.segments) == 4

    def test_known_cost_two_stops(self):
        """
        Route: 1000 miles, stops at 400mi ($2.00) and 700mi ($3.00).
          Seg 1: 0→400  = 400/10 * $2.00 = $80
          Seg 2: 400→700 = 300/10 * $3.00 = $90
          Seg 3: 700→1000 = 300/10 * $3.00 = $90
          Total: $260
        """
        stops = [
            _make_stop(400.0, 2.00),
            _make_stop(700.0, 3.00),
        ]
        result = calculate_fuel_cost(stops, total_distance_miles=1000.0)
        assert result.total_cost_usd == pytest.approx(260.0, abs=0.01)

    def test_dp_cheaper_than_greedy_scenario(self):
        """
        Verify that the DP-optimal stop sequence produces a lower cost than
        the greedy one on the README example:

          DP stops:    A (mile 320, $2.50) + C (mile 750, $2.80)
          Greedy stops: B (mile 400, $3.50) + C (mile 750, $2.80)

        DP cost:
          0→320: 32 gal × $2.50 = $80.00
          320→750: 43 gal × $2.50 = $107.50   (priced at A where you fill up)
          750→1000: 25 gal × $2.80 = $70.00
          Total: $257.50

        Greedy cost:
          0→400: 40 gal × $3.50 = $140.00
          400→750: 35 gal × $3.50 = $122.50   (priced at B)
          750→1000: 25 gal × $2.80 = $70.00
          Total: $332.50
        """
        dp_stops = [_make_stop(320.0, 2.50), _make_stop(750.0, 2.80)]
        greedy_stops = [_make_stop(400.0, 3.50), _make_stop(750.0, 2.80)]

        dp_result = calculate_fuel_cost(dp_stops, total_distance_miles=1000.0)
        greedy_result = calculate_fuel_cost(greedy_stops, total_distance_miles=1000.0)

        assert dp_result.total_cost_usd < greedy_result.total_cost_usd, (
            f"DP (${dp_result.total_cost_usd}) should be cheaper than "
            f"greedy (${greedy_result.total_cost_usd})"
        )

    def test_avg_price_per_gallon_computed(self):
        stops = [_make_stop(300.0, 3.00)]
        result = calculate_fuel_cost(stops, total_distance_miles=600.0)
        assert result.avg_price_per_gallon == pytest.approx(3.00, abs=0.01)


class TestFuelSegmentStructure:
    def test_segments_have_correct_fields(self):
        stops = [_make_stop(300.0, 2.50)]
        result = calculate_fuel_cost(stops, total_distance_miles=600.0)
        seg = result.segments[0]
        assert hasattr(seg, "from_miles")
        assert hasattr(seg, "to_miles")
        assert hasattr(seg, "distance_miles")
        assert hasattr(seg, "price_per_gallon")
        assert hasattr(seg, "gallons")
        assert hasattr(seg, "cost_usd")

    def test_each_segment_gallons_equals_distance_over_mpg(self):
        stops = [_make_stop(300.0, 2.50), _make_stop(700.0, 3.00)]
        result = calculate_fuel_cost(stops, total_distance_miles=1000.0)
        for seg in result.segments:
            expected_gallons = seg.distance_miles / 10
            assert seg.gallons == pytest.approx(expected_gallons, abs=0.01)

    def test_segment_cost_equals_gallons_times_price(self):
        stops = [_make_stop(300.0, 2.50)]
        result = calculate_fuel_cost(stops, total_distance_miles=600.0)
        for seg in result.segments:
            assert seg.cost_usd == pytest.approx(seg.gallons * seg.price_per_gallon, abs=0.01)
