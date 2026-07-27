"""
End-to-end test of the client tool-calling loop, without a real third-party API.

Stands up a tiny mock "booking system" on 127.0.0.1:9099, creates a
reserve_table ClientTool for the seeded Bella Vista Restaurant client
(requires_confirmation=True), then drives a fake call through the full flow:

  caller asks to book -> tool_call detected -> confirmation read-back ->
  caller confirms -> tool executed against the mock -> natural language reply

Run from the repo root (after `python -m scripts.seed_clients`):
    python -m scripts.seed_test_tool
"""
import os
import sys
import time
import asyncio
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before any app import — the SSRF guard would otherwise reject
# our 127.0.0.1 mock endpoint (get_settings() is cached on first call).
os.environ["ALLOW_PRIVATE_TOOL_URLS"] = "1"

import uvicorn
from fastapi import FastAPI, Request

from app.database import AsyncSessionLocal, engine, Base
from app.llm_service import get_ai_response
from app.security import encrypt_credential
import app.crud as crud
from scripts.seed_clients import RESTAURANT, get_or_create_client

MOCK_PORT = 9099
MOCK_API_KEY = "test-secret-123"

# ── Mock booking endpoint ─────────────────────────────────

mock_app = FastAPI()
received_requests: list = []


@mock_app.post("/reserve")
async def reserve(request: Request):
    body = await request.json()
    received_requests.append({
        "body": body,
        "api_key": request.headers.get("X-API-Key"),
    })
    return {
        "status": "confirmed",
        "reservation_id": "RES-2026-042",
        "details": body,
    }


def start_mock_server() -> None:
    config = uvicorn.Config(mock_app, host="127.0.0.1", port=MOCK_PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if server.started:
            return
        time.sleep(0.1)
    raise RuntimeError("Mock booking server failed to start")


# ── Test fixtures ─────────────────────────────────────────

RESERVE_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "party_size": {"type": "integer", "description": "Number of people in the party"},
        "time": {"type": "string", "description": "Requested reservation time, e.g. '7:00 PM'"},
        "date": {"type": "string", "description": "Requested date; 'today' if not specified"},
        "name": {"type": "string", "description": "Name the reservation is under"},
    },
    "required": ["party_size", "time", "name"],
}


async def ensure_tool(db, client_id: int):
    tool = await crud.get_tool_by_name(db, client_id, "reserve_table")
    if tool:
        return tool
    return await crud.create_client_tool(
        db,
        client_id=client_id,
        name="reserve_table",
        description=(
            "Book a table at the restaurant. Call this when the caller wants to make "
            "a reservation and has provided the party size, time, and their name."
        ),
        parameters_schema=RESERVE_TABLE_SCHEMA,
        endpoint_url=f"http://127.0.0.1:{MOCK_PORT}/reserve",
        http_method="POST",
        auth_type="api_key_header",
        auth_credential=encrypt_credential(MOCK_API_KEY),
        auth_header_name="X-API-Key",
        requires_confirmation=True,
    )


def check(label: str, ok: bool) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


async def main():
    print("=" * 60)
    print("Starting mock booking endpoint on 127.0.0.1:%d ..." % MOCK_PORT)
    start_mock_server()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # additive: new tables only

    results = []
    async with AsyncSessionLocal() as db:
        restaurant = await get_or_create_client(db, RESTAURANT)
        tool = await ensure_tool(db, restaurant.id)
        print(f"Client: {restaurant.name} (id={restaurant.id}); tool: {tool.name} (id={tool.id})")

        call_sid = f"CA_tool_test_{int(time.time())}"
        call = await crud.create_call(
            db, call_sid=call_sid, from_number="+15559998888",
            to_number=restaurant.twilio_number, client_id=restaurant.id,
        )

        history = []

        # ── Turn 1: caller asks to book ──
        turn1 = "I'd like to book a table for 4 tonight at 7pm, my name is Ahmed"
        print(f"\nTurn 1 — caller: {turn1!r}")
        reply1 = await get_ai_response(turn1, restaurant.id, db, history, call_id=call.id)
        print(f"Turn 1 — agent : {reply1!r}")

        pending = await crud.get_pending_tool_call(db, call.id)
        results.append(check("tool_call detected and parked as pending (not executed)", pending is not None))
        if pending:
            args = pending.arguments
            print(f"  pending arguments: {args}")
            results.append(check("arguments captured party size 4", args.get("party_size") == 4))
            results.append(check("arguments captured the name Ahmed", "ahmed" in str(args.get("name", "")).lower()))
        results.append(check("nothing hit the booking API yet", len(received_requests) == 0))

        history += [{"role": "user", "content": turn1}, {"role": "assistant", "content": reply1}]

        # ── Turn 2: caller confirms ──
        turn2 = "Yes, that's correct"
        print(f"\nTurn 2 — caller: {turn2!r}")
        reply2 = await get_ai_response(turn2, restaurant.id, db, history, call_id=call.id)
        print(f"Turn 2 — agent : {reply2!r}")

        pending_after = await crud.get_pending_tool_call(db, call.id)
        results.append(check("pending row cleared after confirmation", pending_after is None))
        results.append(check("booking API was called exactly once", len(received_requests) == 1))
        if received_requests:
            req = received_requests[0]
            print(f"  mock endpoint received: {req['body']}")
            results.append(check("decrypted API key arrived in X-API-Key header", req["api_key"] == MOCK_API_KEY))

        from sqlalchemy.future import select
        from app.models import ToolCallLog
        logs = (await db.execute(
            select(ToolCallLog).where(ToolCallLog.call_id == call.id)
        )).scalars().all()
        executed = [l for l in logs if l.success]
        results.append(check("ToolCallLog has a success row", len(executed) == 1))
        if executed:
            print(f"  log row: success={executed[0].success}, response={executed[0].response}")

    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED — full tool loop works end to end.")
    else:
        print("SOME CHECKS FAILED — see FAIL lines above.")
    print("=" * 60)
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
