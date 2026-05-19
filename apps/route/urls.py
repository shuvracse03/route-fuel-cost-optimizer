from django.urls import path
from apps.route.views import RouteView

app_name = "route"

urlpatterns = [
    path("route/", RouteView.as_view(), name="route"),
]
