import hashlib

SALT = b'clariva-field-salt-2025'


def hash_value(value: str) -> str:
    if not value:
        return ''
    return hashlib.sha256(SALT + value.encode('utf-8')).hexdigest()


def verify_hash(value: str, hashed: str) -> bool:
    return hash_value(value) == hashed
