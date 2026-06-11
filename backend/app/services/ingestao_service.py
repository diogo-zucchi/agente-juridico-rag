"""
Serviço de Ingestão de Documentos Jurídicos.

Responsável por:
  1. Ler arquivos (PDF, TXT, HTML)
  2. Dividir em chunks
  3. Gerar embeddings
  4. Salvar no PostgreSQL e no índice FAISS
"""
import hashlib
import os
import json
from pathlib import Path
from typing import List, Tuple

import faiss
import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import Chunk, Documento, Fonte

settings = get_settings()


# ─────────────────────────────────────────────
# Modelo de embeddings (carregado uma vez)
# ─────────────────────────────────────────────
_embedding_model: SentenceTransformer | None = None


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Carregando modelo de embeddings: {settings.embedding_model}")
        _embedding_model = SentenceTransformer(settings.embedding_model)
    return _embedding_model


# ─────────────────────────────────────────────
# FAISS Index
# ─────────────────────────────────────────────
_faiss_index: faiss.Index | None = None
_chunk_ids: List[int] = []     # mapeia posição FAISS -> id do chunk no banco


def _get_faiss_index(dim: int = 384) -> Tuple[faiss.Index, List[int]]:
    """Carrega ou cria o índice FAISS."""
    global _faiss_index, _chunk_ids
    
    # Caminho absoluto fixo, independente de onde a API é executada
    base_dir = Path(__file__).resolve().parent.parent.parent
    index_path = base_dir / "data" / "faiss_index"
    ids_path   = index_path.with_suffix(".ids.json")

    if _faiss_index is None:
        if index_path.exists():
            logger.info("Carregando índice FAISS existente...")
            _faiss_index = faiss.read_index(str(index_path))
            _chunk_ids   = json.loads(ids_path.read_text()) if ids_path.exists() else []
        else:
            logger.info("Criando novo índice FAISS (IndexFlatIP)...")
            index_path.parent.mkdir(parents=True, exist_ok=True)
            _faiss_index = faiss.IndexFlatIP(dim)  
            _chunk_ids   = []

    return _faiss_index, _chunk_ids


def _salvar_faiss():
    base_dir = Path(__file__).resolve().parent.parent.parent
    index_path = base_dir / "data" / "faiss_index"
    ids_path   = index_path.with_suffix(".ids.json")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(_faiss_index, str(index_path))
    ids_path.write_text(json.dumps(_chunk_ids))
    logger.info(f"Índice FAISS salvo em {index_path}")


# ─────────────────────────────────────────────
# Leitura de arquivos
# ─────────────────────────────────────────────

def _ler_pdf(caminho: str) -> str:
    texto = ""

    try:
        import fitz  # PyMuPDF
        with fitz.open(caminho) as doc:
            texto = "\n".join(page.get_text() for page in doc)
    except Exception as e:
        logger.warning(f"PyMuPDF não disponível/falhou ({e}); tentando pypdf...")

    if not texto.strip():
        from pypdf import PdfReader
        reader = PdfReader(caminho)
        texto = "\n".join(p.extract_text() or "" for p in reader.pages)

    if not texto.strip():
        raise ValueError(
            "Não foi possível extrair texto deste PDF. Ele pode ser digitalizado "
            "(imagem), o que exigiria OCR. Envie o documento em .txt ou .html."
        )
    return texto


def _ler_txt(caminho: str) -> str:
    return Path(caminho).read_text(encoding="utf-8", errors="ignore")


def _ler_html(caminho: str) -> str:
    from bs4 import BeautifulSoup
    html = Path(caminho).read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n")


def ler_arquivo(caminho: str) -> str:
    ext = Path(caminho).suffix.lower()
    if ext == ".pdf":
        return _ler_pdf(caminho)
    elif ext in (".txt", ".md"):
        return _ler_txt(caminho)
    elif ext in (".html", ".htm"):
        return _ler_html(caminho)
    else:
        raise ValueError(f"Formato não suportado: {ext}")


# ─────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────

