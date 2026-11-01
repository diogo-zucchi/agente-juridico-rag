"""
Testes automatizados do pipeline RAG.

Execução:
    cd backend
    pytest tests/ -v
"""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from app.services.ingestao_service import _dividir_em_chunks


# ─────────────────────────────────────────────
# Testes de Chunking
# ─────────────────────────────────────────────

class TestChunking:
    def test_texto_curto_retorna_um_chunk(self):
        texto = "Este é um texto curto para teste."
        chunks = _dividir_em_chunks(texto)
        assert len(chunks) >= 1
        assert chunks[0] == texto

    def test_texto_longo_gera_multiplos_chunks(self):
        # Gera texto maior que CHUNK_SIZE (512 chars)
        paragrafo = "Dispositivo legal aplicável ao caso. " * 20
        texto = "\n\n".join([paragrafo] * 5)
        chunks = _dividir_em_chunks(texto)
        assert len(chunks) > 1

    def test_chunks_nao_sao_vazios(self):
        texto = "\n\n".join(["Parágrafo jurídico número {}.".format(i) for i in range(30)])
        chunks = _dividir_em_chunks(texto)
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_preserva_conteudo(self):
        """Todo conteúdo do texto deve aparecer em algum chunk."""
        palavras_chave = ["STJ", "aposentadoria", "insalubridade"]
        texto = "\n\n".join([
            "O STJ decidiu sobre o caso de aposentadoria especial.",
            "A insalubridade foi comprovada por laudo técnico.",
            "O recurso foi provido por unanimidade.",
        ])
        chunks = _dividir_em_chunks(texto)
        texto_chunks = " ".join(chunks)
        for palavra in palavras_chave:
            assert palavra in texto_chunks

    def test_paragrafo_longo_nao_duplica_buffer(self):
        """
        Regressão: após um parágrafo maior que o chunk, o buffer anterior
        era reaproveitado e aparecia duplicado (e fora de ordem) no chunk seguinte.
        """
        from app.services.ingestao_service import settings
        curto_a = "Art. 1º Primeiro dispositivo."
        longo   = "B" * (settings.chunk_size + 100)
        curto_c = "Art. 3º Terceiro dispositivo."
        chunks = _dividir_em_chunks("\n\n".join([curto_a, longo, curto_c]))

        assert sum(curto_a in c for c in chunks) == 1
        assert chunks[0] == curto_a
        assert chunks[-1] == curto_c


# ─────────────────────────────────────────────
# Testes de Leitura de Arquivo
# ─────────────────────────────────────────────

class TestLeituraArquivo:
    def test_ler_txt(self, tmp_path):
        from app.services.ingestao_service import ler_arquivo
        arquivo = tmp_path / "teste.txt"
        arquivo.write_text("Conteúdo jurídico de teste.", encoding="utf-8")
        texto = ler_arquivo(str(arquivo))
        assert "Conteúdo jurídico" in texto

    def test_formato_nao_suportado(self, tmp_path):
        from app.services.ingestao_service import ler_arquivo
        arquivo = tmp_path / "teste.docx"
        arquivo.write_bytes(b"fake content")
        with pytest.raises(ValueError, match="Formato não suportado"):
            ler_arquivo(str(arquivo))

    def test_ler_html(self, tmp_path):
        from app.services.ingestao_service import ler_arquivo
        arquivo = tmp_path / "teste.html"
        arquivo.write_text(
            "<html><body><h1>Acórdão</h1><p>Texto da decisão.</p></body></html>",
            encoding="utf-8"
        )
        texto = ler_arquivo(str(arquivo))
        assert "Acórdão" in texto
        assert "Texto da decisão" in texto


# ─────────────────────────────────────────────
# Testes de Integração (com mock do banco)
# ─────────────────────────────────────────────

class TestBuscaVetorial:
    def _buscar(self, id_documento=None):
        import numpy as np
        from app.services.ingestao_service import buscar_chunks

        chunk_mock = MagicMock()
        db_mock = MagicMock()
        # <#> devolve o produto interno negativo
        db_mock.execute.return_value.all.return_value = [(chunk_mock, -0.82)]

        with patch("app.services.ingestao_service.gerar_embeddings",
                   return_value=np.zeros((1, 384), dtype="float32")):
            resultado = buscar_chunks(db_mock, "pergunta", top_k=3,
                                      id_documento=id_documento)

        from sqlalchemy.dialects import postgresql
        stmt = db_mock.execute.call_args[0][0]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        return resultado, chunk_mock, sql

    def test_usa_produto_interno_do_pgvector(self):
        resultado, chunk_mock, sql = self._buscar()
        assert "<#>" in sql
        assert "LIMIT" in sql
        assert "chunks.id_documento =" not in sql
        # score volta positivo, como no antigo IndexFlatIP
        assert resultado == [(chunk_mock, pytest.approx(0.82))]

    def test_filtra_por_documento_no_banco(self):
        _, _, sql = self._buscar(id_documento=7)
        assert "chunks.id_documento =" in sql


