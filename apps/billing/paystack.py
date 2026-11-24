"""Paystack's HTTP API and webhook signatures, with no extra package.

Everything Paystack takes or gives is JSON over HTTPS. The webhook is signed twice:
the current `Paystack-Signature` header (a `whsec_` signing secret and a timestamp)
and, while a secret key exists, the older `x-paystack-signature` (the secret key
alone). The first is trusted when present; the second is the fallback.
"""
import hashlib
import hmac
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

BASE_URL = 'https://api.paystack.co'
SIGNATURE_TOLERANCE = 300          # seconds; older deliveries are refused
TIMEOUT = 20


class PaystackError(Exception):
    """Paystack refused, was unreachable, or is not configured."""


def _request(method, path, payload=None):
    secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
    if not secret:
        raise PaystackError('Paystack is not configured on this server.')
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        f'{BASE_URL}{path}', data=body, method=method,
        headers={
            'Authorization': f'Bearer {secret}',
            'Content-Type': 'application/json',
            'User-Agent': 'clariva-backend',
        },
    )
    try:
        with urlopen(req, timeout=TIMEOUT) as res:
            data = json.loads(res.read().decode() or '{}')
    except HTTPError as exc:
        detail = ''
        try:
            detail = json.loads(exc.read().decode()).get('message', '')
        except Exception:
            pass
        raise PaystackError(detail or f'Paystack returned {exc.code}.') from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise PaystackError('Paystack could not be reached.') from exc
    if not data.get('status'):
        raise PaystackError(data.get('message') or 'Paystack refused the request.')
    return data.get('data') or {}


def initialize(email, amount_kobo, reference, callback_url='', metadata=None):
    """Start a payment. `amount_kobo` comes from the database, never from the browser."""
    payload = {
        'email': email,
        'amount': int(amount_kobo),
        'reference': reference,
        'currency': 'NGN',
        # No subaccount is involved, so the merchant account already bears the fee.
        # `bearer` is deliberately left out.
    }
    if callback_url:
        payload['callback_url'] = callback_url
    if metadata:
        payload['metadata'] = metadata
    return _request('POST', '/transaction/initialize', payload)


def verify(reference):
    """What Paystack says actually happened. The source of truth for the amount."""
    return _request('GET', f'/transaction/verify/{reference}')


def _parse_signature_header(value):
    """`t=<unix>,v1=<kid>:<hex>[,v1=<kid>:<hex>]` into (timestamp, [hex, ...])."""
    timestamp, signatures = None, []
    for part in (value or '').split(','):
        key, _, val = part.partition('=')
        key, val = key.strip(), val.strip()
        if key == 't':
            timestamp = val
        elif key == 'v1':
            signatures.append(val.split(':', 1)[-1].strip().lower())
    return timestamp, signatures


def _digest(secret, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha512).hexdigest()


def signature_ok(raw_body: bytes, meta, now=None) -> bool:
    """Check a delivery's signature. `meta` is Django's request.META."""
    header = meta.get('HTTP_PAYSTACK_SIGNATURE', '')
    legacy = meta.get('HTTP_X_PAYSTACK_SIGNATURE', '')
    signing_secret = getattr(settings, 'PAYSTACK_SIGNING_SECRET', '')
    secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')

    if header and signing_secret:
        timestamp, signatures = _parse_signature_header(header)
        if not timestamp or not signatures:
            return False
        try:
            sent_at = int(timestamp)
        except ValueError:
            return False
        current = (now or timezone.now()).timestamp()
        if abs(current - sent_at) > SIGNATURE_TOLERANCE:
            return False
        expected = _digest(signing_secret, timestamp.encode() + b'.' + raw_body)
        return any(hmac.compare_digest(expected, sig) for sig in signatures)

    if legacy and secret_key:
        return hmac.compare_digest(_digest(secret_key, raw_body), legacy.strip().lower())
    return False


def signing_timestamp(secret, raw_body, at=None):
    """A correct header for tests and local runs: `t=...,v1=...`."""
    timestamp = str(int((at or timezone.now()).timestamp()))
    value = _digest(secret, timestamp.encode() + b'.' + raw_body)
    return f't={timestamp},v1={value}'


def legacy_signature(secret, raw_body):
    """The deprecated `x-paystack-signature` value."""
    return _digest(secret, raw_body)


def clock():
    return time.time()
