import random
from typing import List, Dict, Any, Callable
from openai import OpenAI
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import (
    Chunk, Consulta, Resposta, RespostaDocumento, Avaliacao, Documento
)
from app.services.ingestao_service import buscar_chunks, _get_faiss_index

PROMPT_JURIDICO = """Você é um assistente jurídico especializado no direito brasileiro.
Utilize EXCLUSIVAMENTE os trechos de documentos jurídicos fornecidos abaixo.
Nunca invente informações. Se a resposta não estiver nos documentos, diga claramente.
Sempre indique as fontes utilizadas na sua resposta.

=== DOCUMENTOS JURÍDICOS RECUPERADOS ===
{contexto}
=========================================

Pergunta: {pergunta}

Resposta fundamentada:"""

# Provedores de LLM suportados
PROVEDORES = ("maritaca", "deepseek", "openai")

# Cache de invocadores por provedor (criados sob demanda)
_llms: Dict[str, Callable[[str], str]] = {}


# ─────────────────────────────────────────────
# Fábrica de LLMs (Maritaca e DeepSeek)
# Ambos usam a interface compatível com a OpenAI,
# mudando apenas base_url, api_key e nome do modelo.
# ─────────────────────────────────────────────
def _criar_llm(provedor: str) -> Callable[[str], str]:
    settings = get_settings()

    if provedor == "maritaca":
        logger.info(f"Carregando LLM Maritaca ({settings.maritaca_model})")
        client = OpenAI(
            api_key=settings.maritaca_api_key,
            base_url="https://chat.maritaca.ai/api",
        )
        modelo = settings.maritaca_model

    elif provedor == "deepseek":
        logger.info(f"Carregando LLM DeepSeek ({settings.deepseek_model})")
        client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        modelo = settings.deepseek_model
    elif provedor == "openai":
        logger.info(f"Carregando LLM OpenAI ({settings.openai_model})")
        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        modelo = settings.openai_model

    else:
        raise ValueError(f"Provedor de LLM desconhecido: {provedor}")

    def invocar(prompt: str) -> str:
        response = client.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1024,
        )
        return response.choices[0].message.content

    return invocar


def _get_llm(provedor: str) -> Callable[[str], str]:
    if provedor not in _llms:
        _llms[provedor] = _criar_llm(provedor)
    return _llms[provedor]


def _montar_contexto(chunks_com_score: List[Dict]) -> str:
    partes = []
    for i, item in enumerate(chunks_com_score, 1):
        fonte = item.get("fonte", "Fonte desconhecida")
        titulo = item.get("titulo", "Documento")
        texto = item.get("texto_chunk", "")
        partes.append(f"[Documento {i}] {titulo} ({fonte})\n{texto}")
    return "\n\n---\n\n".join(partes)


# ─────────────────────────────────────────────
# Recuperação de chunks (com opção de restringir
# a busca a um único documento)
# ─────────────────────────────────────────────
def _recuperar_chunks(
    db: Session,
    pergunta: str,
    k: int,
    id_documento: int | None = None,
) -> List[Dict]:
    """
    Retorna os chunks mais relevantes já enriquecidos com título/fonte.
    Se id_documento for informado, a busca é restrita àquele documento:
    super-amostra o FAISS e depois filtra pelos chunks do documento.
    """
    if id_documento is not None:
        # super-amostra para garantir chunks suficientes do documento alvo
        index, _ = _get_faiss_index()
        resultados = buscar_chunks(pergunta, top_k=max(index.ntotal, k))
    else:
        resultados = buscar_chunks(pergunta, top_k=k)

    if not resultados:
        return []

    chunk_ids = [cid for cid, _ in resultados]
    scores_map = {cid: score for cid, score in resultados}

    query = db.query(Chunk).filter(Chunk.id.in_(chunk_ids))
    if id_documento is not None:
        query = query.filter(Chunk.id_documento == id_documento)
    chunks_db = query.all()

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
    return chunks_com_score[:k]


