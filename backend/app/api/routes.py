from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import shutil, os, tempfile, io, csv

from app.core.database import get_db
from app.models.models import Fonte, Documento
from app.services import rag_service, ingestao_service

router = APIRouter()


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class PerguntaRequest(BaseModel):
    pergunta: str
    provedor: Optional[str] = "maritaca"      # 'maritaca' ou 'deepseek'
    id_documento: Optional[int] = None
    top_k: Optional[int] = None


class CompararRequest(BaseModel):
    pergunta: str
    id_documento: Optional[int] = None
    top_k: Optional[int] = None


class AvaliacaoRequest(BaseModel):
    id_resposta: int
    nota: int                                  # 1 a 5
    comentario: Optional[str] = None
    avaliador: Optional[str] = None


class FonteSchema(BaseModel):
    id: int
    nome: str
    tipo: str
    url_base: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentoSchema(BaseModel):
    id: int
    titulo: str
    nivel_dificuldade: Optional[str] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# Consulta com uma LLM
# ─────────────────────────────────────────────
@router.post("/consultar", tags=["RAG"])
def consultar(req: PerguntaRequest, db: Session = Depends(get_db)):
    if not req.pergunta.strip():
        raise HTTPException(status_code=400, detail="Pergunta não pode estar vazia.")
    return rag_service.responder_pergunta(
        db=db,
        pergunta=req.pergunta,
        provedor=req.provedor or "maritaca",
        top_k=req.top_k,
        id_documento=req.id_documento,
    )


# ─────────────────────────────────────────────
# Comparação às cegas entre as duas LLMs
# ─────────────────────────────────────────────
@router.post("/comparar", tags=["Avaliação"])
def comparar(req: CompararRequest, db: Session = Depends(get_db)):
    if not req.pergunta.strip():
        raise HTTPException(status_code=400, detail="Pergunta não pode estar vazia.")
    return rag_service.comparar_llms(
        db=db,
        pergunta=req.pergunta,
        id_documento=req.id_documento,
        top_k=req.top_k,
    )


# ─────────────────────────────────────────────
# Salvar avaliação (nota 1 a 5)
# ─────────────────────────────────────────────
@router.post("/avaliar", tags=["Avaliação"])
def avaliar(req: AvaliacaoRequest, db: Session = Depends(get_db)):
    try:
        return rag_service.salvar_avaliacao(
            db=db,
            id_resposta=req.id_resposta,
            nota=req.nota,
            comentario=req.comentario,
            avaliador=req.avaliador,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────
# Resultados consolidados (para a apresentação)
# ─────────────────────────────────────────────
@router.get("/resultados", tags=["Avaliação"])
def resultados(db: Session = Depends(get_db)):
    return rag_service.listar_resultados(db=db)


@router.get("/resultados/csv", tags=["Avaliação"])
def resultados_csv(db: Session = Depends(get_db)):
    dados = rag_service.listar_resultados(db=db)
    buffer = io.StringIO()
    campos = [
        "avaliacao_id", "consulta_id", "pergunta", "documento",
        "nivel_dificuldade", "modelo_llm", "nota", "comentario",
        "avaliador", "data_hora",
    ]
    writer = csv.DictWriter(buffer, fieldnames=campos)
    writer.writeheader()
    for linha in dados["linhas"]:
        writer.writerow(linha)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=avaliacoes.csv"},
    )


# ─────────────────────────────────────────────
# Histórico / Ingestão / Listagens
# ─────────────────────────────────────────────
@router.get("/historico", tags=["RAG"])
def historico(limite: int = 20, db: Session = Depends(get_db)):
    return rag_service.listar_historico(db=db, limite=limite)


@router.post("/ingerir", tags=["Ingestão"])
def ingerir_documento(
    arquivo: UploadFile = File(...),
    titulo: str = Form(...),
    id_fonte: Optional[int] = Form(None),
    nivel_dificuldade: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    extensoes_aceitas = {".pdf", ".txt", ".html", ".htm"}
    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in extensoes_aceitas:
        raise HTTPException(status_code=400, detail=f"Formato não suportado. Use: {extensoes_aceitas}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(arquivo.file, tmp)
        tmp_path = tmp.name

    try:
        doc = ingestao_service.ingerir_documento(
            db=db, caminho=tmp_path, titulo=titulo,
            id_fonte=id_fonte, nivel_dificuldade=nivel_dificuldade,
        )
        return {
            "mensagem": "Documento indexado com sucesso.",
            "documento_id": doc.id,
            "titulo": doc.titulo,
            "nivel_dificuldade": doc.nivel_dificuldade,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@router.get("/documentos", response_model=List[DocumentoSchema], tags=["Ingestão"])
def listar_documentos(db: Session = Depends(get_db)):
    return db.query(Documento).order_by(Documento.criado_em.desc()).all()


@router.get("/fontes", response_model=List[FonteSchema], tags=["Fontes"])
def listar_fontes(db: Session = Depends(get_db)):
    return db.query(Fonte).all()
