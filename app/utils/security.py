from __future__ import annotations

import secrets

from passlib.hash import bcrypt

ALLOWED_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def generate_password(length: int = 10) -> str:
    return "".join(secrets.choice(ALLOWED_CHARS) for _ in range(length))


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.verify(password, password_hash)
