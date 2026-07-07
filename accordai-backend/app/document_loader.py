import os
import re
from pathlib import Path
from typing import List, Dict
from app.config import get_settings

settings = get_settings()

def load_text_file(file_path: Path) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def load_pdf_file(file_path: Path) -> str:
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    except ImportError:
        raise ImportError("Install pdfplumber: pip install pdfplumber")

def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50
) -> List[str]:
    """Split text into overlapping chunks."""
    # Normalize whitespace
    text = re.sub(r'\n+', '\n', text).strip()
    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += chunk_size - chunk_overlap

    return chunks

def load_documents(documents_dir: str = None) -> List[Dict]:
    """Load all PDFs and text files from the documents directory."""
    docs_path = Path(documents_dir or settings.DOCUMENTS_DIR)
    docs_path.mkdir(parents=True, exist_ok=True)

    documents = []
    supported = {".txt", ".pdf", ".md"}

    for file_path in docs_path.iterdir():
        if file_path.suffix.lower() not in supported:
            continue

        print(f"Loading: {file_path.name}")

        if file_path.suffix.lower() == ".pdf":
            text = load_pdf_file(file_path)
        else:
            text = load_text_file(file_path)

        chunks = chunk_text(text)

        for i, chunk in enumerate(chunks):
            documents.append({
                "content": chunk,
                "metadata": {
                    "source": file_path.name,
                    "chunk_index": i,
                    "file_type": file_path.suffix.lower()
                }
            })

    print(f"Loaded {len(documents)} chunks from {docs_path}")
    return documents