def _gerar_texto(provedor: str, chunks_com_score: List[Dict], pergunta: str) -> str:
    if not chunks_com_score:
        return (
            "Não encontrei documentos jurídicos relevantes para sua pergunta. "
            "Por favor, indexe documentos relacionados ao tema antes de consultar."
        )
    contexto = _montar_contexto(chunks_com_score)
    prompt = PROMPT_JURIDICO.format(contexto=contexto, pergunta=pergunta)
    logger.info(f"Gerando resposta com LLM: {provedor}")
    try:
        return _get_llm(provedor)(prompt)
    except Exception as e:
        logger.error(f"Erro ao chamar LLM {provedor}: {e}")
        return f"Ocorreu um erro ao gerar a resposta com {provedor}. Verifique a chave de API e o modelo configurado."


def _salvar_resposta(
    db: Session,
    consulta: Consulta,
    texto: str,
    provedor: str,
    fontes: List[Dict],
) -> Resposta:
    resposta = Resposta(
        texto_resposta=texto,
        modelo_llm=provedor,
        id_consulta=consulta.id,
    )
    db.add(resposta)
    db.flush()
    for item in fontes:
        db.add(RespostaDocumento(
            id_resposta=resposta.id,
            id_chunk=item["chunk_id"],
            score=item["score"],
        ))
    return resposta


# ─────────────────────────────────────────────
# Consulta com UMA LLM (uso normal)
# ─────────────────────────────────────────────
def responder_pergunta(
    db: Session,
    pergunta: str,
    provedor: str = "maritaca",
    top_k: int | None = None,
    id_documento: int | None = None,
) -> Dict[str, Any]:
    settings = get_settings()
    k = top_k or settings.top_k_results
    if provedor not in PROVEDORES:
        provedor = "maritaca"

    fontes = _recuperar_chunks(db, pergunta, k, id_documento)
    texto = _gerar_texto(provedor, fontes, pergunta)

    consulta = Consulta(pergunta=pergunta, id_documento=id_documento)
    db.add(consulta)
    db.flush()

    resposta = _salvar_resposta(db, consulta, texto, provedor, fontes)
    consulta.id_resposta = resposta.id
    db.commit()

    logger.info(f"Resposta ({provedor}) salva (consulta_id={consulta.id}).")
    return {
        "consulta_id": consulta.id,
        "resposta_id": resposta.id,
        "modelo_llm": provedor,
        "resposta": texto,
        "fontes": fontes,
    }


# ─────────────────────────────────────────────
# Modo COMPARAÇÃO ÀS CEGAS
# Recupera o contexto UMA vez e gera com as duas LLMs
# sobre exatamente o mesmo contexto. As respostas são
# embaralhadas e rotuladas como A/B (sem revelar a LLM).
# ─────────────────────────────────────────────
def comparar_llms(
    db: Session,
    pergunta: str,
    id_documento: int | None = None,
    top_k: int | None = None,
) -> Dict[str, Any]:
    settings = get_settings()
    k = top_k or settings.top_k_results

    # 1. Contexto único e idêntico para ambas as LLMs
    fontes = _recuperar_chunks(db, pergunta, k, id_documento)

    # 2. Uma consulta, duas respostas
    consulta = Consulta(pergunta=pergunta, id_documento=id_documento)
    db.add(consulta)
    db.flush()

    respostas_salvas = []
    for provedor in PROVEDORES:
        texto = _gerar_texto(provedor, fontes, pergunta)
        resposta = _salvar_resposta(db, consulta, texto, provedor, fontes)
        respostas_salvas.append(resposta)

    # primeira resposta vira a "principal" no histórico
    consulta.id_resposta = respostas_salvas[0].id
    db.commit()

    # 3. Embaralhar e rotular A/B (avaliação às cegas)
    blocos = [
        {"resposta_id": r.id, "texto": r.texto_resposta, "modelo_llm": r.modelo_llm}
        for r in respostas_salvas
    ]
    random.shuffle(blocos)
    rotulos = [chr(ord("A") + i) for i in range(len(blocos))]
    respostas_cegas = []
    for rotulo, bloco in zip(rotulos, blocos):
        respostas_cegas.append({
            "rotulo": rotulo,
            "resposta_id": bloco["resposta_id"],
            "texto": bloco["texto"],
            # modelo_llm é devolvido só para conferência/debug;
            # o frontend NÃO o exibe ao avaliador.
            "modelo_llm": bloco["modelo_llm"],
        })

    logger.info(f"Comparação gerada às cegas (consulta_id={consulta.id}).")
    return {
        "consulta_id": consulta.id,
        "pergunta": pergunta,
        "fontes": fontes,
        "respostas": respostas_cegas,
    }


