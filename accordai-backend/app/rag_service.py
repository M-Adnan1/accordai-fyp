import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Optional
from app.config import get_settings
import logging
 
logger = logging.getLogger(__name__)
settings = get_settings()

_chroma_client: Optional[chromadb.ClientAPI] = None
_collection: Optional[chromadb.Collection] = None
_embedding_model: Optional[SentenceTransformer] = None

COLLECTION_NAME = "knowledge_base"

def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
        _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _embedding_model

def get_chroma_collection() -> chromadb.Collection:
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}  # cosine similarity
        )
        logger.info(f"ChromaDB collection ready. Documents: {_collection.count()}")
    return _collection

def embed_texts(texts: List[str]) -> List[List[float]]:
    model = get_embedding_model()
    return model.encode(texts, show_progress_bar=False).tolist()

def ingest_documents(documents: List[Dict]) -> int:
    """Store document chunks into ChromaDB. Returns count ingested."""
    if not documents:
        logger.warning("No documents to ingest.")
        return 0

    collection = get_chroma_collection()
    # Scope delete-before-reingest to (source AND client_id) — matching on source
    # alone would delete/overwrite another client's chunks for a same-named file.
    source_client_pairs = list({
        (doc["metadata"]["source"], doc["metadata"]["client_id"]) for doc in documents
    })
    for source, client_id in source_client_pairs:
        try:
            collection.delete(where={
                "$and": [
                    {"source": {"$eq": source}},
                    {"client_id": {"$eq": client_id}}
                ]
            })
            logger.info(f"Cleared existing chunks for: {source} (client_id={client_id})")
        except Exception:
            pass
    contents = [doc["content"] for doc in documents]
    metadatas = [doc["metadata"] for doc in documents]
    ids = [f"chunk_{doc['metadata']['client_id']}_{doc['metadata']['source']}_{i}" for i, doc in enumerate(documents)]

    logger.info(f"Embedding {len(contents)} chunks...")
    embeddings = embed_texts(contents)

    # Batch insert (ChromaDB handles large sets better in batches)
    batch_size = 100
    for i in range(0, len(contents), batch_size):
        collection.add(
            ids=ids[i:i+batch_size],
            embeddings=embeddings[i:i+batch_size],
            documents=contents[i:i+batch_size],
            metadatas=metadatas[i:i+batch_size]
        )

    logger.info(f"Ingested {len(contents)} chunks into ChromaDB.")
    return len(contents)

def retrieve_context(
    query: str,
    client_id: int,
    top_k: int = None,
    threshold: float = None
) -> List[Dict]:
    """Retrieve the most relevant chunks for a query, scoped to a single client."""
    collection = get_chroma_collection()

    if collection.count() == 0:
        logger.warning("Knowledge base is empty. No context retrieved.")
        return []

    top_k = top_k or settings.RAG_TOP_K
    threshold = threshold or settings.RAG_SIMILARITY_THRESHOLD

    query_embedding = embed_texts([query])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        where={"client_id": {"$eq": client_id}},
        include=["documents", "metadatas", "distances"]
    )

    retrieved = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity score
        similarity = 1 - (dist / 2)
        if similarity >= threshold:
            retrieved.append({
                "content": doc,
                "source": meta.get("source", "unknown"),
                "similarity": round(similarity, 3)
            })
            logger.info(f"Retrieved chunk from '{meta.get('source')}' (similarity: {similarity:.3f})")

    return retrieved

def format_context_for_prompt(chunks: List[Dict]) -> str:
    """Format retrieved chunks into a string for the LLM prompt."""
    if not chunks:
        return ""
    parts = ["Relevant information from the knowledge base:"]
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"[{i}] (Source: {chunk['source']})\n{chunk['content']}")
    return "\n\n".join(parts)