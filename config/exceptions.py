from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger('apps')


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        return response

    logger.exception('Unhandled exception in %s', context.get('view', 'unknown'))
    return Response(
        {'detail': 'An internal server error occurred.'},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
