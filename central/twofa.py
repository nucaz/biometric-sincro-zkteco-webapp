"""
TOTP-based 2FA (Google Authenticator / Microsoft Authenticator / Authy
compatible) plus "trusted device" cookies so a user who always logs in
from the same PC isn't asked for a code every time.
"""
import base64
import hashlib
import io
import secrets
from datetime import datetime, timedelta

import pyotp
import qrcode

ISSUER_NAME = "Asistencia RRHH"
TRUSTED_DEVICE_COOKIE = "trusted_device"
TRUSTED_DEVICE_DAYS = 30


def generate_secret():
    return pyotp.random_base32()


def qr_data_uri(secret, username):
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER_NAME)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_code(secret, code):
    if not secret or not code:
        return False
    return pyotp.totp.TOTP(secret).verify(code.strip(), valid_window=1)


def new_trusted_device_token():
    """Returns (raw_token_for_cookie, hash_for_db). Only the hash is ever
    stored -- same principle as a password."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def trusted_device_expiry():
    # Naive UTC on purpose -- matches how every other *_at column in this
    # app is stored/compared (SQLite doesn't reliably round-trip tzinfo).
    return datetime.utcnow() + timedelta(days=TRUSTED_DEVICE_DAYS)
