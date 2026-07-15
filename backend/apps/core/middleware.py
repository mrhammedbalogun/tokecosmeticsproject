"""Attach request.country for every request based on the X-Country header."""
from apps.core.country_context import resolve_country


class CountryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.country = resolve_country(request.headers.get("X-Country"))
        return self.get_response(request)
