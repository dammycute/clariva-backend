from rest_framework import status
from rest_framework.exceptions import APIException


class BillingBlocked(APIException):
    """402: the school has to pay before it can use this part of the app."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = 'billing_blocked'

    def __init__(self, code, detail):
        self.detail = {'detail': detail, 'code': code}


class StudentLimitReached(APIException):
    """409: the plan has no room for another student."""

    status_code = status.HTTP_409_CONFLICT
    default_code = 'student_limit'

    def __init__(self, detail):
        self.detail = {'detail': detail, 'code': 'student_limit'}


class PaymentProblem(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'payment_problem'

    def __init__(self, detail, code='payment_problem', status_code=None):
        if status_code:
            self.status_code = status_code
        self.detail = {'detail': detail, 'code': code}