# ─────────────────────────────────────────────
# Avaliação (nota 1 a 5)
# ─────────────────────────────────────────────
def salvar_avaliacao(
    db: Session,
    id_resposta: int,
    nota: int,
    comentario: str | None = None,
    avaliador: str | None = None,
) -> Dict[str, Any]:
    if nota < 1 or nota > 5:
        raise ValueError("A nota deve estar entre 1 e 5.")
    resposta = db.query(Resposta).filter(Resposta.id == id_resposta).first()
    if not resposta:
        raise ValueError(f"Resposta {id_resposta} não encontrada.")

    avaliacao = Avaliacao(
        id_resposta=id_resposta,
        nota=nota,
        comentario=comentario,
        avaliador=avaliador,
    )
    db.add(avaliacao)
    db.commit()
    db.refresh(avaliacao)
    logger.info(f"Avaliação salva (resposta_id={id_resposta}, nota={nota}).")
    return {"avaliacao_id": avaliacao.id, "id_resposta": id_resposta, "nota": nota}

# ─────────────────────────────────────────────
# Resultados consolidados (para a apresentação)
# ─────────────────────────────────────────────
def listar_resultados(db: Session) -> Dict[str, Any]:
    """
    Devolve:
      - linhas: cada avaliação com pergunta, documento, dificuldade, LLM, nota
      - resumo: nota média por LLM x dificuldade e por LLM
    """
    avaliacoes = db.query(Avaliacao).all()
    linhas = []
    for a in avaliacoes:
        resposta = a.resposta
        if not resposta:
            continue
        consulta = (
            db.query(Consulta).filter(Consulta.id == resposta.id_consulta).first()
        )
        doc = consulta.documento if consulta else None
        linhas.append({
            "avaliacao_id": a.id,
            "consulta_id": consulta.id if consulta else None,
            "pergunta": consulta.pergunta if consulta else None,
            "documento": doc.titulo if doc else None,
            "nivel_dificuldade": doc.nivel_dificuldade if doc else None,
            "modelo_llm": resposta.modelo_llm,
            "nota": a.nota,
            "comentario": a.comentario,
            "avaliador": a.avaliador,
            "data_hora": a.data_hora.isoformat() if a.data_hora else None,
        })

    # agregações
    def _media(valores):
        return round(sum(valores) / len(valores), 2) if valores else None

    por_llm: Dict[str, List[int]] = {}
    por_llm_dif: Dict[str, List[int]] = {}
    for l in linhas:
        llm = l["modelo_llm"] or "desconhecido"
        dif = l["nivel_dificuldade"] or "sem_rotulo"
        por_llm.setdefault(llm, []).append(l["nota"])
        por_llm_dif.setdefault(f"{llm}|{dif}", []).append(l["nota"])

    resumo_llm = [
        {"modelo_llm": llm, "nota_media": _media(notas), "n": len(notas)}
        for llm, notas in sorted(por_llm.items())
    ]
    resumo_llm_dif = []
    for chave, notas in sorted(por_llm_dif.items()):
        llm, dif = chave.split("|", 1)
        resumo_llm_dif.append({
            "modelo_llm": llm,
            "nivel_dificuldade": dif,
            "nota_media": _media(notas),
            "n": len(notas),
        })

    return {
        "linhas": linhas,
        "resumo_por_llm": resumo_llm,
        "resumo_por_llm_dificuldade": resumo_llm_dif,
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
