CREATE TABLE IF NOT EXISTS research_documents (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    publication_date DATE,
    version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('text/plain', 'application/pdf')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_sha256, version)
);

CREATE TABLE IF NOT EXISTS research_document_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    embedding JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_research_chunks_document
    ON research_document_chunks (document_id, chunk_index);

CREATE TABLE IF NOT EXISTS research_conversations (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    title TEXT NOT NULL DEFAULT 'New conversation',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_research_conversations_owner
    ON research_conversations (owner_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL
        REFERENCES research_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_research_messages_conversation
    ON research_messages (conversation_id, id);
