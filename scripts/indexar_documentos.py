"""
Script de ingestão em lote — indexa todos os arquivos em data/raw/.

Uso:
    python scripts/indexar_documentos.py
    python scripts/indexar_documentos.py --pasta ./data/raw --fonte-id 1
"""
import argparse
import sys
import os

# Adiciona o backend ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from app.core.database import SessionLocal, verificar_conexao, engine
from app.models.models import Base
from app.services.ingestao_service import ingerir_documento

EXTENSOES_ACEITAS = {".pdf", ".txt", ".html", ".htm"}


def indexar_pasta(pasta: str, id_fonte: int | None):
    caminho = Path(pasta)
    arquivos = [f for f in caminho.iterdir()
                if f.is_file() and f.suffix.lower() in EXTENSOES_ACEITAS]

    if not arquivos:
        logger.warning(f"Nenhum arquivo suportado encontrado em '{pasta}'.")
        return

    logger.info(f"Encontrados {len(arquivos)} arquivo(s) para indexar.")

    db = SessionLocal()
    sucesso, erro = 0, 0

    for arquivo in arquivos:
        try:
            titulo = arquivo.stem.replace("_", " ").replace("-", " ").title()
            ingerir_documento(db=db, caminho=str(arquivo), titulo=titulo, id_fonte=id_fonte)
            sucesso += 1
        except Exception as e:
            logger.error(f"Erro ao indexar '{arquivo.name}': {e}")
            erro += 1

    db.close()
    logger.info(f"Indexação concluída: {sucesso} sucesso(s), {erro} erro(s).")


def main():
    parser = argparse.ArgumentParser(description="Indexa documentos jurídicos em lote.")
    parser.add_argument("--pasta", default="./data/raw", help="Pasta com os documentos.")
    parser.add_argument("--fonte-id", type=int, default=None,
                        help="ID da fonte (tabela fontes) a associar aos documentos.")
    args = parser.parse_args()

    if not verificar_conexao():
        logger.error("Banco de dados indisponível. Abortando.")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    indexar_pasta(args.pasta, args.fonte_id)


if __name__ == "__main__":
    main()