def _dividir_em_chunks(texto: str) -> List[str]:
    """
    Divide o texto em chunks com sobreposição.
    Tenta respeitar parágrafos antes de cortar por caracteres.
    """
    tamanho  = settings.chunk_size
    overlap  = settings.chunk_overlap
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]

    chunks  = []
    buffer  = ""

    for paragrafo in paragrafos:
        if len(buffer) + len(paragrafo) <= tamanho:
            buffer += (" " if buffer else "") + paragrafo
        else:
            if buffer:
                chunks.append(buffer)
            # Parágrafo maior que o chunk? Divide por caractere.
            if len(paragrafo) > tamanho:
                for i in range(0, len(paragrafo), tamanho - overlap):
                    chunks.append(paragrafo[i : i + tamanho])
            else:
                buffer = paragrafo

    if buffer:
        chunks.append(buffer)

    return chunks


# ─────────────────────────────────────────────
# Pipeline principal de ingestão
# ─────────────────────────────────────────────

def ingerir_documento(
    db: Session,
    caminho: str,
    titulo: str,
    id_fonte: int | None = None,
    nivel_dificuldade: str | None = None,
) -> Documento:
    """
    Pipeline completo:
      ler arquivo → calcular hash → chunks → embeddings → salvar banco + FAISS
    """
    # 1. Leitura
    logger.info(f"Lendo arquivo: {caminho}")
    texto = ler_arquivo(caminho)

    # 2. Hash para evitar duplicatas
    hash_doc = hashlib.sha256(texto.encode()).hexdigest()
    existente = db.query(Documento).filter_by(hash_integridade=hash_doc).first()
    if existente:
        logger.warning(f"Documento já indexado (hash={hash_doc[:8]}…). Ignorando.")
        return existente

    # 3. Salvar documento no banco
    doc = Documento(
        titulo=titulo,
        texto=texto,
        id_fonte=id_fonte,
        nivel_dificuldade=nivel_dificuldade,
        hash_integridade=hash_doc,
        arquivo_origem=os.path.basename(caminho),
    )
    db.add(doc)
    db.flush()  # obtém doc.id antes do commit

    # 4. Chunking
    lista_chunks = _dividir_em_chunks(texto)
    logger.info(f"Documento dividido em {len(lista_chunks)} chunks.")

    # 5. Embeddings
    modelo = _get_embedding_model()
    embeddings = modelo.encode(lista_chunks, show_progress_bar=True, normalize_embeddings=True)

    # 6. Salvar chunks no banco
    chunks_db = []
    for idx, (chunk_texto, emb) in enumerate(zip(lista_chunks, embeddings)):
        chunk = Chunk(
            id_documento=doc.id,
            texto_chunk=chunk_texto,
            indice_chunk=idx,
        )
        db.add(chunk)
        chunks_db.append((chunk, emb))

    db.flush()

    # 7. Adicionar ao FAISS
    index, ids = _get_faiss_index(dim=embeddings.shape[1])
    vetores = np.array([emb for _, emb in chunks_db], dtype="float32")
    index.add(vetores)
    for chunk, _ in chunks_db:
        ids.append(chunk.id)

    _salvar_faiss()
    db.commit()

    logger.info(f"Documento '{titulo}' indexado com sucesso ({len(lista_chunks)} chunks).")
    return doc


# ─────────────────────────────────────────────
# Busca semântica (usada pelo retriever)
# ─────────────────────────────────────────────

def buscar_chunks(pergunta: str, top_k: int | None = None) -> List[Tuple[int, float]]:
    """
    Retorna lista de (chunk_id, score) ordenada por similaridade.
    """
    k = top_k or settings.top_k_results
    modelo = _get_embedding_model()
    vetor_pergunta = modelo.encode([pergunta], normalize_embeddings=True).astype("float32")

    index, ids = _get_faiss_index()
    if index.ntotal == 0:
        logger.warning("Índice FAISS vazio! Indexe documentos primeiro.")
        return []

    scores, posicoes = index.search(vetor_pergunta, k)
    resultados = []
    for pos, score in zip(posicoes[0], scores[0]):
        if pos >= 0 and pos < len(ids):
            resultados.append((ids[pos], float(score)))

    return resultados
