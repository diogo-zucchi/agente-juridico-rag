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


class TestChunking:
    def test_texto_curto_retorna_um_chunk(self):
        texto = "Este é um texto curto para teste."
        chunks = _dividir_em_chunks(texto)
        assert len(chunks) >= 1
        assert chunks[0] == texto

    def test_texto_longo_gera_multiplos_chunks(self):
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


# Formato do texto compilado do Planalto: todas as redações em ordem cronológica
LEI_EXEMPLO = """LEI Nº 1, DE 1 DE JANEIRO DE 2000

Dispõe sobre testes.

CAPÍTULO I

Das Disposições Gerais

Art. 1º Texto original do artigo primeiro.

Art. 1º Texto vigente do artigo primeiro.     (Redação dada pela Lei nº 2, de 2001)

Art. 2º São dependentes:

I - o cônjuge;

I - o cônjuge e o companheiro;     (Redação dada pela Lei nº 3, de 2002)

II - os pais;

III - a pessoa designada.     (Revogada pela Lei nº 4, de 2003)

§ 1º O inciso abaixo é do parágrafo:

I - inciso do parágrafo;

Art. 3º Abono anual.

Parágrafo único. Versão original.

Parágrafo único. Versão da medida provisória:     (Vigência encerrada)

I - inciso trazido pela medida provisória;

Parágrafo único. Versão original.

Art. 4º Artigo revogado inteiro.     (Revogado pela Lei nº 6, de 2004)

§ 1º Parágrafo do artigo revogado.     (Revogado pela Lei nº 6, de 2004)

Art. 5º Esta Lei entra em vigor na data de sua publicação,
continuando em outra linha.

Brasília, 1 de janeiro de 2000.

FULANO DE TAL
"""


class TestTextoLegal:
    @pytest.fixture
    def artigos(self):
        from app.services.texto_legal import extrair_artigos
        artigos, _ = extrair_artigos(LEI_EXEMPLO)
        return {a[0].split()[1]: a for a in artigos}

    def test_reconhece_texto_legal(self):
        from app.services.texto_legal import eh_texto_legal
        assert eh_texto_legal(LEI_EXEMPLO)
        assert not eh_texto_legal("Um parecer qualquer.\n\nSem artigos.")

    def test_mantem_so_a_redacao_vigente(self, artigos):
        assert artigos["1º"] == [
            "Art. 1º Texto vigente do artigo primeiro. (Redação dada pela Lei nº 2, de 2001)"
        ]

    def test_revogado_vira_rotulo_e_nota(self, artigos):
        assert "III - (Revogada pela Lei nº 4, de 2003)" in artigos["2º"]

    def test_incisos_de_pais_diferentes_nao_colidem(self, artigos):
        assert artigos["2º"] == [
            "Art. 2º São dependentes:",
            "I - o cônjuge e o companheiro; (Redação dada pela Lei nº 3, de 2002)",
            "II - os pais;",
            "III - (Revogada pela Lei nº 4, de 2003)",
            "§ 1º O inciso abaixo é do parágrafo:",
            "I - inciso do parágrafo;",
        ]

    def test_redacao_substituida_leva_os_filhos(self, artigos):
        # a redação da MP (com inciso) perdeu a vigência e a original voltou
        assert artigos["3º"] == ["Art. 3º Abono anual.", "Parágrafo único. Versão original."]

    def test_artigo_revogado_descarta_os_filhos(self, artigos):
        assert artigos["4º"] == ["Art. 4º (Revogado pela Lei nº 6, de 2004)"]

    def test_continuacao_titulos_e_epilogo(self, artigos):
        from app.services.texto_legal import extrair_artigos
        _, fora = extrair_artigos(LEI_EXEMPLO)
        assert artigos["5º"] == [
            "Art. 5º Esta Lei entra em vigor na data de sua publicação, continuando em outra linha."
        ]
        tudo = "\n".join(l for a in artigos.values() for l in a)
        assert "CAPÍTULO" not in tudo and "Disposições Gerais" not in tudo
        assert "FULANO" not in tudo
        assert "Dispõe sobre testes." in fora

    def test_chunks_nao_misturam_artigos(self):
        import re
        chunks = _dividir_em_chunks(LEI_EXEMPLO)
        for chunk in chunks:
            assert len(re.findall(r"^Art\. \d", chunk, re.M)) <= 1
        assert "Art. 1º Texto original do artigo primeiro." not in "\n".join(chunks)

    def test_artigo_longo_repete_o_caput(self):
        from app.services.texto_legal import dividir_artigo
        caput = "Art. 9º São requisitos do benefício:"
        incisos = [f"{n} - requisito número {n} " + "x" * 90 for n in "I II III IV V VI VII VIII".split()]
        chunks = dividir_artigo([caput] + incisos, 512, 50)

        assert len(chunks) > 1
        assert all(len(c) <= 512 for c in chunks)
        assert all(c.startswith(caput) for c in chunks)
        for inciso in incisos:
            assert sum(inciso in c for c in chunks) == 1

    def test_dispositivo_maior_que_o_chunk_e_fatiado(self):
        from app.services.texto_legal import dividir_artigo
        caput = "Art. 9º Caput curto."
        longo = "§ 1º " + " ".join(f"palavra{i}" for i in range(300))
        chunks = dividir_artigo([caput, longo], 512, 50)

        assert all(len(c) <= 512 for c in chunks)
        assert all(c.startswith(caput) for c in chunks)
        assert "palavra299" in chunks[-1]
        # o corte acontece entre palavras
        assert all(c.split("\n", 1)[1].split()[0].startswith(("§", "palavra")) for c in chunks)

    def test_juntar_artigo_desfaz_a_divisao(self):
        from app.services.texto_legal import dividir_artigo, juntar_artigo, rotulo_do_artigo
        caput = "Art. 10. São requisitos do benefício:"
        incisos = [f"{n} - requisito número {n} " + "x" * 90 for n in "I II III IV V VI".split()]
        chunks = dividir_artigo([caput] + incisos, 512, 50)

        assert len(chunks) > 1
        assert {rotulo_do_artigo(c) for c in chunks} == {"Art. 10."}
        assert juntar_artigo(chunks) == "\n".join([caput] + incisos)

    def test_rotulo_do_artigo(self):
        from app.services.texto_legal import rotulo_do_artigo
        assert rotulo_do_artigo("Art. 29-A. O INSS ...") == "Art. 29-A."
        assert rotulo_do_artigo("Art. 152 (Revogado pela Lei nº 9.528, de 1997)") == "Art. 152"
        assert rotulo_do_artigo("Parágrafo solto") is None

    def test_lei_8213_art_16_so_com_redacao_vigente(self):
        from pathlib import Path
        arquivo = (Path(__file__).resolve().parents[2]
                   / "leis-e-perguntas-avaliacao" / "lei_8213_91_dificil.txt")
        if not arquivo.exists():
            pytest.skip("arquivo de avaliação ausente")

        chunks = _dividir_em_chunks(arquivo.read_text(encoding="utf-8"))
        art16 = [c for c in chunks if c.startswith("Art. 16.")]
        texto = "\n".join(art16)

        assert art16
        assert "ou deficiência grave" in texto
        assert "IV - (Revogada pela Lei nº 9.032, de 1995)" in texto
        # redação original do inciso I (de 1991) não pode sobrar
        assert "filho, de qualquer condição, menor de 21 (vinte e um) anos ou inválido;" not in texto
        # o caput não fica mais colado no fim do Art. 15
        assert not any("Art. 15" in c and "Art. 16." in c for c in chunks)


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
        # o score volta positivo
        assert resultado == [(chunk_mock, pytest.approx(0.82))]

    def test_filtra_por_documento_no_banco(self):
        _, _, sql = self._buscar(id_documento=7)
        assert "chunks.id_documento =" in sql


