from pydantic_settings import BaseSettings
from functools import lru_cache
class Settings(BaseSettings):
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_PHONE_NUMBER: str
    GROQ_API_KEY: str
    DATABASE_URL: str


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