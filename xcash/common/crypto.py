import hashlib
import hmac


def calc_hmac(message: str, key: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_hmac(message: str, key: str, signature: str) -> bool:
    calculated_hmac = calc_hmac(message, key)
    return hmac.compare_digest(signature, calculated_hmac)
