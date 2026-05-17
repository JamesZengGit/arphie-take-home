-- Document Q&A Database Schema
-- Adapted from align-knowledge for personal document processing
-- PostgreSQL with pgvector extension for hybrid retrieval

-- Enable pgvector extension for embedding storage
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop tables if they exist (for clean reinstall)
DROP TABLE IF EXISTS document_relationships CASCADE;
DROP TABLE IF EXISTS information_gaps CASCADE;
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;

-- Documents table - stores uploaded files
CREATE TABLE documents (
    document_id SERIAL PRIMARY KEY,
    external_document_id VARCHAR(255) UNIQUE NOT NULL, -- String ID for API/Redis mapping
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    content_type VARCHAR(50) NOT NULL, -- 'pdf', 'markdown', 'text'
    file_size INTEGER,
    total_chunks INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Document chunks table - stores processed text chunks with entities
CREATE TABLE document_chunks (
    chunk_id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL, -- Order within document
    chunk_text TEXT NOT NULL,
    page_number INTEGER, -- For PDFs
    section_header TEXT, -- For structured documents

    -- Extracted entities (JSONB for flexibility)
    entities JSONB, -- {"people": [...], "dates": [...], "topics": [...], "file_refs": [...]}
    entity_extraction_status VARCHAR(20) DEFAULT 'pending' CHECK (entity_extraction_status IN ('pending', 'extracted', 'failed')),

    -- Embeddings for semantic search
    embedding vector(768), -- 768-dimensional embeddings from sentence-transformers
    embedding_status VARCHAR(20) DEFAULT 'pending' CHECK (embedding_status IN ('pending', 'embedded', 'stale', 'failed')),

    -- Full-text search vector
    search_vector tsvector,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX idx_documents_external_id ON documents (external_document_id);
CREATE INDEX idx_documents_content_type ON documents (content_type);
CREATE INDEX idx_documents_created_at ON documents (created_at DESC);

CREATE INDEX idx_chunks_document_id ON document_chunks (document_id);
CREATE INDEX idx_chunks_page_number ON document_chunks (page_number);
CREATE INDEX idx_chunks_entity_status ON document_chunks (entity_extraction_status);
CREATE INDEX idx_chunks_embedding_status ON document_chunks (embedding_status);

-- JSONB indexes for entity search
CREATE INDEX idx_chunks_entities ON document_chunks USING GIN (entities);

-- Full-text search indexes
CREATE INDEX idx_chunks_search_vector ON document_chunks USING GIN (search_vector);

-- pgvector index for semantic similarity search (created after embeddings are populated)
CREATE INDEX idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Performance indexes for complex queries
CREATE INDEX idx_chunks_entities_specific ON document_chunks USING GIN ((entities->'people'), (entities->'topics'), (entities->'dates'), (entities->'file_refs'));
CREATE INDEX idx_chunks_doc_entity_status ON document_chunks (document_id, entity_extraction_status);
CREATE INDEX idx_chunks_search_created ON document_chunks (created_at DESC) WHERE search_vector IS NOT NULL;

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers to automatically update updated_at
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE
    ON documents FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

CREATE TRIGGER update_chunks_updated_at BEFORE UPDATE
    ON document_chunks FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- Comments for documentation
COMMENT ON TABLE documents IS 'Uploaded documents with metadata';
COMMENT ON TABLE document_chunks IS 'Text chunks from documents with extracted entities and embeddings';
COMMENT ON COLUMN document_chunks.entities IS 'JSON object containing extracted entities';
COMMENT ON COLUMN document_chunks.embedding IS '768-dimensional vector from sentence-transformers';

-- Information gaps table - detect missing coverage
CREATE TABLE information_gaps (
    gap_id VARCHAR(50) PRIMARY KEY,
    type VARCHAR(50) DEFAULT 'missing_information',
    severity VARCHAR(20) CHECK (severity IN ('critical', 'warning', 'info')),
    description TEXT,
    document_id INTEGER REFERENCES documents(document_id),
    missing_topics TEXT[],
    suggested_documents INTEGER[],
    created_at TIMESTAMP DEFAULT NOW()
);

-- Document relationships table - cross-document connections
CREATE TABLE document_relationships (
    relationship_id SERIAL PRIMARY KEY,
    source_document_id INTEGER REFERENCES documents(document_id),
    target_document_id INTEGER REFERENCES documents(document_id),
    relationship_type VARCHAR(30) CHECK (relationship_type IN ('REFERENCES', 'SIMILAR_TOPICS', 'CONTRADICTS')),
    confidence FLOAT CHECK (confidence >= 0.0 AND confidence <= 1.0),
    shared_entities JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Gap and relationship indexes
CREATE INDEX idx_gaps_document ON information_gaps (document_id);
CREATE INDEX idx_gaps_type ON information_gaps (type);
CREATE INDEX idx_relationships_source ON document_relationships (source_document_id);
CREATE INDEX idx_relationships_target ON document_relationships (target_document_id);
CREATE INDEX idx_relationships_type ON document_relationships (relationship_type);

-- Function to update search_vector automatically
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        COALESCE(NEW.chunk_text, '') || ' ' ||
        COALESCE(NEW.section_header, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update search_vector
CREATE TRIGGER update_chunks_search_vector
    BEFORE INSERT OR UPDATE ON document_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_search_vector();

COMMENT ON TABLE information_gaps IS 'Detected information gaps and missing coverage';
COMMENT ON TABLE document_relationships IS 'Cross-document relationships and connections';
COMMENT ON COLUMN document_chunks.search_vector IS 'Full-text search vector for PostgreSQL search';