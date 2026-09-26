import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from routing.services.fuel_optimizer import FuelOptimizerService
from routing.services.mapbox_service import MapboxService
from django.shortcuts import render
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def map_view(request):
    """Render map interface with Mapbox token."""
    context = {
        'mapbox_token': getattr(settings, 'MAPBOX_ACCESS_TOKEN', ''),
    }
    return render(request, 'routing/route_map.html', context)


class FuelRouteView(APIView):
    """
    API endpoint to compute optimal fuel stops and route geometry between two US locations.
    
    Query Parameters:
        start (str): Starting location name/address
        finish (str): Destination location name/address
        
    Returns:
        200: Complete route with fuel stops and optimization metrics
        400: Missing/invalid parameters or geocoding error
        500: Unexpected server error
    """

    def get(self, request):
        # Extract and validate query parameters
        start_location = request.query_params.get('start', '').strip()
        finish_location = request.query_params.get('finish', '').strip()

        if not start_location or not finish_location:
            return Response(
                {
                    'status': 'error',
                    'message': "Both 'start' and 'finish' query parameters are required.",
                    'data': None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Initialize services
            mapbox_service = MapboxService()
            optimizer_service = FuelOptimizerService()

            # Step 1: Geocode locations
            logger.info(f"Geocoding: {start_location} -> {finish_location}")
            start_coords = mapbox_service.geocode(start_location)
            finish_coords = mapbox_service.geocode(finish_location)

            # Step 2: Get route geometry from Mapbox
            logger.info("Fetching directions from Mapbox")
            route_data = mapbox_service.get_directions(start_coords, finish_coords)
            coords = route_data['geometry']['coordinates']

            # Step 3: Optimize fuel stops using complete pipeline
            logger.info("Running fuel optimization algorithm")
            optimization_result = optimizer_service.plan_route(coords)

            # Step 4: Check optimization status
            if optimization_result['status'] == 'error':
                # Route is infeasible
                logger.warning(f"Route optimization failed: {optimization_result['message']}")
                return Response(
                    {
                        'status': 'error',
                        'message': optimization_result['message'],
                        'data': {
                            'start_location': start_location,
                            'finish_location': finish_location,
                            'total_distance_miles': optimization_result['total_route_miles'],
                            'max_truck_range_miles': optimization_result['max_range_miles'],                                                
                            'route_geometry': route_data['geometry'],
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Step 5: Build successful response with all metrics
            response_payload = {
                'status': 'success',
                'message': optimization_result['message'],
                'data': {
                    # Location info
                    'start_location': start_location,
                    'finish_location': finish_location,
                    
                    # Route metrics
                    'total_distance_miles': optimization_result['total_route_miles'],
                    'max_truck_range_miles': optimization_result['max_range_miles'],
                    
                    # Fuel metrics
                    'total_fuel_gallons': optimization_result['total_gallons'],
                    'total_fuel_cost': optimization_result['total_fuel_cost'],
                    'avg_price_per_gallon': optimization_result.get('avg_price_per_gallon', 0.0),
                    'tank_capacity_gallons': 50.0,
                    
                    # Stops info
                    'number_of_fuel_stops': len(optimization_result['fuel_stops']),
                    'candidate_stations_found': optimization_result['candidate_stations_found'],
                    'fuel_stops': self._format_fuel_stops(optimization_result['fuel_stops']),
                    
                    # Route geometry for mapping
                    'route_geometry': route_data['geometry'],
                },
            }

            logger.info(
                f"Route optimization successful: {optimization_result['total_route_miles']} miles, "
                f"{len(optimization_result['fuel_stops'])} stops"
            )

            return Response(response_payload, status=status.HTTP_200_OK)

        except ValueError as ve:
            logger.error(f"Validation error: {str(ve)}")
            return Response(
                {
                    'status': 'error',
                    'message': f'Invalid location or route parameters: {str(ve)}',
                    'data': None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception(f"Unexpected error in fuel route optimization")
            return Response(
                {
                    'status': 'error',
                    'message': 'An unexpected error occurred during route optimization.',
                    'data': None,
                    'debug': str(e) if settings.DEBUG else None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @staticmethod
    def _format_fuel_stops(fuel_stops):
        """
        Format fuel stops for API response with only relevant fields.
        
        Args:
            fuel_stops: List of fuel stop dictionaries from optimizer
            
        Returns:
            Formatted list of fuel stops with essential information
        """
        formatted_stops = []
        for i, stop in enumerate(fuel_stops, 1):
            formatted_stops.append({
                'stop_number': i,
                'name': stop['name'],
                'address': stop['address'],
                'city': stop['city'],
                'state': stop['state'],
                'price_per_gallon': stop['price'],
                'distance_from_start_miles': stop['dist_from_start'],
                'off_route_distance_miles': stop['off_route_miles'],
                'distance_from_previous_miles': stop['distance_from_previous'],
                'gallons_purchased': stop['gallons_purchased'],
                'cost_dollars': stop['cost'],
                'coordinates': {
                    'latitude': stop['latitude'],
                    'longitude': stop['longitude'],
                },
            })
        return formatted_stops


# Optional: Fast route optimization endpoint (cached for 1 hour)
@api_view(['GET'])
def fuel_route_cached(request):
    """
    Cached version of FuelRouteView for frequently requested routes.
    Cache key includes start and finish locations.
    """
    start_location = request.query_params.get('start', '').strip()
    finish_location = request.query_params.get('finish', '').strip()

    if not start_location or not finish_location:
        return Response(
            {
                'status': 'error',
                'message': "Both 'start' and 'finish' query parameters are required.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Create cache key from locations
    cache_key = f"fuel_route:{start_location}:{finish_location}"
    
    # Check cache first
    cached_result = cache.get(cache_key)
    if cached_result:
        cached_result['cached'] = True
        return Response(cached_result, status=status.HTTP_200_OK)

    # If not cached, compute using FuelRouteView
    view = FuelRouteView.as_view()
    response = view(request)
    
    # Cache successful results for 1 hour
    if response.status_code == status.HTTP_200_OK and response.data.get('status') == 'success':
        response.data['cached'] = False
        cache.set(cache_key, response.data, timeout=3600)  # 1 hour
    
    return response