"""
Cost calculator — computes total fuel cost for the trip.

Segment pricing model (consistent with the DP optimizer):
  • [start → stop_1]       : priced at stop_1 (you fill up at stop_1 for the trip so far)
  • [stop_i → stop_{i+1}]  : priced at stop_i (you buy fuel at stop_i to reach stop_{i+1})
  • [last_stop → finish]   : priced at last_stop

Assumptions:
  - Vehicle range: 500 miles max
  - Fuel efficiency: 10 MPG
  - At each fuel stop, buy exactly enough gallons to reach the next waypoint.
  - The first segment (start → stop_1) is priced at stop_1's rate, representing
    the cost of fuelling up at the first stop to account for the initial leg.
"""
from dataclasses import dataclass
from typing import List

from django.conf import settings

from apps.route.services.fuel_selector import SelectedStop


@dataclass
class FuelSegment:
    from_miles: float
    to_miles: float
    distance_miles: float
    price_per_gallon: float
    gallons: float
    cost_usd: float


@dataclass
class FuelCostSummary:
    segments: List[FuelSegment]
    total_gallons: float
    total_cost_usd: float
    avg_price_per_gallon: float
    num_stops: int


def calculate_fuel_cost(
    fuel_stops: List[SelectedStop],
    total_distance_miles: float,
) -> FuelCostSummary:
    """
    Build per-segment cost breakdown and aggregate totals.

    Segments:
      [trip_start → stop_1] priced at stop_1.price
      [stop_1 → stop_2]     priced at stop_2.price
      ...
      [last_stop → finish]  priced at last_stop.price
    """
    mpg = settings.VEHICLE_MPG

    segments: List[FuelSegment] = []

    if not fuel_stops:
        # Short trip — no stops needed; use a nominal price of 0 only if no
        # stops recorded (shouldn't happen as we still compute cost).
        # In practice this branch means the route is under 500 miles.
        # We cannot price the fuel without a station; we return zeros.
        return FuelCostSummary(
            segments=[],
            total_gallons=total_distance_miles / mpg,
            total_cost_usd=0.0,
            avg_price_per_gallon=0.0,
            num_stops=0,
        )

    # Segment: start of trip → first stop (fuelled at first stop's price)
    segments.append(
        _make_segment(
            from_miles=0.0,
            to_miles=fuel_stops[0].miles_from_start,
            price=fuel_stops[0].price_per_gallon,
            mpg=mpg,
        )
    )

    # Intermediate segments
    for i in range(1, len(fuel_stops)):
        segments.append(
            _make_segment(
                from_miles=fuel_stops[i - 1].miles_from_start,
                to_miles=fuel_stops[i].miles_from_start,
                price=fuel_stops[i].price_per_gallon,
                mpg=mpg,
            )
        )

    # Final segment: last stop → destination (priced at last stop)
    segments.append(
        _make_segment(
            from_miles=fuel_stops[-1].miles_from_start,
            to_miles=total_distance_miles,
            price=fuel_stops[-1].price_per_gallon,
            mpg=mpg,
        )
    )

    total_gallons = sum(s.gallons for s in segments)
    total_cost = sum(s.cost_usd for s in segments)
    avg_price = total_cost / total_gallons if total_gallons else 0.0

    return FuelCostSummary(
        segments=segments,
        total_gallons=round(total_gallons, 3),
        total_cost_usd=round(total_cost, 2),
        avg_price_per_gallon=round(avg_price, 4),
        num_stops=len(fuel_stops),
    )


def _make_segment(
    from_miles: float,
    to_miles: float,
    price: float,
    mpg: float,
) -> FuelSegment:
    distance = to_miles - from_miles
    gallons = distance / mpg
    return FuelSegment(
        from_miles=round(from_miles, 2),
        to_miles=round(to_miles, 2),
        distance_miles=round(distance, 2),
        price_per_gallon=price,
        gallons=round(gallons, 3),
        cost_usd=round(gallons * price, 2),
    )
