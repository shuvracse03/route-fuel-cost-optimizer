"""
Unit tests for the DP fuel optimizer (_run_dp) in fuel_selector.py.

We test the pure algorithmic core (_run_dp) directly — no DB, no Django ORM.
This is the most important algorithmic test: verify DP produces globally
optimal results vs what a greedy approach would choose.
"""
import pytest

# We import the private function directly for unit testing the algorithm
from apps.route.services.fuel_selector import _run_dp, _build_stops


def _make_candidate(route_miles: float, price: float, opis_id: int = 1) -> dict:
    """Helper to build a minimal candidate dict for DP tests."""
    return {
        "opis_id": opis_id,
        "name": f"Station {opis_id}",
        "address": "Test Rd",
        "city": "Testville",
        "state": "TX",
        "lat": 32.0,
        "lng": -96.0,
        "price": price,
        "route_miles": route_miles,
        "off_route_miles": 0.0,
    }


class TestRunDpBasic:
    def test_no_stops_needed_short_route(self):
        """Route < 500 miles: destination reachable directly from START."""
        candidates = [
            _make_candidate(100.0, 3.00, 1),
            _make_candidate(200.0, 2.50, 2),
        ]
        stop_indices = _run_dp(candidates, total_distance_miles=400.0)
        # No stop is necessary — vehicle can reach destination without refuelling
        assert stop_indices is not None
        assert stop_indices == []

    def test_one_stop_required_long_route(self):
        """Route 600 miles with one candidate: must stop."""
        candidates = [
            _make_candidate(300.0, 3.00, 1),
        ]
        stop_indices = _run_dp(candidates, total_distance_miles=600.0)
        assert stop_indices == [1]

    def test_returns_none_when_no_valid_path(self):
        """No stations within 500 miles: destination unreachable."""
        # Station at mile 600 — but from START (0) → 600 > 500, unreachable
        # And destination at 700 → station can't reach it either (100 mi gap)
        candidates = [
            _make_candidate(600.0, 3.00, 1),
        ]
        # Destination at 700; START→station=600>500, station→END=100 ok BUT
        # START→station is invalid. Expect None.
        result = _run_dp(candidates, total_distance_miles=700.0)
        assert result is None

    def test_empty_candidates_short_route(self):
        """No candidates, route < 500 miles: valid empty path."""
        stop_indices = _run_dp([], total_distance_miles=400.0)
        assert stop_indices == []

    def test_empty_candidates_long_route(self):
        """No candidates, route > 500 miles: unreachable."""
        result = _run_dp([], total_distance_miles=700.0)
        assert result is None


