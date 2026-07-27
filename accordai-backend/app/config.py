from pydantic_settings import BaseSettings
from functools import lru_cache
class Settings(BaseSettings):
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_PHONE_NUMBER: str
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    DATABASE_URL: str

    # Fernet key for encrypting client tool credentials at rest
    ENCRYPTION_KEY: str

    # JWT auth
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24h; refresh tokens are future work

    # Public base URL of this backend (the tunnel/host Twilio can reach).
    # Shown in Settings as the voice webhook base; not used for routing.
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # Comma-separated browser origins allowed by CORS (add the deployed
    # frontend's domain here, e.g. "http://localhost:3000,https://app.vercel.app").
    CORS_ORIGINS: str = "http://localhost:3000"

    # Client tool execution
    TOOL_HTTP_TIMEOUT: float = 10.0
    # Dev-only escape hatch so test scripts can point tools at 127.0.0.1.
    # Must stay False in production — it disables SSRF protection.
    ALLOW_PRIVATE_TOOL_URLS: bool = False


     # RAG
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    DOCUMENTS_DIR: str = "./documents"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    RAG_TOP_K: int = 3
    RAG_SIMILARITY_THRESHOLD: float = 0.4
    
    # App
    DEBUG: bool = True
    class Config:
        env_file = ".env"


        

@lru_cache()
def get_settings():
    return Settings()