from django.urls import path
from routing.views import FuelRouteView, map_view

urlpatterns = [
    path('route/', FuelRouteView.as_view(), name='fuel-route'),
    path('map/', map_view, name='route-map'),
]