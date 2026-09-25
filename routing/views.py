from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from routing.services.fuel_optimizer import FuelOptimizerService
from routing.services.mapbox_service import MapboxService
from django.shortcuts import render 

def map_view(request): return render(request, 'routing/route_map.html')

class FuelRouteView(APIView):
    """API Endpoint to compute optimal fuel stops and route geometry between two US locations."""

    def get(self, request):
        start_location = request.query_params.get('start')
        finish_location = request.query_params.get('finish')

        if not start_location or not finish_location:
            return Response(
                {
                    'error': "Both 'start' and 'finish' query parameters are required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            mapbox_service = MapboxService()
            optimizer_service = FuelOptimizerService()

            # 1. Geocode origin and destination
            start_coords = mapbox_service.geocode(start_location)
            finish_coords = mapbox_service.geocode(finish_location)

            # 2. Fetch directions and route geometry from Mapbox
            route_data = mapbox_service.get_directions(start_coords, finish_coords)
            coords = route_data['geometry']['coordinates']

            # 3. Perform spatial filtering and fuel stop optimization
            candidate_stations, total_miles = (
                optimizer_service.filter_candidate_stations(coords)
            )
            optimization_plan = optimizer_service.optimize_fuel_stops(
                candidate_stations, total_miles
            )

            # 4. Construct final response format
            response_payload = {
                'start_location': start_location,
                'finish_location': finish_location,
                'total_distance_miles': optimization_plan['total_route_miles'],
                'total_fuel_gallons': optimization_plan['total_gallons'],
                'total_fuel_cost': optimization_plan['total_fuel_cost'],
                'number_of_fuel_stops': len(optimization_plan['fuel_stops']),
                'fuel_stops': optimization_plan['fuel_stops'],
                'route_geometry': route_data['geometry'],
            }
            return Response(response_payload, status=status.HTTP_200_OK)

        except ValueError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {'error': f'An unexpected error occurred: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
