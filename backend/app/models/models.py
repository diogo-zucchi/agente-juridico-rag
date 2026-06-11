"""
Modelos ORM — espelham as tabelas do init_db.sql.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Text, Date, Float,
    DateTime, ForeignKey, func
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Fonte(Base):
    __tablename__ = "fontes"

    id        = Column(Integer, primary_key=True, index=True)
    nome      = Column(String(255), nullable=False)
    tipo      = Column(String(100), nullable=False)
    url_base  = Column(Text)
    criado_em = Column(DateTime, default=func.now())

    documentos = relationship("Documento", back_populates="fonte")


class Documento(Base):
    __tablename__ = "documentos"

    id               = Column(Integer, primary_key=True, index=True)
    titulo           = Column(String(500), nullable=False)
    texto            = Column(Text, nullable=False)
    data_publicacao  = Column(Date)
    # rótulo do experimento: 'facil', 'medio' ou 'dificil'
    nivel_dificuldade = Column(String(20), nullable=True)
    id_fonte         = Column(Integer, ForeignKey("fontes.id"))
    hash_integridade = Column(String(64), unique=True)
    arquivo_origem   = Column(String(500))
    criado_em        = Column(DateTime, default=func.now())

    fonte  = relationship("Fonte", back_populates="documentos")
    chunks = relationship("Chunk", back_populates="documento", cascade="all, delete")


class Chunk(Base):
    __tablename__ = "chunks"

    id           = Column(Integer, primary_key=True, index=True)
    id_documento = Column(Integer, ForeignKey("documentos.id", ondelete="CASCADE"))
    texto_chunk  = Column(Text, nullable=False)
    indice_chunk = Column(Integer, nullable=False)
    # embedding armazenado como texto JSON (fallback sem pgvector instalado)
    criado_em    = Column(DateTime, default=func.now())

    documento = relationship("Documento", back_populates="chunks")
    respostas = relationship("RespostaDocumento", back_populates="chunk")


class Consulta(Base):
    __tablename__ = "consultas"

    id          = Column(Integer, primary_key=True, index=True)
    pergunta    = Column(Text, nullable=False)
    data_hora   = Column(DateTime, default=func.now())
    id_resposta = Column(Integer, ForeignKey("respostas.id"), nullable=True)
    # documento usado no teste (quando a busca é restrita a 1 documento)
    id_documento = Column(Integer, ForeignKey("documentos.id", ondelete="SET NULL"), nullable=True)

    resposta = relationship("Resposta", back_populates="consulta",
                            foreign_keys=[id_resposta])
    documento = relationship("Documento", foreign_keys=[id_documento])


class Resposta(Base):
    __tablename__ = "respostas"

    id             = Column(Integer, primary_key=True, index=True)
    texto_resposta = Column(Text, nullable=False)
    # qual LLM gerou esta resposta: 'maritaca' ou 'deepseek'
    modelo_llm     = Column(String(50), nullable=True)
    data_hora      = Column(DateTime, default=func.now())
    id_consulta    = Column(Integer, ForeignKey("consultas.id", ondelete="CASCADE"))

    consulta  = relationship("Consulta", back_populates="resposta",
                              foreign_keys=[Consulta.id_resposta])
    documentos_utilizados = relationship("RespostaDocumento", back_populates="resposta")
    avaliacoes = relationship("Avaliacao", back_populates="resposta",
                              cascade="all, delete")


class RespostaDocumento(Base):
    __tablename__ = "resposta_documento"

    id          = Column(Integer, primary_key=True, index=True)
    id_resposta = Column(Integer, ForeignKey("respostas.id", ondelete="CASCADE"))
    id_chunk    = Column(Integer, ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    score       = Column(Float)
    criado_em   = Column(DateTime, default=func.now())

    resposta = relationship("Resposta", back_populates="documentos_utilizados")
    chunk    = relationship("Chunk", back_populates="respostas")


class Avaliacao(Base):
    __tablename__ = "avaliacoes"

    id          = Column(Integer, primary_key=True, index=True)
    id_resposta = Column(Integer, ForeignKey("respostas.id", ondelete="CASCADE"))
    nota        = Column(Integer, nullable=False)   # 1 a 5
    comentario  = Column(Text, nullable=True)
    avaliador   = Column(String(255), nullable=True)
    data_hora   = Column(DateTime, default=func.now())

    resposta = relationship("Resposta", back_populates="avaliacoes")
