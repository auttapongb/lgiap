"""LGIAP — Database Initialization"""
import os, sys
import psycopg2

DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/lgiap")

SQL = """
CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    line_group_id VARCHAR(255) UNIQUE NOT NULL,
    group_name VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    archive_enabled BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    line_user_id VARCHAR(255) UNIQUE NOT NULL,
    display_names JSONB DEFAULT '[]'::jsonb,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS group_members (
    id SERIAL PRIMARY KEY,
    group_id INT REFERENCES groups(id),
    user_id INT REFERENCES users(id),
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    left_at TIMESTAMPTZ,
    UNIQUE(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    line_message_id VARCHAR(255) UNIQUE NOT NULL,
    group_id VARCHAR(255),
    user_id VARCHAR(255),
    message_type VARCHAR(50) NOT NULL,
    text_content TEXT DEFAULT '',
    raw_event_json JSONB DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    is_unsent BOOLEAN DEFAULT FALSE,
    ai_rating INT DEFAULT -1,
    ai_topic VARCHAR(300),
    embedding vector(1024)
);

CREATE INDEX IF NOT EXISTS idx_messages_group_time ON messages(group_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(message_type);
CREATE INDEX IF NOT EXISTS idx_messages_rating ON messages(ai_rating) WHERE ai_rating >= 0;
CREATE INDEX IF NOT EXISTS idx_messages_topic ON messages(ai_topic) WHERE ai_topic IS NOT NULL;

CREATE TABLE IF NOT EXISTS media_assets (
    id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(id),
    media_type VARCHAR(50),
    original_filename VARCHAR(500),
    storage_url TEXT,
    file_size BIGINT,
    mime_type VARCHAR(200),
    download_status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS links (
    id SERIAL PRIMARY KEY,
    message_id INT REFERENCES messages(id),
    url TEXT NOT NULL,
    domain VARCHAR(300),
    title VARCHAR(500),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id SERIAL PRIMARY KEY,
    group_id VARCHAR(255) NOT NULL,
    summary_date DATE NOT NULL,
    summary_text TEXT,
    key_topics JSONB DEFAULT '[]'::jsonb,
    decisions JSONB DEFAULT '[]'::jsonb,
    action_items JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id, summary_date)
);

INSERT INTO groups (line_group_id, group_name)
VALUES ('default', 'Default Group')
ON CONFLICT (line_group_id) DO NOTHING;

DO $$ BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector extension not available — embeddings disabled';
END $$;
"""

def init_db():
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        cur.execute(SQL)
        conn.commit()
        print("✅ Database initialized successfully")
        
        # Verify pgvector
        cur.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')")
        has_vector = cur.fetchone()[0]
        if has_vector:
            print("✅ pgvector extension available")
        else:
            print("⚠️  pgvector NOT available — embeddings column created but won't work")
            
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        table_count = cur.fetchone()[0]
        print(f"✅ {table_count} tables created")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Database init failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
