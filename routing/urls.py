from django.urls import path
from routing.views import FuelRouteView, fuel_route_cached, map_view

urlpatterns = [
    path('route/', FuelRouteView.as_view(), name='fuel-route'),
    path('map/', map_view, name='route-map'),
    path('api/route/', fuel_route_cached, name='fuel_route_cached'),
]