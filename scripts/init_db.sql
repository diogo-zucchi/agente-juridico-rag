-- ============================================================
-- Inicialização do Banco de Dados - Agente Jurídico RAG
-- ============================================================

-- Habilita a extensão pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- --------------------------------------------------------
-- Tabela: FONTES
-- Origem dos documentos (tribunal, legislação, etc.)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS fontes (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(255) NOT NULL,
    tipo      VARCHAR(100) NOT NULL,  -- ex: 'STJ', 'STF', 'legislação', 'súmula'
    url_base  TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

-- --------------------------------------------------------
-- Tabela: DOCUMENTOS
-- Documentos jurídicos indexados
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS documentos (
    id              SERIAL PRIMARY KEY,
    titulo          VARCHAR(500) NOT NULL,
    texto           TEXT NOT NULL,
    data_publicacao DATE,
    id_fonte        INTEGER REFERENCES fontes(id) ON DELETE SET NULL,
    hash_integridade VARCHAR(64) UNIQUE,  -- SHA-256 para evitar duplicatas
    arquivo_origem  VARCHAR(500),
    criado_em       TIMESTAMP DEFAULT NOW()
);

-- --------------------------------------------------------
-- Tabela: CHUNKS
-- Trechos dos documentos com seus embeddings vetoriais
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    id_documento INTEGER REFERENCES documentos(id) ON DELETE CASCADE,
    texto_chunk  TEXT NOT NULL,
    indice_chunk INTEGER NOT NULL,        -- posição do chunk no doc
    embedding    vector(384),             -- dimensão do modelo MiniLM (384)
    criado_em    TIMESTAMP DEFAULT NOW()
);

-- Índice vetorial para busca por similaridade (cosine)
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- --------------------------------------------------------
-- Tabela: CONSULTAS
-- Perguntas feitas pelos usuários
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS consultas (
    id         SERIAL PRIMARY KEY,
    pergunta   TEXT NOT NULL,
    data_hora  TIMESTAMP DEFAULT NOW(),
    id_resposta INTEGER  -- será preenchido após gerar resposta
);

-- --------------------------------------------------------
-- Tabela: RESPOSTAS
-- Respostas geradas pelo LLM
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS respostas (
    id             SERIAL PRIMARY KEY,
    texto_resposta TEXT NOT NULL,
    data_hora      TIMESTAMP DEFAULT NOW(),
    id_consulta    INTEGER REFERENCES consultas(id) ON DELETE CASCADE
);

-- Atualiza FK de consultas -> respostas
ALTER TABLE consultas
    ADD CONSTRAINT fk_consulta_resposta
    FOREIGN KEY (id_resposta) REFERENCES respostas(id) ON DELETE SET NULL;

-- --------------------------------------------------------
-- Tabela: RESPOSTA_DOCUMENTO
-- Quais documentos/chunks embasaram cada resposta
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS resposta_documento (
    id          SERIAL PRIMARY KEY,
    id_resposta INTEGER REFERENCES respostas(id) ON DELETE CASCADE,
    id_chunk    INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    score       FLOAT,   -- score de similaridade
    criado_em   TIMESTAMP DEFAULT NOW()
);

-- --------------------------------------------------------
-- Dados iniciais de fontes jurídicas
-- --------------------------------------------------------
INSERT INTO fontes (nome, tipo, url_base) VALUES
    ('Superior Tribunal de Justiça', 'STJ', 'https://www.stj.jus.br'),
    ('Supremo Tribunal Federal', 'STF', 'https://portal.stf.jus.br'),
    ('Planalto - Legislação Federal', 'legislação', 'https://www.planalto.gov.br'),
    ('Tribunal Superior do Trabalho', 'TST', 'https://www.tst.jus.br')
ON CONFLICT DO NOTHING;
