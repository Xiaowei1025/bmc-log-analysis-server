import base64
import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return base64.b64encode(salt + derived).decode()


def verify_password(password: str, encoded: str) -> bool:
    raw = base64.b64decode(encoded.encode())
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), raw[:16], 200_000)
    return hmac.compare_digest(raw[16:], candidate)
