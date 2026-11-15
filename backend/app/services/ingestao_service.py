"""
Serviço de Ingestão de Documentos Jurídicos.

Responsável por:
  1. Ler arquivos (PDF, TXT, HTML)
  2. Dividir em chunks (em leis: só a redação vigente, por artigo)
  3. Gerar embeddings
  4. Salvar texto e vetores no PostgreSQL (pgvector)
"""
import hashlib
import os
from pathlib import Path
from typing import List, Tuple

from loguru import logger
from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import Chunk, Documento, Fonte
from app.services.texto_legal import (
    dividir_artigo, eh_texto_legal, extrair_artigos, juntar_artigo, rotulo_do_artigo,
)

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
        dim = _embedding_model.get_sentence_embedding_dimension()
        if dim != settings.embedding_dim:
            raise ValueError(
                f"O modelo de embeddings gera vetores de dimensão {dim}, mas a "
                f"coluna chunks.embedding espera {settings.embedding_dim}. "
                "Ajuste EMBEDDING_DIM e a coluna vector(...) no banco."
            )
    return _embedding_model


def gerar_embeddings(textos: List[str], show_progress_bar: bool = False):
    """Embeddings normalizados (norma 1): produto interno = cosseno."""
    modelo = _get_embedding_model()
    return modelo.encode(
        textos, show_progress_bar=show_progress_bar, normalize_embeddings=True
    )


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
    Textos legais (com 'Art. N') são limpos das redações revogadas e
    divididos por artigo; os demais, por parágrafos.
    """
    if not eh_texto_legal(texto):
        return _dividir_por_paragrafos(texto)

    artigos, texto_fora = extrair_artigos(texto)
    chunks = _dividir_por_paragrafos(texto_fora) if texto_fora else []
    for linhas in artigos:
        chunks.extend(dividir_artigo(linhas, settings.chunk_size, settings.chunk_overlap))
    return chunks


def _dividir_por_paragrafos(texto: str) -> List[str]:
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
                # o buffer já foi emitido: zera para não duplicá-lo
                # no próximo chunk
                buffer = ""
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
      ler arquivo → calcular hash → chunks → embeddings → salvar no banco
    Texto e vetores são gravados na mesma transação: ou o documento
    inteiro fica indexado, ou nada é gravado.
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
    embeddings = gerar_embeddings(lista_chunks, show_progress_bar=True)

    # 6. Salvar chunks e vetores no banco
    for idx, (chunk_texto, emb) in enumerate(zip(lista_chunks, embeddings)):
        db.add(Chunk(
            id_documento=doc.id,
            texto_chunk=chunk_texto,
            indice_chunk=idx,
            embedding=emb,
        ))

    db.commit()

    logger.info(f"Documento '{titulo}' indexado com sucesso ({len(lista_chunks)} chunks).")
    return doc


# ─────────────────────────────────────────────
# Busca semântica (usada pelo retriever)
# ─────────────────────────────────────────────

def buscar_chunks(
    db: Session,
    pergunta: str,
    top_k: int | None = None,
    id_documento: int | None = None,
) -> List[Tuple[Chunk, float]]:
    """
    Retorna lista de (chunk, score) ordenada por similaridade.
    Se id_documento for informado, a busca é restrita àquele documento.

    Busca exata (sem índice aproximado): o score é o produto interno
    entre embeddings normalizados, o mesmo do antigo IndexFlatIP do FAISS.
    """
    k = top_k or settings.top_k_results
    vetor_pergunta = gerar_embeddings([pergunta])[0]

    # operador <#> do pgvector: devolve o produto interno NEGATIVO
    distancia = Chunk.embedding.max_inner_product(vetor_pergunta)

    stmt = (
        select(Chunk, distancia)
        .where(Chunk.embedding.isnot(None))
        .order_by(distancia)
        .limit(k)
    )
    if id_documento is not None:
        stmt = stmt.where(Chunk.id_documento == id_documento)

    resultados = db.execute(stmt).all()
    if not resultados:
        logger.warning("Nenhum chunk indexado encontrado. Indexe documentos primeiro.")

    return [(chunk, -float(dist)) for chunk, dist in resultados]


def texto_do_artigo(db: Session, id_documento: int, rotulo: str) -> str:
    """
    Remonta o artigo inteiro a partir dos chunks do documento que começam
    com o rótulo (todo chunk de um artigo começa com ele).
    """
    stmt = (
        select(Chunk.texto_chunk)
        .where(Chunk.id_documento == id_documento)
        .where(Chunk.texto_chunk.startswith(rotulo, autoescape=True))
        .order_by(Chunk.indice_chunk)
    )
    # startswith("Art. 1") também pega "Art. 10": confere o rótulo exato
    textos = [t for t in db.scalars(stmt).all() if rotulo_do_artigo(t) == rotulo]
    return juntar_artigo(textos)
