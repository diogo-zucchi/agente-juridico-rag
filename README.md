# Agente Jurídico Inteligente — RAG

TCC — Engenharia de Software — UTFPR Dois Vizinhos — 2026
Autor: Diogo Eduardo Ferrari Zucchi
Orientador: Prof. Dr. Francisco Carlos Souza

Sistema de consulta jurídica em linguagem natural. O usuário indexa documentos jurídicos e faz perguntas; o sistema recupera os trechos mais relevantes por busca semântica e gera uma resposta fundamentada citando as fontes, permitindo verificar a procedência de cada informação.

O sistema também inclui um **instrumento de comparação às cegas** entre modelos de linguagem, usado durante o desenvolvimento para fundamentar a escolha do modelo. Esse instrumento não faz parte do fluxo destinado ao usuário final.

---

## Modelos de linguagem

A geração das respostas usa o padrão de API compatível com a OpenAI, de modo que a troca de modelo se resume a alterar a URL base, a credencial e o nome do modelo. Três modelos estão integrados:

| Provedor | Modelo | Papel |
|----------|--------|-------|
| Maritaca | `sabia-4` | **Modelo da ferramenta** (produção) — brasileiro, com pré-treino em português e legislação jurídica. |
| DeepSeek | `deepseek-chat` | Apenas para o estudo comparativo às cegas. |
| OpenAI | `gpt-4o-mini` | Apenas para o estudo comparativo às cegas. |

A ferramenta opera com o **Sabiá**; DeepSeek e GPT foram integrados exclusivamente para fundamentar a escolha do modelo na etapa de validação.

---

## Arquitetura

- **Frontend:** página única em HTML, CSS e JavaScript (`frontend/index.html`), consumindo a API por requisições assíncronas.
- **Backend:** Python 3.11 + FastAPI, organizado em camadas (rotas → serviços → persistência).
- **Persistência:** PostgreSQL (dados estruturados) + índice vetorial FAISS em disco (busca por similaridade).
- **Embeddings:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (suporte a português, execução local).

O texto fica no banco relacional e os vetores no índice FAISS, ligados por um arquivo de mapeamento que relaciona cada posição do índice ao `id` do chunk no banco (ver "Persistência do índice").

---

## Pré-requisitos

- Python 3.11
- Docker Desktop

---

## Instalação

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows (PowerShell)
# source .venv/bin/activate    # Linux/macOS
pip install -r requirements.txt
```

---

## Configuração

Crie um arquivo `.env` na raiz do projeto com o seguinte conteúdo (substitua as chaves pelas suas):

```env
# ── Banco de dados ───────────────────────────────────────
DATABASE_URL=postgresql+psycopg://postgres:senha@localhost:5432/agente_juridico
POSTGRES_USER=postgres
POSTGRES_PASSWORD=senha
POSTGRES_DB=agente_juridico

# ── Modelo da ferramenta (produção) ──────────────────────
MARITACA_API_KEY=sua_chave_maritaca
MARITACA_MODEL=sabia-4

# ── Modelos do estudo comparativo (avaliação às cegas) ───
DEEPSEEK_API_KEY=sua_chave_deepseek
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com

OPENAI_API_KEY=sua_chave_openai
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1

# ── Embeddings e índice vetorial ─────────────────────────
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
FAISS_INDEX_PATH=./backend/data/faiss_index

# ── API ──────────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=true

# ── Recuperação e fragmentação ───────────────────────────
TOP_K_RESULTS=5
CHUNK_SIZE=512
CHUNK_OVERLAP=50

# ── Logs ─────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_FILE=./logs/agente.log
```

> As credenciais de DeepSeek e OpenAI só são necessárias para reproduzir o estudo comparativo às cegas. Para o uso normal da ferramenta, basta `MARITACA_API_KEY`.

---

## Execução

1. Subir o banco de dados:

```bash
docker compose up -d postgres
```

2. Iniciar a API (dentro da pasta `backend/`):

```bash
cd backend
python -m uvicorn app.main:app --reload
```

3. Abrir a interface, de uma das formas:
   - acesse `http://localhost:8000/` (a API serve o `index.html` na raiz); ou
   - abra o arquivo `frontend/index.html` diretamente no navegador.

Documentação interativa da API (Swagger): `http://localhost:8000/docs`.

> Alternativa: `docker compose up` sobe banco e backend juntos (serviço `backend` no `docker-compose.yml`).

---

## Uso

- **Indexar um documento:** use a área de upload na interface e selecione um arquivo PDF, TXT ou HTML, informando um título (e, opcionalmente, um nível de dificuldade usado apenas no experimento).
- **Consultar:** digite a pergunta jurídica e clique em Consultar. A resposta vem acompanhada das fontes utilizadas e seus escores de similaridade.
- **Comparar modelos (estudo):** na aba de avaliação, a mesma pergunta é respondida por todos os modelos sobre o mesmo contexto; as respostas são embaralhadas e exibidas como Resposta A, B, C, sem identificar o modelo, para avaliação às cegas com nota de 1 a 5.

Indexação em lote (todos os arquivos de uma pasta):

```bash
python scripts/indexar_documentos.py --pasta ./data/raw --fonte-id 1
```

---

## Endpoints principais

Prefixo: `/api/v1`

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/consultar` | Consulta com um modelo (padrão: Maritaca). |
| `POST` | `/comparar` | Gera respostas de todos os modelos sobre o mesmo contexto (às cegas). |
| `POST` | `/avaliar` | Registra a nota (1 a 5) de uma resposta. |
| `GET`  | `/resultados` | Consolida as notas por modelo e por nível de dificuldade. |
| `GET`  | `/resultados/csv` | Exporta as avaliações em CSV. |
| `POST` | `/ingerir` | Indexa um documento enviado. |
| `GET`  | `/documentos` | Lista os documentos indexados. |
| `GET`  | `/historico` | Histórico de consultas. |

---

## Persistência do índice

O índice FAISS é mantido em disco junto a um arquivo de mapeamento:

- `backend/data/faiss_index` — índice FAISS (`IndexFlatIP`, similaridade por produto interno sobre embeddings normalizados), gravado com `faiss.write_index`.
- `backend/data/faiss_index.ids.json` — **arquivo de mapeamento**: lista de `id`s dos chunks no PostgreSQL na mesma ordem dos vetores. Como o `IndexFlatIP` devolve apenas a posição do vetor na busca (0, 1, 2…), esse arquivo traduz a posição retornada pelo FAISS no registro correto do banco.

Ambos são gravados e recarregados em conjunto para manter a coerência entre o texto (no banco) e os vetores (no índice).

---

## Testes

```bash
cd backend
pytest tests/ -v
```

A suíte cobre fragmentação de texto, leitura de arquivos, integridade (hash anti-duplicação), serviço de recuperação/geração e rotas da API, usando mocks para o banco e os serviços externos.
