from pydantic_settings import BaseSettings
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".env"

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:senha@localhost:5432/agente_juridico"

    maritaca_api_key: str = ""

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    faiss_index_path: str = "./data/faiss_index"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = True

    top_k_results: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 50

    log_level: str = "INFO"
    log_file: str = "./logs/agente.log"

    class Config:
        env_file = str(ENV_FILE)
        extra = "ignore"


def get_settings() -> Settings:
    return Settings()