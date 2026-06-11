-- ============================================================
-- Migração v2 — Suporte a múltiplas LLMs e avaliação
-- Rode este script UMA vez se o banco já existia antes da
-- funcionalidade de comparação/avaliação.
-- (Para um banco novo, o init_db.sql já contém tudo.)
-- ============================================================

-- Coluna que identifica qual LLM gerou cada resposta
ALTER TABLE respostas
    ADD COLUMN IF NOT EXISTS modelo_llm VARCHAR(50);

-- Rótulo de dificuldade do documento (experimento)
ALTER TABLE documentos
    ADD COLUMN IF NOT EXISTS nivel_dificuldade VARCHAR(20);

-- Documento usado em cada consulta (quando a busca é restrita)
ALTER TABLE consultas
    ADD COLUMN IF NOT EXISTS id_documento INTEGER
        REFERENCES documentos(id) ON DELETE SET NULL;

-- Tabela de avaliações (nota de 1 a 5 por resposta)
CREATE TABLE IF NOT EXISTS avaliacoes (
    id          SERIAL PRIMARY KEY,
    id_resposta INTEGER REFERENCES respostas(id) ON DELETE CASCADE,
    nota        INTEGER NOT NULL CHECK (nota BETWEEN 1 AND 5),
    comentario  TEXT,
    avaliador   VARCHAR(255),
    data_hora   TIMESTAMP DEFAULT NOW()
);
