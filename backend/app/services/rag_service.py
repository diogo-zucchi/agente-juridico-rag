from typing import List, Dict, Any
from openai import OpenAI
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import Chunk, Consulta, Resposta, RespostaDocumento
from app.services.ingestao_service import buscar_chunks

PROMPT_JURIDICO = """Você é um assistente jurídico especializado no direito brasileiro.
Utilize EXCLUSIVAMENTE os trechos de documentos jurídicos fornecidos abaixo.
Nunca invente informações. Se a resposta não estiver nos documentos, diga claramente.
Sempre indique as fontes utilizadas na sua resposta.

=== DOCUMENTOS JURÍDICOS RECUPERADOS ===
{contexto}
=========================================

Pergunta: {pergunta}

Resposta fundamentada:"""

_llm = None


def _criar_llm():
    settings = get_settings()
    logger.info("Carregando modelo: Maritaca Sabiá-4")
    client = OpenAI(
        api_key=settings.maritaca_api_key,
        base_url="https://chat.maritaca.ai/api",
    )

    def invocar(prompt: str) -> str:
        response = client.chat.completions.create(
            model="sabia-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1024,
        )
        return response.choices[0].message.content

    return invocar


def _get_llm():
    global _llm
    if _llm is None:
        _llm = _criar_llm()
    return _llm


def _montar_contexto(chunks_com_score: List[Dict]) -> str:
    partes = []
    for i, item in enumerate(chunks_com_score, 1):
        fonte = item.get("fonte", "Fonte desconhecida")
        titulo = item.get("titulo", "Documento")
        texto = item.get("texto_chunk", "")
        partes.append(f"[Documento {i}] {titulo} ({fonte})\n{texto}")
    return "\n\n---\n\n".join(partes)


def responder_pergunta(
    db: Session,
    pergunta: str,
    top_k: int | None = None,
) -> Dict[str, Any]:
    settings = get_settings()
    k = top_k or settings.top_k_results

    logger.info(f"Buscando chunks para: '{pergunta[:80]}...'")
    resultados = buscar_chunks(pergunta, top_k=k)

    if not resultados:
        resposta_texto = (
            "Não encontrei documentos jurídicos relevantes para sua pergunta. "
            "Por favor, indexe documentos relacionados ao tema antes de consultar."
        )
        fontes = []
    else:
        chunk_ids = [cid for cid, _ in resultados]
        scores_map = {cid: score for cid, score in resultados}

        chunks_db = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()

        chunks_com_score = []
        for chunk in chunks_db:
            doc = chunk.documento
            fonte = doc.fonte.nome if doc and doc.fonte else "Fonte desconhecida"
            chunks_com_score.append({
                "chunk_id": chunk.id,
                "titulo": doc.titulo if doc else "Documento",
                "fonte": fonte,
                "texto_chunk": chunk.texto_chunk,
                "score": scores_map.get(chunk.id, 0.0),
            })

        chunks_com_score.sort(key=lambda x: x["score"], reverse=True)

        contexto = _montar_contexto(chunks_com_score)
        prompt = PROMPT_JURIDICO.format(contexto=contexto, pergunta=pergunta)

        logger.info("Gerando resposta com LLM...")
        try:
            llm = _get_llm()
            resposta_texto = llm(prompt)
        except Exception as e:
            logger.error(f"Erro ao chamar LLM: {e}")
            resposta_texto = "Ocorreu um erro ao gerar a resposta. Verifique as configurações do modelo."

        fontes = chunks_com_score

    consulta = Consulta(pergunta=pergunta)
    db.add(consulta)
    db.flush()

    resposta_db = Resposta(
        texto_resposta=resposta_texto,
        id_consulta=consulta.id,
    )
    db.add(resposta_db)
    db.flush()

    consulta.id_resposta = resposta_db.id

    for item in fontes:
        rd = RespostaDocumento(
            id_resposta=resposta_db.id,
            id_chunk=item["chunk_id"],
            score=item["score"],
        )
        db.add(rd)

    db.commit()

    logger.info(f"Resposta gerada e salva (consulta_id={consulta.id}).")
    return {
        "consulta_id": consulta.id,
        "resposta": resposta_texto,
        "fontes": fontes,
    }


def listar_historico(db: Session, limite: int = 20) -> List[Dict]:
    consultas = (
        db.query(Consulta)
        .order_by(Consulta.data_hora.desc())
        .limit(limite)
        .all()
    )
    return [
        {
            "id": c.id,
            "pergunta": c.pergunta,
            "data_hora": c.data_hora.isoformat(),
            "resposta": c.resposta.texto_resposta if c.resposta else None,
        }
        for c in consultas
    ]