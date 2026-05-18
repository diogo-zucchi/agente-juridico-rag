from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import shutil, os, tempfile

from app.core.database import get_db
from app.models.models import Fonte
from app.services import rag_service, ingestao_service

router = APIRouter()


class PerguntaRequest(BaseModel):
    pergunta: str
    top_k: Optional[int] = None


class FonteSchema(BaseModel):
    id: int
    nome: str
    tipo: str
    url_base: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("/consultar", tags=["RAG"])
def consultar(req: PerguntaRequest, db: Session = Depends(get_db)):
    if not req.pergunta.strip():
        raise HTTPException(status_code=400, detail="Pergunta não pode estar vazia.")
    return rag_service.responder_pergunta(db=db, pergunta=req.pergunta, top_k=req.top_k)


@router.get("/historico", tags=["RAG"])
def historico(limite: int = 20, db: Session = Depends(get_db)):
    return rag_service.listar_historico(db=db, limite=limite)


@router.post("/ingerir", tags=["Ingestão"])
def ingerir_documento(
    arquivo: UploadFile = File(...),
    titulo: str = Form(...),
    id_fonte: Optional[int] = Form(None),
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
        doc = ingestao_service.ingerir_documento(db=db, caminho=tmp_path, titulo=titulo, id_fonte=id_fonte)
        return {"mensagem": "Documento indexado com sucesso.", "documento_id": doc.id, "titulo": doc.titulo}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@router.get("/fontes", response_model=List[FonteSchema], tags=["Fontes"])
def listar_fontes(db: Session = Depends(get_db)):
    return db.query(Fonte).all()
