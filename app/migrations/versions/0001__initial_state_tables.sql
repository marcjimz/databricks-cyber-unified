-- 0001__initial_state_tables.sql
-- Initial app-owned state schema: per-user preferences, Genie chat history,
-- and lightweight session records. Extracted from the former startup bootstrap
-- in core/state.py so schema changes are versioned files, not code edits.
--
-- Runs inside the app-owned state schema (search_path is pinned to it), so the
-- unqualified object names below land there. Forward-only; do not edit this
-- file after it has been applied -- add a new NNNN__*.sql instead.

CREATE TABLE IF NOT EXISTS cyber360_preferences (
    user_email        TEXT PRIMARY KEY,
    theme             TEXT NOT NULL DEFAULT 'light',
    reporting_period  INTEGER NOT NULL DEFAULT 30,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cyber360_chats (
    chat_id     TEXT PRIMARY KEY,
    user_email  TEXT NOT NULL,
    domain      TEXT,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cyber360_sessions (
    session_id  TEXT PRIMARY KEY,
    user_email  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cyber360_chats_user
    ON cyber360_chats (user_email, created_at);

CREATE INDEX IF NOT EXISTS idx_cyber360_sessions_user
    ON cyber360_sessions (user_email);
