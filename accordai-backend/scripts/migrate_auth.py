"""Development migration + seed for JWT auth (run once, idempotent).

    python scripts/migrate_auth.py

Does three things:
1. Creates any missing tables (notably the new `users` table).
2. ALTER TABLE clients: drops NOT NULL on twilio_number — signup-created
   tenants have no number until one is provisioned. This is the only ALTER;
   everything else is additive and handled by create_all.
3. Seeds demo accounts for the two pre-auth demo tenants so existing data
   stays reachable, plus one 'member' account to demonstrate RBAC:

       admin@sunshine.demo   / SunshineDemo1  (admin,  Sunshine Car Rentals)
       member@sunshine.demo  / SunshineDemo1  (member, Sunshine Car Rentals)
       admin@bellavista.demo / BellaDemo1     (admin,  Bella Vista Restaurant)

   Override passwords via SEED_SUNSHINE_PASSWORD / SEED_BELLA_PASSWORD env
   vars. DEV/DEMO ONLY — never run against a production database; these
   credentials exist solely in this script, not in application logic.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import engine, Base, AsyncSessionLocal
import app.models  # noqa: F401 — register all models on Base
from app.security import hash_password
import app.crud as crud

SUNSHINE_PW = os.environ.get("SEED_SUNSHINE_PASSWORD", "SunshineDemo1")
BELLA_PW = os.environ.get("SEED_BELLA_PASSWORD", "BellaDemo1")

SEED_USERS = [
    # (client_id, email, password, full_name, role)
    (1, "admin@sunshine.demo", SUNSHINE_PW, "Sunshine Admin", "admin"),
    (1, "member@sunshine.demo", SUNSHINE_PW, "Sunshine Member", "member"),
    (2, "admin@bellavista.demo", BELLA_PW, "Bella Vista Admin", "admin"),
]


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("Tables ensured (users table created if missing).")

        await conn.execute(text(
            "ALTER TABLE clients ALTER COLUMN twilio_number DROP NOT NULL"
        ))
        print("clients.twilio_number is now nullable.")

    async with AsyncSessionLocal() as db:
        for client_id, email, password, full_name, role in SEED_USERS:
            if await crud.get_user_by_email(db, email):
                print(f"  skip {email} (already exists)")
                continue
            client = await crud.get_client(db, client_id)
            if client is None:
                print(f"  skip {email} (client {client_id} not found — run seed_clients.py first)")
                continue
            await crud.create_user(
                db, client_id=client_id, email=email,
                password_hash=hash_password(password),
                full_name=full_name, role=role,
            )
            print(f"  seeded {email} ({role}, client {client_id})")

    await engine.dispose()
    print("Done.")
if __name__ == "__main__":
    asyncio.run(main())