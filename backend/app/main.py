from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from loguru import logger
import sys, os

from app.core.config import get_settings
from app.core.database import verificar_conexao, engine
from app.models.models import Base
from app.api.routes import router

settings = get_settings()

# ─────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────
logger.remove()
logger.add(sys.stdout, level=settings.log_level)
logger.add(settings.log_file, rotation="10 MB", retention="30 days", level=settings.log_level)

# ─────────────────────────────────────────────
# Aplicação
# ─────────────────────────────────────────────
app = FastAPI(
    title="Agente Jurídico Inteligente (RAG)",
    description=(
        "API para consulta jurídica em linguagem natural usando "
        "Retrieval-Augmented Generation sobre documentos indexados."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Em produção, liste os domínios permitidos
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


# ─────────────────────────────────────────────
# Eventos de inicialização
# ─────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("Iniciando Agente Jurídico RAG...")
    ok = verificar_conexao()
    if not ok:
        logger.error("Banco de dados indisponível. Verifique a configuração.")
    else:
        # Cria tabelas que ainda não existem (não substitui o init_db.sql em prod)
        Base.metadata.create_all(bind=engine)
        logger.info("Tabelas verificadas/criadas.")


@app.get("/", tags=["Status"])
def root():
    # Serve o frontend (index.html) na raiz, para funcionar via túnel/deploy
    frontend = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html")
    if os.path.exists(frontend):
        return FileResponse(frontend)
    return {"status": "online", "app": "Agente Jurídico RAG", "docs": "/docs"}


@app.get("/health", tags=["Status"])
def health():
    db_ok = verificar_conexao()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}