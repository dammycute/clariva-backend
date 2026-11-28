import hashlib
import hmac

from django.conf import settings


def hash_value(value: str) -> str:
    """A keyed fingerprint, for finding an encrypted secret. Useless without LOOKUP_HASH_KEY."""
    if not value:
        return ''
    return hmac.new(settings.LOOKUP_HASH_KEY.encode(), value.encode('utf-8'), hashlib.sha256).hexdigest()


def verify_hash(value: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_value(value), hashed or '')
