"""
Globally optimal fuel stop selection using Dynamic Programming (DP).

WHY DP INSTEAD OF GREEDY
─────────────────────────
A greedy window approach divides the route into fixed ~450-mile chunks and
independently picks the cheapest station per window. This can fail:

  Greedy: must stop in Window 1 (350–480 mi) at $3.50/gal
  DP:     stop at mile 320 at $2.50/gal → next stop skips the $3.50 zone

Because the greedy algorithm cannot "look ahead", it makes locally optimal
choices that are globally suboptimal.

DP FORMULATION (DAG Shortest Path)
────────────────────────────────────
Model the trip as a directed acyclic graph:

  • Node 0         = trip START (mile 0, free initial tank)
  • Nodes 1..n     = candidate fuel stations, sorted by ascending route mileage
  • Node n+1 (END) = trip destination (mile = total_distance)

  • Edge (i → j) is valid when 0 < dist(i,j) ≤ 500 miles (vehicle range)
  • Edge cost     = (dist_miles / 10 MPG) × price_per_gallon_at_i
  • Special case  : START → any node costs 0 (vehicle departs with a full tank)

  dp[j]   = minimum total fuel cost to reach node j
  prev[j] = the predecessor node that achieves dp[j]

  Recurrence (forward pass, nodes in mileage order):
    dp[0]   = 0
    dp[j]   = min over all valid i<j:
                dp[i] + (dist(i,j) / 10) × price_at_i
              where "valid" means dist(i,j) ≤ 500
              and   START → j always costs 0

  Answer = dp[END]; backtrack via prev[] to recover actual stop sequence.

COMPLEXITY
──────────
  • Single DB query: O(S) where S = stations in route bounding box (~300–800)
  • Station projection: O(S × M/k) where M = route points, k = sample interval
  • DP: O(S²) worst case, O(S × W) average where W = stations within 500mi (~50–100)
  • Typical runtime: < 100ms for cross-country routes

This guarantees globally minimum fuel cost — no greedy approximation.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

from django.conf import settings

from apps.core.utils import compute_bbox, haversine_miles
from apps.core.request_context import set_data_source, DataSource
from apps.route.models import FuelStation
from apps.route.services.route_builder import MileMarker

logger = logging.getLogger(__name__)

MAX_RANGE_MILES = 500
MPG = 10
# Use every Nth mile marker when projecting stations onto the route.
# At ORS resolution (~50–100m per point), every 10th marker ≈ 0.5 miles of
# error in the station's route position — negligible for our purposes.
_PROJECTION_SAMPLE = 10


@dataclass
class SelectedStop:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    lat: float
    lng: float
    price_per_gallon: float
    miles_from_start: float
    miles_from_last_stop: float


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def select_fuel_stops_dp(
    mile_markers: List[MileMarker],
    total_distance_miles: float,
) -> List[SelectedStop]:
    """
    Return the globally optimal sequence of fuel stops for the route.

    Uses a DAG shortest-path DP to minimise total fuel cost, unlike a greedy
    window approach which is only locally optimal.
    """
    candidates = _fetch_and_project_candidates(mile_markers)

    if not candidates:
        logger.warning("No geocoded stations found along route corridor.")
        return []

    # DP requires ascending mileage order
    candidates.sort(key=lambda c: c["route_miles"])

    logger.debug(
        "DP optimizer: %d candidate stations for %.1f-mile route",
        len(candidates),
        total_distance_miles,
    )

    stop_indices = _run_dp(candidates, total_distance_miles)

    if stop_indices is None:
        logger.warning("DP: no valid path to destination within vehicle range constraints.")
        return []

    return _build_stops(stop_indices, candidates)


# ---------------------------------------------------------------------------
# Station fetching & route projection
# ---------------------------------------------------------------------------

def _fetch_and_project_candidates(mile_markers: List[MileMarker]) -> List[dict]:
    """
    Single DB query: fetch all geocoded stations within the route bounding box.
    Then project each station onto the route and discard those that are too far
    off-route (configurable via FUEL_CANDIDATE_CORRIDOR_MILES, default 30 mi).
    """
    corridor_miles: float = getattr(settings, "FUEL_CANDIDATE_CORRIDOR_MILES", 30.0)

    all_points = [(lat, lng) for lat, lng, _ in mile_markers]
    bbox = compute_bbox(all_points, padding_deg=0.5)

    db_stations = list(
        FuelStation.objects.filter(
            geocoded=True,
            lat__gte=bbox.min_lat,
            lat__lte=bbox.max_lat,
            lng__gte=bbox.min_lng,
            lng__lte=bbox.max_lng,
        )
    )

    logger.debug(
        "DB returned %d candidate stations in route bbox", len(db_stations)
    )

    # Downsample mile markers for projection speed:
    # O(S × M) → O(S × M/k), acceptable accuracy loss (< 0.5 mi error).
    sampled: List[MileMarker] = mile_markers[::_PROJECTION_SAMPLE]
    if not sampled or sampled[-1] != mile_markers[-1]:
        sampled = list(sampled) + [mile_markers[-1]]

    candidates = []
    for station in db_stations:
        # Find closest route point using squared L2 distance (cheap proxy)
        closest = min(
            sampled,
            key=lambda m: (m[0] - station.lat) ** 2 + (m[1] - station.lng) ** 2,
        )

        # Verify with actual haversine distance for the filtering decision
        off_route = haversine_miles(station.lat, station.lng, closest[0], closest[1])

        if off_route > corridor_miles:
            continue

        candidates.append({
            "opis_id": station.opis_id,
            "name": station.name,
            "address": station.address,
            "city": station.city,
            "state": station.state,
            "lat": station.lat,
            "lng": station.lng,
            "price": float(station.min_price),
            "route_miles": closest[2],
            "off_route_miles": off_route,
        })

    logger.debug(
        "%d stations within %.0f-mile corridor after projection filtering",
        len(candidates),
        corridor_miles,
    )
    return candidates


# ---------------------------------------------------------------------------
# Core DP
# ---------------------------------------------------------------------------

def _run_dp(
    candidates: List[dict],
    total_distance_miles: float,
) -> Optional[List[int]]:
    """
    Forward DP pass over sorted candidates.

    Node encoding:
      0       = START  (mile 0, free initial tank)
      1..n    = candidates[0..n-1]  (1-indexed)
      n+1     = END    (mile = total_distance_miles)

    Returns a list of 1-based candidate indices representing the optimal stops,
    or None if the destination is unreachable within vehicle range constraints.
    """
    n = len(candidates)
    START = 0
    END = n + 1
    INF = float("inf")

    dp = [INF] * (n + 2)
    prev = [-1] * (n + 2)
    dp[START] = 0.0

    def get_miles(idx: int) -> float:
        if idx == START:
            return 0.0
        if idx == END:
            return total_distance_miles
        return candidates[idx - 1]["route_miles"]

    def get_price(idx: int) -> float:
        if idx in (START, END):
            return 0.0
        return candidates[idx - 1]["price"]

    # Forward pass: process nodes in strictly ascending mileage order.
    # For each destination node j, search predecessors backwards (i = j-1 → 0).
    # Because get_miles is non-decreasing with index, dist = miles[j] - miles[i]
    # INCREASES as i decreases → we can break as soon as dist > MAX_RANGE.
    for j in range(1, n + 2):
        j_miles = get_miles(j)

        for i in range(j - 1, -1, -1):
            i_miles = get_miles(i)
            dist = j_miles - i_miles

            if dist > MAX_RANGE_MILES:
                break  # All earlier predecessors are even further away

            if dist <= 0.0:
                continue  # Same position or reversed — skip

            if dp[i] == INF:
                continue  # Unreachable predecessor

            # Vehicles departs with a full free tank: first leg costs nothing.
            # All subsequent legs are paid for at the departure station's price.
            leg_cost = 0.0 if i == START else (dist / MPG) * get_price(i)

            total = dp[i] + leg_cost
            if total < dp[j]:
                dp[j] = total
                prev[j] = i

    if dp[END] == INF:
        return None  # Destination unreachable

    logger.debug("DP optimal cost: $%.2f", dp[END])

    # Backtrack from END to START, collecting actual stop nodes (skip START/END)
    stops: List[int] = []
    curr = prev[END]
    while curr not in (START, -1):
        stops.append(curr)
        curr = prev[curr]

    stops.reverse()
    return stops


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------

def _build_stops(stop_indices: List[int], candidates: List[dict]) -> List[SelectedStop]:
    """Convert 1-based candidate index list into SelectedStop dataclass instances."""
    result: List[SelectedStop] = []
    last_miles = 0.0

    for idx in stop_indices:
        cand = candidates[idx - 1]  # convert from 1-based DP index to 0-based list
        stop = SelectedStop(
            opis_id=cand["opis_id"],
            name=cand["name"],
            address=cand["address"],
            city=cand["city"],
            state=cand["state"],
            lat=cand["lat"],
            lng=cand["lng"],
            price_per_gallon=cand["price"],
            miles_from_start=round(cand["route_miles"], 1),
            miles_from_last_stop=round(cand["route_miles"] - last_miles, 1),
        )
        result.append(stop)
        last_miles = cand["route_miles"]

    return result


# ---------------------------------------------------------------------------
# Legacy greedy interface (kept for reference — not called by production code)
# ---------------------------------------------------------------------------

def select_fuel_stops(windows, mile_markers):
    """
    DEPRECATED — greedy window-based selection.
    Use select_fuel_stops_dp() instead for globally optimal results.
    Kept here to avoid import errors if referenced elsewhere.
    """
    raise NotImplementedError(
        "Greedy select_fuel_stops() has been superseded by the DP-based "
        "select_fuel_stops_dp(). Update callers to use the DP version."
    )

