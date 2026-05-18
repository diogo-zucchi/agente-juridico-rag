Agente Jurídico Inteligente — RAG
TCC — Engenharia de Software — UTFPR Dois Vizinhos — 2026
Orientador: Prof. Dr. Francisco Carlos Souza

Sistema de consulta jurídica em linguagem natural. O usuário indexa documentos (leis, acórdãos, súmulas) e faz perguntas; o sistema recupera os trechos mais relevantes e gera uma resposta fundamentada citando as fontes.


PRÉ-REQUISITOS

- Python 3.11
- Docker Desktop


INSTALAÇÃO

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt


CONFIGURAÇÃO

Crie um arquivo .env na raiz do projeto com o mesmo conteúdo:

DATABASE_URL=postgresql+psycopg://postgres:senha@localhost:5432/agente_juridico
POSTGRES_USER=postgres
POSTGRES_PASSWORD=senha
POSTGRES_DB=agente_juridico
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
MARITACA_API_KEY=110882663383945948606_f9c19f4c2ce168ff
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

EXECUÇÃO

1. Subir o banco:
docker compose up -d postgres

2. Iniciar a API (dentro da pasta backend/):
python -m uvicorn app.main:app --reload

3. Abrir a interface:
Abra o arquivo frontend/index.html no navegador.


USO

Para indexar um documento, use a área de upload na interface e selecione um arquivo PDF, TXT ou HTML.
Para consultar, digite a pergunta jurídica e clique em Consultar.


TESTES

cd backend
pytest tests/ -v

Projeto acadêmico — UTFPR Dois Vizinhos — Uso educacional
