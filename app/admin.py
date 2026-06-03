"""Admin CLI for managing B2B API keys.

Usage (with the venv active):
    python -m app.admin issue "Acme Corp"     # create a key, prints it ONCE
    python -m app.admin list                  # list issued keys (no secrets)
    python -m app.admin revoke <key_id>       # disable a key

The raw key is shown only at issue time — store it somewhere safe and hand it to
the client. We keep only its hash.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from .auth import generate_key, hash_key
from .db import ApiKey, SessionLocal, init_db


async def issue(client_name: str) -> None:
    raw = generate_key()
    await init_db()
    async with SessionLocal() as db:
        row = ApiKey(
            client_name=client_name,
            key_prefix=raw[:16],
            key_hash=hash_key(raw),
        )
        db.add(row)
        await db.commit()
    print("\n  API key issued — copy it now, it will NOT be shown again:\n")
    print(f"    client : {client_name}")
    print(f"    key_id : {row.id}")
    print(f"    API KEY: {raw}\n")


async def list_keys() -> None:
    await init_db()
    async with SessionLocal() as db:
        rows = (await db.execute(select(ApiKey))).scalars().all()
    if not rows:
        print("(no keys issued)")
        return
    for r in rows:
        state = "active" if r.active else "revoked"
        print(f"{r.id}  {r.client_name:<24} {r.key_prefix}…  [{state}]")


async def revoke(key_id: str) -> None:
    await init_db()
    async with SessionLocal() as db:
        row = await db.get(ApiKey, key_id)
        if not row:
            print(f"no key with id {key_id}")
            return
        row.active = False
        await db.commit()
    print(f"revoked {key_id}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, *rest = args
    if cmd == "issue" and rest:
        asyncio.run(issue(" ".join(rest)))
    elif cmd == "list":
        asyncio.run(list_keys())
    elif cmd == "revoke" and rest:
        asyncio.run(revoke(rest[0]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
