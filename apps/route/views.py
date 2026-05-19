"""
Route API views.

POST /api/v1/route/
  → validate input
  → check cache (Redis → PostgreSQL)
  → on MISS: call ORS, build mile markers, select fuel stops, calculate cost
  → persist to cache
  → return JSON response
"""
import logging
from datetime import timezone as dt_timezone
from datetime import datetime

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.utils import make_cache_key, normalise_location
from apps.core.request_context import set_data_source, DataSource
from apps.route.serializers import (
    FuelSegmentSerializer,
    FuelStopSerializer,
    RouteRequestSerializer,
)
from apps.route.services.cache_service import get_cached_route, save_route_to_cache
from apps.route.services.cost_calculator import calculate_fuel_cost
from apps.route.services.fuel_selector import select_fuel_stops_dp
from apps.route.services.ors_client import ORSClient, ORSError, ORSRateLimitError
from apps.route.services.route_builder import build_mile_markers

logger = logging.getLogger(__name__)

_ors_client = ORSClient()


class RouteView(APIView):
    """
    POST /api/v1/route/

    Request body:
        { "start": "Dallas, TX", "finish": "Los Angeles, CA" }

    Response:
        Full route with fuel stops, cost summary, and GeoJSON geometry.
    """

    def post(self, request: Request) -> Response:
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        start = normalise_location(serializer.validated_data["start"])
        finish = normalise_location(serializer.validated_data["finish"])
        cache_key = make_cache_key(start, finish)

        # ── Layer 1 & 2: cache lookup ──────────────────────────────────────
        cached = get_cached_route(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        # ── Full computation ───────────────────────────────────────────────
        try:
            route_data = _ors_client.get_route(start, finish)
        except ORSRateLimitError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "60"},
            )
        except ORSError as exc:
            return Response(
                {"error": str(exc)},
                status=exc.status_code,
            )

        # Mark that we used ORS API for this request
        set_data_source(DataSource.ORS_API)

        # Build mile markers from GeoJSON coordinates
        mile_markers = build_mile_markers(route_data["coordinates"])

        # DP-based globally optimal fuel stop selection (single DB query + O(n²) DP)
        fuel_stops = select_fuel_stops_dp(mile_markers, route_data["distance_miles"])

        # Calculate fuel cost
        cost_summary = calculate_fuel_cost(fuel_stops, route_data["distance_miles"])

        # ── Build response payload ─────────────────────────────────────────
        response_payload = _build_response(
            start=start,
            finish=finish,
            route_data=route_data,
            fuel_stops=fuel_stops,
            cost_summary=cost_summary,
            cached=False,
        )

        # ── Persist to cache ───────────────────────────────────────────────
        save_route_to_cache(cache_key, start, finish, response_payload)

        return Response(response_payload, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

def _build_response(start, finish, route_data, fuel_stops, cost_summary, cached: bool) -> dict:
    stops_data = []
    for stop in fuel_stops:
        stops_data.append({
            "opis_id": stop.opis_id,
            "name": stop.name,
            "address": stop.address,
            "city": stop.city,
            "state": stop.state,
            "lat": round(stop.lat, 6),
            "lng": round(stop.lng, 6),
            "price_per_gallon": stop.price_per_gallon,
            "miles_from_start": round(stop.miles_from_start, 1),
            "miles_from_last_stop": round(stop.miles_from_last_stop, 1),
        })

    segments_data = []
    for seg in cost_summary.segments:
        segments_data.append({
            "from_miles": seg.from_miles,
            "to_miles": seg.to_miles,
            "distance_miles": seg.distance_miles,
            "price_per_gallon": seg.price_per_gallon,
            "gallons": seg.gallons,
            "cost_usd": seg.cost_usd,
        })

    return {
        "route": {
            "start": start,
            "finish": finish,
            "total_distance_miles": round(route_data["distance_miles"], 1),
            "duration_hours": round(route_data["duration_hours"], 2),
            "geometry": route_data["geometry"],
        },
        "fuel_stops": stops_data,
        "fuel_summary": {
            "total_gallons": cost_summary.total_gallons,
            "total_cost_usd": cost_summary.total_cost_usd,
            "avg_price_per_gallon": cost_summary.avg_price_per_gallon,
            "num_stops": cost_summary.num_stops,
            "cost_breakdown": segments_data,
        },
        "meta": {
            "cached": cached,
            "computed_at": datetime.now(dt_timezone.utc).isoformat(),
            "ors_calls_made": 0 if cached else 1,
        },
    }
