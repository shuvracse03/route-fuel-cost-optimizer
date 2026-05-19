"""
Unit tests for apps/route/serializers.py

Tests input validation logic — required fields, same-location rejection,
whitespace handling, and max-length constraints.
"""
import pytest

from apps.route.serializers import RouteRequestSerializer


class TestRouteRequestSerializer:
    def _valid_data(self, start="Dallas, TX", finish="Los Angeles, CA"):
        return {"start": start, "finish": finish}

    def test_valid_data_passes(self):
        s = RouteRequestSerializer(data=self._valid_data())
        assert s.is_valid(), s.errors

    def test_missing_start_fails(self):
        s = RouteRequestSerializer(data={"finish": "Los Angeles, CA"})
        assert not s.is_valid()
        assert "start" in s.errors

    def test_missing_finish_fails(self):
        s = RouteRequestSerializer(data={"start": "Dallas, TX"})
        assert not s.is_valid()
        assert "finish" in s.errors

    def test_empty_start_fails(self):
        s = RouteRequestSerializer(data=self._valid_data(start=""))
        assert not s.is_valid()
        assert "start" in s.errors

    def test_empty_finish_fails(self):
        s = RouteRequestSerializer(data=self._valid_data(finish=""))
        assert not s.is_valid()
        assert "finish" in s.errors

    def test_same_location_case_insensitive_fails(self):
        s = RouteRequestSerializer(data={"start": "Dallas, TX", "finish": "dallas, tx"})
        assert not s.is_valid()
        assert "non_field_errors" in s.errors or "__all__" in s.errors or s.errors

    def test_same_location_exact_match_fails(self):
        s = RouteRequestSerializer(data={"start": "Dallas, TX", "finish": "Dallas, TX"})
        assert not s.is_valid()

    def test_whitespace_only_start_fails(self):
        s = RouteRequestSerializer(data=self._valid_data(start="   "))
        assert not s.is_valid()

    def test_start_exceeds_max_length_fails(self):
        long_str = "A" * 256
        s = RouteRequestSerializer(data=self._valid_data(start=long_str))
        assert not s.is_valid()
        assert "start" in s.errors

    def test_whitespace_is_trimmed(self):
        s = RouteRequestSerializer(data={"start": "  Dallas, TX  ", "finish": "  Los Angeles, CA  "})
        assert s.is_valid(), s.errors
        assert s.validated_data["start"] == "Dallas, TX"
        assert s.validated_data["finish"] == "Los Angeles, CA"

    def test_validated_data_contains_both_fields(self):
        s = RouteRequestSerializer(data=self._valid_data())
        s.is_valid()
        assert "start" in s.validated_data
        assert "finish" in s.validated_data
