import os
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.document_loader import load_pdf_file, load_text_file, chunk_text
from app.rag_service import ingest_documents, get_chroma_collection
import logging

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and ingest a document into the knowledge base."""
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file_ext}'. Allowed: {ALLOWED_EXTENSIONS}"
        )

    # Save file to documents dir
    docs_path = Path(settings.DOCUMENTS_DIR)
    docs_path.mkdir(parents=True, exist_ok=True)
    file_path = docs_path / file.filename

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    logger.info(f"Saved uploaded file: {file.filename}")

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
                "file_type": file_ext
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
async def list_documents():
    """List all documents currently in the knowledge base."""
    docs_path = Path(settings.DOCUMENTS_DIR)
    docs_path.mkdir(parents=True, exist_ok=True)

    files = [
        f.name for f in docs_path.iterdir()
        if f.suffix.lower() in ALLOWED_EXTENSIONS
    ]
    collection = get_chroma_collection()

    return {
        "files": files,
        "total_chunks": collection.count()
    }


@router.delete("/delete/{filename}")
async def delete_document(filename: str):
    """Delete a document and remove its chunks from ChromaDB."""
    file_path = Path(settings.DOCUMENTS_DIR) / filename

    # Remove from disk
    if file_path.exists():
        os.remove(file_path)
        logger.info(f"Deleted file: {filename}")

    # Remove its chunks from ChromaDB
    collection = get_chroma_collection()
    collection.delete(where={"source": {"$eq": filename}})
    logger.info(f"Removed chunks for: {filename}")

    return {"message": f"'{filename}' deleted from knowledge base."}