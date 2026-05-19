"""
Shared utility functions used across the project.
"""
import math
import hashlib
import re
from dataclasses import dataclass
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in miles between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------

@dataclass
class BBox:
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


def compute_bbox(points: List[Tuple[float, float]], padding_deg: float = 0.5) -> BBox:
    """
    Compute an axis-aligned bounding box around a list of (lat, lng) tuples,
    expanded by *padding_deg* degrees on every side.
    """
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return BBox(
        min_lat=min(lats) - padding_deg,
        max_lat=max(lats) + padding_deg,
        min_lng=min(lngs) - padding_deg,
        max_lng=max(lngs) + padding_deg,
    )


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def make_cache_key(start: str, finish: str) -> str:
    """
    Produce a deterministic, case-insensitive cache key for a start/finish pair.

    >>> make_cache_key("Dallas, TX", "Los Angeles, CA")
    == make_cache_key("dallas, tx", "los angeles, ca")
    """
    normalised = f"{start.strip().lower()}|{finish.strip().lower()}"
    return hashlib.sha256(normalised.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Location normalisation
# ---------------------------------------------------------------------------

_MULTI_SPACE = re.compile(r"\s+")


def normalise_location(raw: str) -> str:
    """Strip and collapse whitespace in a location string."""
    return _MULTI_SPACE.sub(" ", raw.strip())


# ---------------------------------------------------------------------------
# Off-route distance
# ---------------------------------------------------------------------------

def min_distance_to_corridor(
    station_lat: float,
    station_lng: float,
    corridor_points: List[Tuple[float, float]],
) -> float:
    """
    Return the minimum haversine distance (miles) from a station to any point
    in the route corridor.  Used as a tiebreaker when multiple stations have
    similar prices.
    """
    return min(
        haversine_miles(station_lat, station_lng, lat, lng)
        for lat, lng in corridor_points
    )
