# Agente Jurídico Inteligente — RAG

TCC — Engenharia de Software — UTFPR Dois Vizinhos — 2026

Orientador: Prof. Dr. Francisco Carlos Souza

Sistema de consulta jurídica em linguagem natural. O usuário indexa documentos jurídicos e faz perguntas; o sistema recupera os trechos mais relevantes e gera uma resposta fundamentada citando as fontes.

---

## Pré-requisitos

- Python 3.11
- Docker Desktop

---

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Configuração

Crie um arquivo `.env` na raiz do projeto com o seguinte conteúdo:

```ini
DATABASE_URL=postgresql+psycopg://postgres:senha@localhost:5432/agente_juridico
POSTGRES_USER=postgres
POSTGRES_PASSWORD=senha
POSTGRES_DB=agente_juridico
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
MARITACA_API_KEY=sua_chave_aqui
MARITACA_MODEL=sabia-4
GEMINI_API_KEY=sua_chave_gemini_aqui
GEMINI_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
FAISS_INDEX_PATH=caminho_absoluto\backend\data\faiss_index
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=true
TOP_K_RESULTS=5
CHUNK_SIZE=512
CHUNK_OVERLAP=50
LOG_LEVEL=INFO
LOG_FILE=./logs/agente.log
```

---

## Execução

1. Subir o banco:

```powershell
docker compose up -d postgres
```

2. Iniciar a API (dentro da pasta `backend/`):

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

3. Abrir a interface: abra o arquivo `frontend/index.html` no navegador.

---

## Uso

Para indexar um documento, use a área de upload na interface e selecione um arquivo PDF, TXT ou HTML.

Para consultar, digite a pergunta jurídica e clique em Consultar.

---

## Testes

```powershell
cd backend
pytest tests/ -v
```