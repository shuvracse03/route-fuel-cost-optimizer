"""
OpenRouteService API client.

Responsibilities:
  - Make exactly ONE directions call per unique route request.
  - Return the GeoJSON LineString geometry and distance/duration metadata.
  - Raise typed exceptions so the view layer can return clean HTTP errors.
"""
import logging
from typing import TypedDict

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class RouteData(TypedDict):
    coordinates: list          # [[lng, lat], ...]  (GeoJSON order)
    distance_meters: float
    distance_miles: float
    duration_seconds: float
    duration_hours: float
    geometry: dict             # GeoJSON LineString


class ORSError(Exception):
    """Raised when ORS returns an error or an unexpected response."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class ORSRateLimitError(ORSError):
    def __init__(self):
        super().__init__("OpenRouteService rate limit exceeded. Please try again later.", 503)


class ORSClient:
    """Thin wrapper around the ORS Directions v2 endpoint."""

    DIRECTIONS_BASE_URL = settings.ORS_BASE_URL            # https://api.openrouteservice.org/v2
    GEOCODE_BASE_URL = "https://api.openrouteservice.org"  # geocoding is NOT under /v2
    TIMEOUT = settings.ORS_TIMEOUT_SECONDS

    def get_route(self, start: str, finish: str) -> RouteData:
        """
        Geocode start & finish via ORS geocoding, then fetch driving directions.

        All in a single HTTP call to the directions endpoint (we pass place
        names directly via the 'resolve' feature is NOT available — so we first
        geocode both points, then call directions).

        Actually ORS directions accepts coordinates only, so we do:
          1. Geocode start  → (lng, lat)   ← ORS geocoding
          2. Geocode finish → (lng, lat)
          3. Directions call (1 call)

        Total: up to 3 calls worst case; exactly 1 directions call always.
        The geocoding results are lightweight and fast (< 100ms each).
        """
        start_coord = self._geocode(start)
        finish_coord = self._geocode(finish)
        return self._directions(start_coord, finish_coord)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _geocode(self, place: str) -> tuple[float, float]:
        """Return (lng, lat) for a place name using ORS geocoding."""
        url = f"{self.GEOCODE_BASE_URL}/geocode/search"
        params = {
            "api_key": settings.ORS_API_KEY,
            "text": place,
            "boundary.country": "US",
            "size": 1,
        }
        try:
            resp = requests.get(url, params=params, timeout=self.TIMEOUT)
        except requests.RequestException as exc:
            raise ORSError(f"Network error contacting ORS geocoding: {exc}")

        if resp.status_code == 429:
            raise ORSRateLimitError()
        if not resp.ok:
            raise ORSError(
                f"ORS geocoding error for '{place}': {resp.status_code} {resp.text[:200]}",
                status_code=502,
            )

        data = resp.json()
        features = data.get("features", [])
        if not features:
            raise ORSError(
                f"Could not geocode location '{place}'. "
                "Make sure it is a valid US city/address.",
                status_code=400,
            )

        coords = features[0]["geometry"]["coordinates"]  # [lng, lat]
        logger.debug("Geocoded '%s' → %s", place, coords)
        return coords[0], coords[1]  # (lng, lat)

    def _directions(
        self,
        start_coord: tuple[float, float],
        finish_coord: tuple[float, float],
    ) -> RouteData:
        """Call ORS driving-car directions and return structured RouteData."""
        url = f"{self.DIRECTIONS_BASE_URL}/directions/driving-car/geojson"
        payload = {
            "coordinates": [list(start_coord), list(finish_coord)],
        }
        headers = {
            "Authorization": settings.ORS_API_KEY,
            "Content-Type": "application/json",
        }

        logger.info("Calling ORS directions: %s → %s", start_coord, finish_coord)

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.TIMEOUT)
        except requests.RequestException as exc:
            raise ORSError(f"Network error contacting ORS directions: {exc}")

        if resp.status_code == 429:
            raise ORSRateLimitError()
        if resp.status_code == 404:
            raise ORSError(
                "ORS could not find a driving route between the given locations.",
                status_code=400,
            )
        if not resp.ok:
            raise ORSError(
                f"ORS directions error: {resp.status_code} {resp.text[:300]}",
                status_code=502,
            )

        data = resp.json()
        feature = data["features"][0]
        props = feature["properties"]["summary"]
        geometry = feature["geometry"]          # GeoJSON LineString
        coordinates = geometry["coordinates"]   # [[lng, lat], ...]

        distance_meters = props["distance"]
        distance_miles = distance_meters * 0.000621371

        return RouteData(
            coordinates=coordinates,
            distance_meters=distance_meters,
            distance_miles=distance_miles,
            duration_seconds=props["duration"],
            duration_hours=props["duration"] / 3600,
            geometry=geometry,
        )
