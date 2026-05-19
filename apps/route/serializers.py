"""
Serializers for the route API.

RouteRequestSerializer  — validates POST body input.
FuelStopSerializer      — serializes a SelectedStop dataclass for output.
FuelSegmentSerializer   — serializes a FuelSegment for the cost breakdown.
"""
from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
        help_text="Start location within the USA (e.g. 'Dallas, TX')",
    )
    finish = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
        help_text="Finish location within the USA (e.g. 'Los Angeles, CA')",
    )

    def validate(self, data):
        if data["start"].lower().strip() == data["finish"].lower().strip():
            raise serializers.ValidationError(
                "start and finish locations must be different."
            )
        return data


class FuelStopSerializer(serializers.Serializer):
    opis_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    miles_from_start = serializers.FloatField()
    miles_from_last_stop = serializers.FloatField()


class FuelSegmentSerializer(serializers.Serializer):
    from_miles = serializers.FloatField()
    to_miles = serializers.FloatField()
    distance_miles = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    gallons = serializers.FloatField()
    cost_usd = serializers.FloatField()
