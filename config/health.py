from config.views import health_check


class HealthCheckMiddleware:
    """Answer /health/ before anything else looks at the request.

    A load balancer checks the server by its private IP address over plain HTTP. Django
    would refuse that host name, or redirect it to HTTPS, and the server would be marked
    unhealthy. This page reveals only whether the app and database answer.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/health/':
            return health_check(request)
        return self.get_response(request)
