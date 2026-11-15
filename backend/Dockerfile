# Build a partir da raiz do repositório (contexto "."):
#   docker build -f backend/Dockerfile .
FROM python:3.13-slim

WORKDIR /app/backend

# Dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Dependências Python
# torch só para CPU: evita baixar as bibliotecas CUDA (vários GB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Mesma estrutura do repositório: a API serve ../frontend/index.html
COPY backend /app/backend
COPY frontend /app/frontend

# Diretórios necessários
RUN mkdir -p /app/backend/logs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
