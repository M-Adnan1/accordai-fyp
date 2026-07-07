# """
# Run this script to ingest documents into the knowledge base:
#     python -m app.ingest
#     python -m app.ingest --dir ./my_docs
# """
# import asyncio
# import argparse
# import logging
# from app.document_loader import load_documents
# from app.rag_service import ingest_documents, get_chroma_collection

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# def main():
#     parser = argparse.ArgumentParser(description="Ingest documents into ChromaDB")
#     parser.add_argument("--dir", type=str, default=None, help="Path to documents directory")
#     args = parser.parse_args()
#     print("=" * 50)
#     print("AccordAI - Document Ingestion")
#     print("=" * 50)
#     documents = load_documents(args.dir)
#     if not documents:
#         print("No documents found. Add .txt, .pdf, or .md files to your documents directory.")
#         return
#     count = ingest_documents(documents)
#     collection = get_chroma_collection()
#     print("=" * 50)
#     print(f"Done! {count} chunks stored in ChromaDB.")
#     print(f"Total in knowledge base: {collection.count()}")
#     print("=" * 50)
# if __name__ == "__main__":
#     main()