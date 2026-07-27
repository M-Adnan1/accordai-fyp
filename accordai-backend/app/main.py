from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.voice_handler import router as voice_router
from app.database import engine, Base
from app.config import get_settings
import logging
from app.rag_service import get_chroma_collection, get_embedding_model
from app.documents_router import router as documents_router
from app.analytics_router import router as analytics_router
from app.tools_router import router as tools_router
from app.auth_router import router as auth_router
from app.account_router import router as account_router
from fastapi.middleware.cors import CORSMiddleware


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")
    logger.info("Initializing ChromaDB...")
    get_chroma_collection()
    logger.info("ChromaDB ready.")
    logger.info("Preloading embedding model...")
    get_embedding_model()
    logger.info("Embedding model ready.")
    yield
    logger.info("Shutting down...")
    await engine.dispose()
app = FastAPI(
    title="AccordAI Backend",
    description="AI Customer Service Voice Agent",
    version="1.0.0",
    lifespan=lifespan
)


app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(account_router, prefix="/account", tags=["Account"])
app.include_router(voice_router, prefix="/voice", tags=["Voice"])
app.include_router(documents_router, prefix="/documents", tags=["Documents"])
app.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
app.include_router(tools_router, prefix="/tools", tags=["Tools"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "message": "AccordAI Backend is running!",
        "status": "healthy"
    }
@app.get("/health")
async def health():
    return {"status": "ok"}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )