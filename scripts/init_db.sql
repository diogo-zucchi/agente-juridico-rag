CREATE EXTENSION IF NOT EXISTS vector;

-- Origem dos documentos (tribunal, legislação, etc.)
CREATE TABLE IF NOT EXISTS fontes (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(255) NOT NULL,
    tipo      VARCHAR(100) NOT NULL,  -- ex: 'STJ', 'STF', 'legislação', 'súmula'
    url_base  TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documentos (
    id              SERIAL PRIMARY KEY,
    titulo          VARCHAR(500) NOT NULL,
    texto           TEXT NOT NULL,
    data_publicacao DATE,
    nivel_dificuldade VARCHAR(20),   -- 'facil', 'medio' ou 'dificil' (experimento)
    id_fonte        INTEGER REFERENCES fontes(id) ON DELETE SET NULL,
    hash_integridade VARCHAR(64) UNIQUE,  -- SHA-256 para evitar duplicatas
    arquivo_origem  VARCHAR(500),
    criado_em       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    id_documento INTEGER REFERENCES documentos(id) ON DELETE CASCADE,
    texto_chunk  TEXT NOT NULL,
    indice_chunk INTEGER NOT NULL,
    embedding    vector(384),             -- dimensão do MiniLM (EMBEDDING_DIM)
    criado_em    TIMESTAMP DEFAULT NOW()
);

-- Sem índice vetorial: com poucos milhares de chunks a busca exata é rápida
-- e determinística.

CREATE INDEX IF NOT EXISTS chunks_id_documento_idx ON chunks (id_documento);

CREATE TABLE IF NOT EXISTS consultas (
    id         SERIAL PRIMARY KEY,
    pergunta   TEXT NOT NULL,
    data_hora  TIMESTAMP DEFAULT NOW(),
    id_resposta INTEGER,
    id_documento INTEGER REFERENCES documentos(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS respostas (
    id             SERIAL PRIMARY KEY,
    texto_resposta TEXT NOT NULL,
    modelo_llm     VARCHAR(50),
    data_hora      TIMESTAMP DEFAULT NOW(),
    id_consulta    INTEGER REFERENCES consultas(id) ON DELETE CASCADE
);

-- consultas e respostas se referenciam: esta FK só pode vir depois das duas tabelas
ALTER TABLE consultas
    ADD CONSTRAINT fk_consulta_resposta
    FOREIGN KEY (id_resposta) REFERENCES respostas(id) ON DELETE SET NULL;

-- Chunks que embasaram cada resposta
CREATE TABLE IF NOT EXISTS resposta_documento (
    id          SERIAL PRIMARY KEY,
    id_resposta INTEGER REFERENCES respostas(id) ON DELETE CASCADE,
    id_chunk    INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    score       FLOAT,
    criado_em   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS avaliacoes (
    id          SERIAL PRIMARY KEY,
    id_resposta INTEGER REFERENCES respostas(id) ON DELETE CASCADE,
    nota        INTEGER NOT NULL CHECK (nota BETWEEN 1 AND 5),
    comentario  TEXT,
    avaliador   VARCHAR(255),
    data_hora   TIMESTAMP DEFAULT NOW()
);

INSERT INTO fontes (nome, tipo, url_base) VALUES
    ('Superior Tribunal de Justiça', 'STJ', 'https://www.stj.jus.br'),
    ('Supremo Tribunal Federal', 'STF', 'https://portal.stf.jus.br'),
    ('Planalto - Legislação Federal', 'legislação', 'https://www.planalto.gov.br'),
    ('Tribunal Superior do Trabalho', 'TST', 'https://www.tst.jus.br')
ON CONFLICT DO NOTHING;
