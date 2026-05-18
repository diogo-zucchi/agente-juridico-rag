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

class TestRagService:
    def test_responder_sem_documentos_indexados(self):
        """Sem índice FAISS, deve retornar mensagem de aviso."""
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

    def test_root_retorna_status_online(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "online"

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
