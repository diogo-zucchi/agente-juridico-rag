from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import get_settings
from loguru import logger

settings = get_settings()

url = settings.database_url
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
elif not "postgresql+psycopg" in url:
    url = url.replace("postgresql+psycopg2", "postgresql+psycopg", 1)

engine = create_engine(
    url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verificar_conexao():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Conexão com PostgreSQL estabelecida.")
        return True
    except Exception as e:
        logger.error(f"❌ Falha ao conectar ao PostgreSQL: {e}")
        return False