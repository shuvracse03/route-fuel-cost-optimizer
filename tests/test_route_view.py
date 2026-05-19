"""
Integration & end-to-end tests for POST /api/v1/route/

Uses pytest-django's APIClient with:
  - Mocked ORS calls (no real HTTP requests)
  - Mocked DB station queries (no real PostgreSQL needed)
  - Mocked cache (Redis not required)

Tests cover:
  - 400 validation errors
  - Cache HIT path (Redis + DB)
  - Cache MISS → full compute path
  - ORS error propagation
  - Response shape and required fields
"""
import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def route_url():
    return "/api/v1/route/"


MOCK_ORS_ROUTE = {
    "coordinates": [
        [-96.796, 32.776],
        [-100.0,  32.9],
        [-106.489, 31.759],
        [-110.974, 32.253],
        [-118.243, 34.052],
    ],
    "distance_meters": 2300000,
    "distance_miles": 1429.3,
    "duration_seconds": 72000,
    "duration_hours": 20.0,
    "geometry": {
        "type": "LineString",
        "coordinates": [
            [-96.796, 32.776],
            [-118.243, 34.052],
        ],
    },
}

MOCK_STATIONS = [
    MagicMock(
        opis_id=1,
        name="Cheap Stop TX",
        address="I-10 Exit 200",
        city="Somewhere",
        state="TX",
        lat=32.9,
        lng=-100.0,
        min_price=2.85,
        geocoded=True,
    ),
    MagicMock(
        opis_id=2,
        name="Cheap Stop AZ",
        address="I-10 Exit 100",
        city="Tucson",
        state="AZ",
        lat=32.253,
        lng=-110.974,
        min_price=2.95,
        geocoded=True,
    ),
]


