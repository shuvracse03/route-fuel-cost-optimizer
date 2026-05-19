"""
Route builder — converts ORS GeoJSON coordinates into mile markers and
determines where fuel stops need to occur along the route.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Tuple

from django.conf import settings

from apps.core.utils import haversine_miles

logger = logging.getLogger(__name__)

# (lat, lng, cumulative_miles_from_start)
MileMarker = Tuple[float, float, float]


@dataclass
class FuelWindow:
    """A mile-range corridor where the vehicle must refuel."""

    search_start_miles: float   # start scanning for a station here
    search_end_miles: float     # latest acceptable stop mile
    corridor_points: List[Tuple[float, float]] = field(default_factory=list)
    # (lat, lng) pairs within this window's mile range


def build_mile_markers(coordinates: list) -> List[MileMarker]:
    """
    Walk ORS GeoJSON coordinates [[lng, lat], ...] and attach cumulative
    mileage to each point.

    Returns a list of (lat, lng, cumulative_miles).
    """
    if not coordinates:
        return []

    markers: List[MileMarker] = []
    cumulative = 0.0
    prev_lat = coordinates[0][1]
    prev_lng = coordinates[0][0]
    markers.append((prev_lat, prev_lng, 0.0))

    for lng, lat in coordinates[1:]:
        cumulative += haversine_miles(prev_lat, prev_lng, lat, lng)
        markers.append((lat, lng, cumulative))
        prev_lat, prev_lng = lat, lng

    return markers


def build_fuel_windows(
    mile_markers: List[MileMarker],
    total_distance_miles: float,
) -> List[FuelWindow]:
    """
    Determine the set of FuelWindow objects — each representing a corridor
    where the vehicle must stop to refuel.

    The algorithm advances a "last_fueled_at" pointer along the route.
    Each time the remaining range would exceed MAX_RANGE, we create a window
    starting at SEARCH_START_OFFSET miles after the last stop and ending at
    SEARCH_END_OFFSET miles (leaving a 20-mile safety margin).
    """
    max_range = settings.VEHICLE_MAX_RANGE_MILES          # 500
    search_start_offset = settings.FUEL_SEARCH_START_OFFSET  # 350
    search_end_offset = settings.FUEL_SEARCH_END_OFFSET      # 480
    assumed_stop = settings.FUEL_ASSUMED_STOP                 # 450

    windows: List[FuelWindow] = []
    last_fueled_at = 0.0

    while (total_distance_miles - last_fueled_at) > max_range:
        search_start = last_fueled_at + search_start_offset
        search_end = last_fueled_at + search_end_offset

        # Gather route points that fall inside this window's mile range
        corridor = [
            (lat, lng)
            for lat, lng, mi in mile_markers
            if search_start <= mi <= search_end
        ]

        # If we got no corridor points (e.g. very long straight segment),
        # fall back to the single nearest point to the midpoint of the window.
        if not corridor:
            midpoint_mile = (search_start + search_end) / 2
            nearest = min(
                mile_markers,
                key=lambda m: abs(m[2] - midpoint_mile),
            )
            corridor = [(nearest[0], nearest[1])]
            logger.debug(
                "No corridor points for window [%.1f–%.1f]; using nearest point %.1f mi",
                search_start,
                search_end,
                nearest[2],
            )

        windows.append(
            FuelWindow(
                search_start_miles=search_start,
                search_end_miles=search_end,
                corridor_points=corridor,
            )
        )
        last_fueled_at += assumed_stop

    logger.debug(
        "Built %d fuel window(s) for %.1f-mile route", len(windows), total_distance_miles
    )
    return windows
