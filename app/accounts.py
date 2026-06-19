from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Company
from .deps import get_db

_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ROUNDS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ROUNDS)
    return secrets.compare_digest(dk.hex(), expected)


async def current_company(request: Request, db: AsyncSession = Depends(get_db)) -> Company | None:
    cid = request.session.get("company_id")
    if not cid:
        return None
    return await db.get(Company, cid)
