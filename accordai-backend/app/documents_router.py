import os
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.deps import get_current_user, require_admin
from app.document_loader import load_pdf_file, load_text_file, chunk_text
from app.models import User
from app.rag_service import ingest_documents, get_chroma_collection
import logging

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


def _client_docs_path(client_id: int) -> Path:
    return Path(settings.DOCUMENTS_DIR) / str(client_id)


# Tenant context comes from the authenticated user; mutations are admin-only.
@router.post("/upload")
async def upload_document(file: UploadFile = File(...), user: User = Depends(require_admin)):
    """Upload and ingest a document into the tenant's knowledge base."""
    client_id = user.client_id
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file_ext}'. Allowed: {ALLOWED_EXTENSIONS}"
        )

    # Save file under a per-client subfolder so two clients uploading a
    # same-named file don't overwrite each other's file on disk.
    docs_path = _client_docs_path(client_id)
    docs_path.mkdir(parents=True, exist_ok=True)
    file_path = docs_path / file.filename

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    logger.info(f"Saved uploaded file: {file.filename} (client_id={client_id})")

    # Load & chunk
    try:
        if file_ext == ".pdf":
            text = load_pdf_file(file_path)
        else:
            text = load_text_file(file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")

    chunks = chunk_text(text)
    documents = [
        {
            "content": chunk,
            "metadata": {
                "source": file.filename,
                "chunk_index": i,
                "file_type": file_ext,
                "client_id": client_id
            }
        }
        for i, chunk in enumerate(chunks)
    ]

    count = ingest_documents(documents)

    return JSONResponse({
        "message": "Document ingested successfully.",
        "filename": file.filename,
        "chunks_ingested": count
    })


@router.get("/list")
async def list_documents(user: User = Depends(get_current_user)):
    """List all documents currently in the tenant's knowledge base."""
    client_id = user.client_id
    docs_path = _client_docs_path(client_id)
    docs_path.mkdir(parents=True, exist_ok=True)

    files = [
        f.name for f in docs_path.iterdir()
        if f.suffix.lower() in ALLOWED_EXTENSIONS
    ]
    collection = get_chroma_collection()
    client_chunks = collection.get(where={"client_id": {"$eq": client_id}}, include=[])

    return {
        "files": files,
        "total_chunks": len(client_chunks["ids"])
    }


@router.delete("/delete/{filename}")
async def delete_document(filename: str, user: User = Depends(require_admin)):
    """Delete a document and remove its chunks from ChromaDB, scoped to the tenant."""
    client_id = user.client_id
    file_path = _client_docs_path(client_id) / filename

    # Remove from disk
    if file_path.exists():
        os.remove(file_path)
        logger.info(f"Deleted file: {filename} (client_id={client_id})")

    # Remove its chunks from ChromaDB
    collection = get_chroma_collection()
    collection.delete(where={
        "$and": [
            {"source": {"$eq": filename}},
            {"client_id": {"$eq": client_id}}
        ]
    })
    logger.info(f"Removed chunks for: {filename} (client_id={client_id})")

    return {"message": f"'{filename}' deleted from knowledge base."}