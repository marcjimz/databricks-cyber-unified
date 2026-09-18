-- 0002__rename_state_tables_cyber_unified.sql
-- Rename the app-owned state tables cyber360_* -> cyber_unified_* as part of the
-- CyberUnified rebrand. 0001 is already applied on deployed targets and is
-- forward-only/immutable, so the rename lands here instead of being edited in.
--
-- Idempotent + safe on a FRESH database, where 0001 already created the tables
-- under the old names and this file renames them; and on an ALREADY-RENAMED
-- database, where the guards make every statement a no-op. Runs inside the
-- app-owned state schema (search_path is pinned to it).

DO $mig$
BEGIN
    IF to_regclass('cyber360_preferences') IS NOT NULL
       AND to_regclass('cyber_unified_preferences') IS NULL THEN
        ALTER TABLE cyber360_preferences RENAME TO cyber_unified_preferences;
    END IF;

    IF to_regclass('cyber360_chats') IS NOT NULL
       AND to_regclass('cyber_unified_chats') IS NULL THEN
        ALTER TABLE cyber360_chats RENAME TO cyber_unified_chats;
    END IF;

    IF to_regclass('cyber360_sessions') IS NOT NULL
       AND to_regclass('cyber_unified_sessions') IS NULL THEN
        ALTER TABLE cyber360_sessions RENAME TO cyber_unified_sessions;
    END IF;

    IF to_regclass('idx_cyber360_chats_user') IS NOT NULL
       AND to_regclass('idx_cyber_unified_chats_user') IS NULL THEN
        ALTER INDEX idx_cyber360_chats_user RENAME TO idx_cyber_unified_chats_user;
    END IF;

    IF to_regclass('idx_cyber360_sessions_user') IS NOT NULL
       AND to_regclass('idx_cyber_unified_sessions_user') IS NULL THEN
        ALTER INDEX idx_cyber360_sessions_user RENAME TO idx_cyber_unified_sessions_user;
    END IF;
END
$mig$;

-- Cover a from-scratch database whose 0001 predates this rename only in name:
-- if the tables somehow do not exist at all, create them under the new names.
CREATE TABLE IF NOT EXISTS cyber_unified_preferences (
    user_email        TEXT PRIMARY KEY,
    theme             TEXT NOT NULL DEFAULT 'light',
    reporting_period  INTEGER NOT NULL DEFAULT 30,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cyber_unified_chats (
    chat_id     TEXT PRIMARY KEY,
    user_email  TEXT NOT NULL,
    domain      TEXT,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cyber_unified_sessions (
    session_id  TEXT PRIMARY KEY,
    user_email  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cyber_unified_chats_user
    ON cyber_unified_chats (user_email, created_at);

CREATE INDEX IF NOT EXISTS idx_cyber_unified_sessions_user
    ON cyber_unified_sessions (user_email);