class TestRagService:
    def test_recuperar_chunks_repassa_documento_e_scores(self):
        from app.services import rag_service

        chunk = MagicMock()
        chunk.id = 10
        chunk.id_documento = 3
        chunk.texto_chunk = "Parecer sem artigos."
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
            "texto_chunk": "Parecer sem artigos.",
            "score": 0.9,
        }]

    def _chunk(self, id_, texto):
        chunk = MagicMock()
        chunk.id, chunk.id_documento, chunk.texto_chunk = id_, 3, texto
        return chunk

    def test_recuperar_chunks_entrega_o_artigo_inteiro_uma_vez(self):
        from app.services import rag_service

        caput = "Art. 16. São beneficiários, na condição de dependentes do segurado:"
        artigo = f"{caput}\nI - o cônjuge;\n§ 5º Prova de união estável."
        resultados = [
            (self._chunk(1, f"{caput}\n§ 5º Prova de união estável."), 0.8),
            (self._chunk(2, f"{caput}\nI - o cônjuge;"), 0.7),
            (self._chunk(3, "Art. 17. Outro artigo."), 0.6),
        ]
        with patch("app.services.rag_service.buscar_chunks", return_value=resultados), \
             patch("app.services.rag_service.texto_do_artigo",
                   side_effect=lambda db, doc, rotulo: artigo if rotulo == "Art. 16." else "Art. 17. Outro artigo.") as remonta:
            fontes = rag_service._recuperar_chunks(MagicMock(), "dependentes", 5)

        assert [f["texto_chunk"] for f in fontes] == [artigo, "Art. 17. Outro artigo."]
        assert [f["score"] for f in fontes] == [0.8, 0.6]
        assert remonta.call_args_list[0].args[1:] == (3, "Art. 16.")

    def test_artigo_grande_demais_fica_so_o_chunk(self):
        from app.services import rag_service

        chunk = self._chunk(1, "Art. 11. São segurados obrigatórios:\nI - como empregado;")
        with patch("app.services.rag_service.buscar_chunks", return_value=[(chunk, 0.8)]), \
             patch("app.services.rag_service.texto_do_artigo", return_value="x" * 10_000):
            fontes = rag_service._recuperar_chunks(MagicMock(), "segurados", 5)

        assert fontes[0]["texto_chunk"] == chunk.texto_chunk

    def test_responder_sem_documentos_indexados(self):
        """Sem chunks indexados, deve retornar mensagem de aviso."""
        from app.services import rag_service
        from app.services.ingestao_service import buscar_chunks

        db_mock = MagicMock()
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