class TestRunDpOptimality:
    """
    These tests verify DP produces globally optimal results — the core
    algorithmic correctness proof that a greedy approach cannot guarantee.
    """

    def test_dp_skips_expensive_station(self):
        """
        Replicates the README example:
          A: mile 320, $2.50  ← DP picks this
          B: mile 400, $3.50  ← Greedy would be forced here (350-480 mi window)
          C: mile 750, $2.80

        DP should choose [A, C], NOT [B, C].
        """
        candidates = [
            _make_candidate(320.0, 2.50, opis_id=1),   # A
            _make_candidate(400.0, 3.50, opis_id=2),   # B
            _make_candidate(750.0, 2.80, opis_id=3),   # C
        ]
        # Must sort by route_miles (as the real code does before calling _run_dp)
        candidates.sort(key=lambda c: c["route_miles"])

        stop_indices = _run_dp(candidates, total_distance_miles=1000.0)
        assert stop_indices is not None

        chosen_opis_ids = [candidates[i - 1]["opis_id"] for i in stop_indices]
        assert 1 in chosen_opis_ids, "DP should stop at station A (cheaper)"
        assert 2 not in chosen_opis_ids, "DP should skip station B (expensive)"
        assert 3 in chosen_opis_ids, "DP should stop at station C"

    def test_dp_chooses_cheaper_path_over_fewer_stops(self):
        """
        Route: 0 → 1100 miles (must stop — too far to reach END in one tank).

        Two paths to END:
          Path 1 (2 stops via expensive X): START→X(400mi,$5.00)→B(900mi,$2.00)→END
            cost = 0 (free first leg) + (500/10)*$5.00 + (200/10)*$2.00 = $250+$40 = $290

          Path 2 (2 stops via cheap A):  START→A(450mi,$2.00)→B(900mi,$2.00)→END
            cost = 0 (free first leg) + (450/10)*$2.00 + (200/10)*$2.00 = $90+$40 = $130 ← optimal

        DP should pick A (cheaper) over X (expensive), even though both are reachable from START.
        """
        candidates = [
            _make_candidate(400.0, 5.00, opis_id=2),   # X — expensive
            _make_candidate(450.0, 2.00, opis_id=1),   # A — cheap
            _make_candidate(900.0, 2.00, opis_id=3),   # B
        ]
        candidates.sort(key=lambda c: c["route_miles"])

        stop_indices = _run_dp(candidates, total_distance_miles=1100.0)
        assert stop_indices is not None

        chosen_opis_ids = [candidates[i - 1]["opis_id"] for i in stop_indices]
        assert 2 not in chosen_opis_ids, "Should not stop at expensive station X"
        assert 1 in chosen_opis_ids, "Should stop at cheap station A"
        assert 3 in chosen_opis_ids, "Should stop at B to reach END"

    def test_dp_cost_is_globally_minimal(self):
        """
        Verify the total cost computed via DP is less than any alternative path.

        Route: 0 → 1000 miles (R at 700mi is unreachable from START — 700 > 500)

        Stations:
          Q: mile 300, $2.00 (cheap)
          P: mile 450, $3.50 (expensive)
          R: mile 700, $2.50 (must be reached via Q or P)

        All valid paths (first leg is always FREE — START→first stop costs $0):
          [Q, R]:   0 + (400/10)*$2.00 + (300/10)*$2.50 = $80 + $75 = $155  ← optimal
          [P, R]:   0 + (250/10)*$3.50 + (300/10)*$2.50 = $87.5 + $75 = $162.5
          [Q,P,R]:  0 + (150/10)*$2.00 + (250/10)*$3.50 + $75 = $30+$87.5+$75 = $192.5

        Expected: Q + R at $155
        """
        candidates = [
            _make_candidate(300.0, 2.00, opis_id=1),   # Q — cheap
            _make_candidate(450.0, 3.50, opis_id=2),   # P — expensive
            _make_candidate(700.0, 2.50, opis_id=3),   # R
        ]
        candidates.sort(key=lambda c: c["route_miles"])

        stop_indices = _run_dp(candidates, total_distance_miles=1000.0)
        assert stop_indices is not None

        chosen_opis_ids = [candidates[i - 1]["opis_id"] for i in stop_indices]
        assert chosen_opis_ids == [1, 3], f"Expected [Q, R] (opis 1,3), got OPIS IDs {chosen_opis_ids}"

    def test_dp_with_many_candidates_stays_optimal(self):
        """DP with 10+ stations still finds the cheapest path."""
        # Route 1500 miles; cheap stations at 400, 900; expensive everywhere else
        candidates = [
            _make_candidate(100.0, 5.00, opis_id=1),
            _make_candidate(200.0, 4.80, opis_id=2),
            _make_candidate(400.0, 2.00, opis_id=3),  # cheap
            _make_candidate(500.0, 4.50, opis_id=4),
            _make_candidate(600.0, 4.90, opis_id=5),
            _make_candidate(700.0, 4.70, opis_id=6),
            _make_candidate(900.0, 2.10, opis_id=7),  # cheap
            _make_candidate(1100.0, 4.60, opis_id=8),
            _make_candidate(1300.0, 4.80, opis_id=9),
        ]
        candidates.sort(key=lambda c: c["route_miles"])

        stop_indices = _run_dp(candidates, total_distance_miles=1500.0)
        assert stop_indices is not None

        chosen_opis_ids = {candidates[i - 1]["opis_id"] for i in stop_indices}
        assert 3 in chosen_opis_ids, "Should stop at cheap station at mile 400"
        assert 7 in chosen_opis_ids, "Should stop at cheap station at mile 900"


class TestBuildStops:
    def test_stop_mileage_set_correctly(self):
        candidates = [
            _make_candidate(300.0, 2.50, opis_id=10),
            _make_candidate(700.0, 3.00, opis_id=20),
        ]
        # stop_indices are 1-based
        stops = _build_stops([1, 2], candidates)
        assert len(stops) == 2
        assert stops[0].miles_from_start == pytest.approx(300.0, abs=0.5)
        assert stops[1].miles_from_start == pytest.approx(700.0, abs=0.5)

    def test_miles_from_last_stop_computed(self):
        candidates = [
            _make_candidate(300.0, 2.50, opis_id=10),
            _make_candidate(700.0, 3.00, opis_id=20),
        ]
        stops = _build_stops([1, 2], candidates)
        assert stops[0].miles_from_last_stop == pytest.approx(300.0, abs=0.5)
        assert stops[1].miles_from_last_stop == pytest.approx(400.0, abs=0.5)

    def test_empty_indices_returns_empty(self):
        candidates = [_make_candidate(300.0, 2.50)]
        stops = _build_stops([], candidates)
        assert stops == []

    def test_stop_fields_populated(self):
        candidates = [_make_candidate(300.0, 2.50, opis_id=42)]
        candidates[0]["name"] = "Test Station"
        candidates[0]["city"] = "Austin"
        candidates[0]["state"] = "TX"
        stops = _build_stops([1], candidates)
        assert stops[0].opis_id == 42
        assert stops[0].name == "Test Station"
        assert stops[0].price_per_gallon == pytest.approx(2.50)