def _make_cache_key(start: str, finish: str) -> str:
    normalised = f"{start.strip().lower()}|{finish.strip().lower()}"
    return hashlib.sha256(normalised.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Validation tests (no mocking needed)
# ---------------------------------------------------------------------------

class TestRouteViewValidation:
    def test_missing_start_returns_400(self, client, route_url):
        resp = client.post(route_url, {"finish": "Los Angeles, CA"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "errors" in resp.data

    def test_missing_finish_returns_400(self, client, route_url):
        resp = client.post(route_url, {"start": "Dallas, TX"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_body_returns_400(self, client, route_url):
        resp = client.post(route_url, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_same_start_finish_returns_400(self, client, route_url):
        resp = client.post(
            route_url,
            {"start": "Dallas, TX", "finish": "Dallas, TX"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_method_not_allowed(self, client, route_url):
        resp = client.get(route_url)
        assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Cache HIT tests
# ---------------------------------------------------------------------------

class TestRouteViewCacheHit:
    def test_redis_cache_hit_returns_200(self, client, route_url):
        cached_response = {
            "route": {"start": "Dallas, TX", "finish": "Los Angeles, CA",
                      "total_distance_miles": 1429.3, "duration_hours": 20.0,
                      "geometry": {"type": "LineString", "coordinates": []}},
            "fuel_stops": [],
            "fuel_summary": {"total_gallons": 142.93, "total_cost_usd": 410.0,
                             "avg_price_per_gallon": 2.87, "num_stops": 2,
                             "cost_breakdown": []},
            "meta": {"cached": True, "computed_at": "2024-01-01T00:00:00Z",
                     "ors_calls_made": 0},
        }

        with patch(
            "apps.route.views.get_cached_route",
            return_value=cached_response,
        ):
            resp = client.post(
                route_url,
                {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["meta"]["cached"] is True

    def test_cache_hit_does_not_call_ors(self, client, route_url):
        with patch(
            "apps.route.views.get_cached_route",
            return_value={"meta": {"cached": True}, "route": {}, "fuel_stops": [],
                          "fuel_summary": {}},
        ) as mock_cache, patch(
            "apps.route.views.ORSClient.get_route"
        ) as mock_ors:
            client.post(
                route_url,
                {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                format="json",
            )
            mock_ors.assert_not_called()


# ---------------------------------------------------------------------------
# Cache MISS → full compute path
# ---------------------------------------------------------------------------

class TestRouteViewFullCompute:
    def _run_full_compute(self, client, route_url):
        with patch(
            "apps.route.views.get_cached_route",
            return_value=None,
        ), patch(
            "apps.route.views.ORSClient.get_route",
            return_value=MOCK_ORS_ROUTE,
        ), patch(
            "apps.route.services.fuel_selector.FuelStation.objects.filter"
        ) as mock_filter, patch(
            "apps.route.views.save_route_to_cache"
        ):
            # Chain .filter(...) query — return our mock stations
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter(MOCK_STATIONS))
            mock_qs.__len__ = MagicMock(return_value=len(MOCK_STATIONS))
            mock_filter.return_value = mock_qs

            resp = client.post(
                route_url,
                {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                format="json",
            )
        return resp

    def test_full_compute_returns_200(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        assert resp.status_code == status.HTTP_200_OK

    def test_response_has_route_key(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        assert "route" in resp.data

    def test_response_has_fuel_stops_key(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        assert "fuel_stops" in resp.data

    def test_response_has_fuel_summary_key(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        assert "fuel_summary" in resp.data

    def test_response_has_meta_key(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        assert "meta" in resp.data

    def test_response_not_cached_on_first_call(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        assert resp.data["meta"]["cached"] is False

    def test_route_fields_present(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        route = resp.data["route"]
        assert "start" in route
        assert "finish" in route
        assert "total_distance_miles" in route
        assert "duration_hours" in route
        assert "geometry" in route

    def test_fuel_summary_fields_present(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        summary = resp.data["fuel_summary"]
        assert "total_gallons" in summary
        assert "total_cost_usd" in summary
        assert "avg_price_per_gallon" in summary
        assert "num_stops" in summary
        assert "cost_breakdown" in summary

    def test_route_distance_matches_ors(self, client, route_url):
        resp = self._run_full_compute(client, route_url)
        assert resp.data["route"]["total_distance_miles"] == pytest.approx(1429.3, abs=1.0)

    def test_ors_called_exactly_once_on_cache_miss(self, client, route_url):
        with patch(
            "apps.route.views.get_cached_route",
            return_value=None,
        ), patch(
            "apps.route.views.ORSClient.get_route",
            return_value=MOCK_ORS_ROUTE,
        ) as mock_ors, patch(
            "apps.route.services.fuel_selector.FuelStation.objects.filter"
        ) as mock_filter, patch(
            "apps.route.views.save_route_to_cache"
        ):
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter(MOCK_STATIONS))
            mock_filter.return_value = mock_qs

            client.post(
                route_url,
                {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                format="json",
            )
            mock_ors.assert_called_once()

    def test_result_saved_to_cache_on_compute(self, client, route_url):
        with patch(
            "apps.route.views.get_cached_route",
            return_value=None,
        ), patch(
            "apps.route.views.ORSClient.get_route",
            return_value=MOCK_ORS_ROUTE,
        ), patch(
            "apps.route.services.fuel_selector.FuelStation.objects.filter"
        ) as mock_filter, patch(
            "apps.route.views.save_route_to_cache"
        ) as mock_save:
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter(MOCK_STATIONS))
            mock_filter.return_value = mock_qs

            client.post(
                route_url,
                {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                format="json",
            )
            mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# ORS error propagation
# ---------------------------------------------------------------------------

class TestRouteViewORSErrors:
    def test_ors_error_returns_502(self, client, route_url):
        from apps.route.services.ors_client import ORSError

        with patch(
            "apps.route.views.get_cached_route",
            return_value=None,
        ), patch(
            "apps.route.views.ORSClient.get_route",
            side_effect=ORSError("ORS failed", status_code=502),
        ):
            resp = client.post(
                route_url,
                {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                format="json",
            )
        assert resp.status_code == 502
        assert "error" in resp.data

    def test_ors_bad_location_returns_400(self, client, route_url):
        from apps.route.services.ors_client import ORSError

        with patch(
            "apps.route.views.get_cached_route",
            return_value=None,
        ), patch(
            "apps.route.views.ORSClient.get_route",
            side_effect=ORSError("Cannot geocode location", status_code=400),
        ):
            resp = client.post(
                route_url,
                {"start": "Nonexistent Place XYZ", "finish": "Los Angeles, CA"},
                format="json",
            )
        assert resp.status_code == 400

    def test_ors_rate_limit_returns_503(self, client, route_url):
        from apps.route.services.ors_client import ORSRateLimitError

        with patch(
            "apps.route.views.get_cached_route",
            return_value=None,
        ), patch(
            "apps.route.views.ORSClient.get_route",
            side_effect=ORSRateLimitError(),
        ):
            resp = client.post(
                route_url,
                {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                format="json",
            )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Retry-After" in resp.headers