class TestRagService:
    def test_recuperar_chunks_repassa_documento_e_scores(self):
        from app.services import rag_service

        chunk = MagicMock()
        chunk.id = 10
        chunk.texto_chunk = "Art. 16. São beneficiários..."
        chunk.documento.titulo = "Lei 8.213/91"
        chunk.documento.fonte.nome = "Planalto"

        with patch("app.services.rag_service.buscar_chunks",
                   return_value=[(chunk, 0.9)]) as busca:
            fontes = rag_service._recuperar_chunks(MagicMock(), "dependentes", 5, id_documento=3)

        assert busca.call_args.kwargs["id_documento"] == 3
        assert fontes == [{
            "chunk_id": 10,
            "titulo": "Lei 8.213/91",
            "fonte": "Planalto",
            "texto_chunk": "Art. 16. São beneficiários...",
            "score": 0.9,
        }]

    def test_responder_sem_documentos_indexados(self):
        """Sem chunks indexados, deve retornar mensagem de aviso."""
        from app.services import rag_service
        from app.services.ingestao_service import buscar_chunks

        db_mock = MagicMock()
        # Consulta salva com flush
        consulta_mock = MagicMock()
        consulta_mock.id = 1
        resposta_mock  = MagicMock()
        resposta_mock.id = 1
        db_mock.query.return_value.filter.return_value.all.return_value = []

        with patch("app.services.rag_service.buscar_chunks", return_value=[]):
            with patch("app.services.rag_service.Consulta", return_value=consulta_mock):
                with patch("app.services.rag_service.Resposta", return_value=resposta_mock):
                    resultado = rag_service.responder_pergunta(
                        db=db_mock,
                        pergunta="Quais decisões tratam de aposentadoria especial?",
                    )

        assert "consulta_id" in resultado
        assert "resposta" in resultado
        assert "indexe" in resultado["resposta"].lower() or "não encontrei" in resultado["resposta"].lower()

    def test_historico_formato(self):
        """listar_historico deve retornar lista de dicts com campos esperados."""
        from app.services.rag_service import listar_historico
        from datetime import datetime

        consulta_mock = MagicMock()
        consulta_mock.id = 1
        consulta_mock.pergunta = "Teste?"
        consulta_mock.data_hora = datetime(2026, 1, 15, 10, 30)
        consulta_mock.resposta = MagicMock()
        consulta_mock.resposta.texto_resposta = "Resposta de teste."

        db_mock = MagicMock()
        db_mock.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            consulta_mock
        ]

        historico = listar_historico(db=db_mock, limite=5)
        assert isinstance(historico, list)
        assert len(historico) == 1
        assert historico[0]["pergunta"] == "Teste?"
        assert "data_hora" in historico[0]


# ─────────────────────────────────────────────
# Testes de Hash de Integridade
# ─────────────────────────────────────────────

class TestHashIntegridade:
    def test_hash_consistente(self):
        import hashlib
        texto = "Documento jurídico de referência."
        h1 = hashlib.sha256(texto.encode()).hexdigest()
        h2 = hashlib.sha256(texto.encode()).hexdigest()
        assert h1 == h2

    def test_hash_diferente_para_textos_distintos(self):
        import hashlib
        h1 = hashlib.sha256("Texto A".encode()).hexdigest()
        h2 = hashlib.sha256("Texto B".encode()).hexdigest()
        assert h1 != h2


# ─────────────────────────────────────────────
# Testes das Rotas da API (TestClient)
# ─────────────────────────────────────────────

class TestAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_root_responde(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_consulta_sem_pergunta_retorna_400(self, client):
        with patch("app.api.routes.rag_service.responder_pergunta"):
            r = client.post("/api/v1/consultar", json={"pergunta": ""})
        assert r.status_code == 400

    def test_consulta_com_pergunta_valida(self, client):
        mock_resultado = {
            "consulta_id": 1,
            "resposta": "Resposta de teste.",
            "fontes": [],
        }
        with patch("app.api.routes.rag_service.responder_pergunta", return_value=mock_resultado):
            r = client.post(
                "/api/v1/consultar",
                json={"pergunta": "O que é aposentadoria especial?"},
            )
        assert r.status_code == 200
        assert "resposta" in r.json()
