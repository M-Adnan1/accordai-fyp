"""
Seed two test Client rows (a car rental company and a restaurant) so you can
point two Twilio numbers at them and manually test multi-tenant isolation.

Also uploads a same-named file ("faq.txt") to both clients with different
content, ingests it the same way /documents/upload does, and then runs a
scoped retrieve_context() query per client to prove:
  - the files land in separate DOCUMENTS_DIR/{client_id}/ subfolders
    (no overwrite), and
  - each client's retrieval only ever surfaces its own chunks
    (no cross-client leakage in Chroma).

Run from the repo root:
    python -m scripts.seed_clients
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.future import select
from app.database import AsyncSessionLocal, engine, Base
from app.models import Client
from app.config import get_settings
from app.document_loader import chunk_text
from app.rag_service import ingest_documents, retrieve_context

settings = get_settings()

CAR_RENTAL = {
    "name": "Sunshine Car Rentals",
    "twilio_number": "+13526236826",
    "system_prompt": (
        "You are a helpful customer service assistant for Sunshine Car Rentals, "
        "a car rental company. Help customers with reservations, vehicle "
        "availability, pricing, and rental policies. Keep responses brief and "
        "conversational (1-3 sentences). Be friendly and professional."
    ),
    "greeting": "Hello! Thanks for calling Sunshine Car Rentals. How can I help you with your rental today?",
    "voice": "Polly.Joanna",
}

RESTAURANT = {
    "name": "Bella Vista Restaurant",
    "twilio_number": "+15550002222",
    "system_prompt": (
        "You are a helpful customer service assistant for Bella Vista Restaurant. "
        "Help customers with reservations, menu questions, hours, and restaurant "
        "policies. Keep responses brief and conversational (1-3 sentences). "
        "Be friendly and professional."
    ),
    "greeting": "Hello! Thanks for calling Bella Vista Restaurant. How can I help you today?",
    "voice": "Polly.Matthew",
}

# Both clients upload a file with the SAME name — this is exactly the
# collision scenario that used to overwrite files and delete the wrong
# client's Chroma chunks.
SHARED_FILENAME = "faq.txt"

CAR_RENTAL_FAQ = (
    "Q: What is the minimum age to rent a car? A: You must be at least 21 years "
    "old with a valid driver's license. Q: Do you offer insurance? A: Yes, we "
    "offer collision damage waiver and liability insurance add-ons. Q: What is "
    "your cancellation policy? A: Free cancellation up to 24 hours before pickup."
)

RESTAURANT_FAQ = (
    "Q: Do you take reservations? A: Yes, we accept reservations by phone or "
    "online up to 30 days in advance. Q: Do you have vegetarian options? A: Yes, "
    "our menu includes a dedicated vegetarian and vegan section. Q: What are "
    "your hours? A: We're open Tuesday through Sunday, 11am to 10pm."
)


async def get_or_create_client(db, data: dict) -> Client:
    result = await db.execute(select(Client).where(Client.twilio_number == data["twilio_number"]))
    existing = result.scalar_one_or_none()
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return existing

    client = Client(**data, is_active=True)
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


def upload_faq_for_client(client: Client, default_content: str) -> None:
    """Mirrors what POST /documents/upload does, without going over HTTP.

    Prefers the FAQ already sitting on disk at DOCUMENTS_DIR/{client_id}/faq.txt
    so a hand-edited knowledge base is re-ingested exactly as written. Only when
    no file exists yet (a fresh setup) do we fall back to the built-in default
    text and write it out.
    """
    docs_path = Path(settings.DOCUMENTS_DIR) / str(client.id)
    docs_path.mkdir(parents=True, exist_ok=True)
    file_path = docs_path / SHARED_FILENAME

    if file_path.exists():
        content = file_path.read_text(encoding="utf-8")
        print(f"  Using existing on-disk FAQ for '{client.name}' ({len(content)} chars)")
    else:
        content = default_content
        file_path.write_text(content, encoding="utf-8")
        print(f"  Wrote default FAQ for '{client.name}' ({len(content)} chars)")

    chunks = chunk_text(content)
    documents = [
        {
            "content": chunk,
            "metadata": {
                "source": SHARED_FILENAME,
                "chunk_index": i,
                "file_type": ".txt",
                "client_id": client.id,
            },
        }
        for i, chunk in enumerate(chunks)
    ]
    ingested = ingest_documents(documents)
    print(f"  Ingested {ingested} chunk(s) for '{client.name}' -> {file_path}")


def check_isolation(client: Client, expected_snippet: str, forbidden_snippet: str) -> bool:
    results = retrieve_context(
        f"Tell me about {client.name}", client_id=client.id, top_k=5, threshold=0.0
    )
    combined = " ".join(r["content"] for r in results)
    has_expected = expected_snippet.lower() in combined.lower()
    has_forbidden = forbidden_snippet.lower() in combined.lower()
    ok = has_expected and not has_forbidden
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] '{client.name}' retrieval contains own content: {has_expected}, "
          f"contains other client's content: {has_forbidden}")
    return ok


async def main():
    print("=" * 60)
    print("Resetting dev schema (drop_all + create_all)...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("Schema reset complete.")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        print("Seeding clients...")
        car_rental = await get_or_create_client(db, CAR_RENTAL)
        restaurant = await get_or_create_client(db, RESTAURANT)
        print(f"  {car_rental.name}: id={car_rental.id}, twilio_number={car_rental.twilio_number}")
        print(f"  {restaurant.name}: id={restaurant.id}, twilio_number={restaurant.twilio_number}")

        print("\nUploading same-named 'faq.txt' to both clients...")
        upload_faq_for_client(car_rental, CAR_RENTAL_FAQ)
        upload_faq_for_client(restaurant, RESTAURANT_FAQ)

        car_rental_path = Path(settings.DOCUMENTS_DIR) / str(car_rental.id) / SHARED_FILENAME
        restaurant_path = Path(settings.DOCUMENTS_DIR) / str(restaurant.id) / SHARED_FILENAME
        # Prove the two same-named files landed in separate folders without
        # clobbering each other: both exist, both non-empty, and their contents
        # differ. (We no longer compare against the hardcoded seed text, since
        # each client's FAQ is now read from disk.)
        car_rental_text = car_rental_path.read_text(encoding="utf-8") if car_rental_path.exists() else ""
        restaurant_text = restaurant_path.read_text(encoding="utf-8") if restaurant_path.exists() else ""
        both_exist_separately = (
            car_rental_path.exists()
            and restaurant_path.exists()
            and car_rental_text.strip() != ""
            and restaurant_text.strip() != ""
            and car_rental_text != restaurant_text
        )
        print(f"  Files preserved separately on disk: {'PASS' if both_exist_separately else 'FAIL'}")

        print("\nVerifying retrieval isolation...")
        car_ok = check_isolation(car_rental, "21 years", "vegetarian")
        restaurant_ok = check_isolation(restaurant, "reservations by phone", "collision damage")

        print("\n" + "=" * 60)
        if both_exist_separately and car_ok and restaurant_ok:
            print("Isolation check PASSED — same-named uploads no longer collide.")
        else:
            print("Isolation check FAILED — investigate before testing with real Twilio numbers.")
        print("=" * 60)
        print("\nPoint two Twilio numbers at this backend's /voice/incoming to test manually:")
        print(f"  {car_rental.name}: {car_rental.twilio_number}")
        print(f"  {restaurant.name}: {restaurant.twilio_number}")


if __name__ == "__main__":
    asyncio.run(main())
