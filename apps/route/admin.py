from django.contrib.gis import admin as gis_admin
from django.contrib import admin

from .models import FuelStation, RouteCache

# GISModelAdmin was added in Django 3.2 (replacing GeoModelAdmin which was removed in 4.0+).
# Support both to stay compatible across environments.
_GISAdminBase = getattr(gis_admin, "GISModelAdmin", None) or getattr(gis_admin, "GeoModelAdmin")


@gis_admin.register(FuelStation)
class FuelStationAdmin(_GISAdminBase):
    list_display = ("opis_id", "name", "city", "state", "min_price", "geocoded")
    list_filter = ("state", "geocoded")
    search_fields = ("name", "city", "address", "opis_id")
    readonly_fields = ("created_at", "updated_at", "geocoded_at", "location")
    ordering = ("state", "min_price")


@admin.register(RouteCache)
class RouteCacheAdmin(admin.ModelAdmin):
    list_display = ("start_location", "finish_location", "hit_count", "created_at")
    search_fields = ("start_location", "finish_location", "cache_key")
    readonly_fields = ("cache_key", "created_at", "updated_at")
    ordering = ("-hit_count",)
