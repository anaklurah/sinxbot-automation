"""
Database models and connection management for OSAP.
====================================================
Provides:

* :data:`PLATFORMS` — canonical list of all supported upload platforms.
* :data:`SCHEMA` — DDL that creates all tables, indices, and triggers.
* :func:`get_conn` — open a raw :class:`sqlite3.Connection` with WAL mode and
  all recommended PRAGMA settings pre-applied.
* :func:`db_session` — context-manager wrapper around :func:`get_conn` that
  commits on clean exit and rolls back on exception.
* :func:`init_db` — idempotent database initialisation (runs the full SCHEMA).
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Canonical list of all platforms supported by OSAP, in display order.
PLATFORMS: list[str] = [
    "youtube",
    "facebook",
    "instagram",
    "twitter",
    "twitter_nsfw",
    "tiktok",
    "upscrolled",
    "febspot",
]

# ---------------------------------------------------------------------------
# DDL Schema
# ---------------------------------------------------------------------------

SCHEMA: str = """
-- -----------------------------------------------------------------------
-- videos
-- -----------------------------------------------------------------------
-- Central table tracking every source video through its processing pipeline.
-- Status state machine:
--   pending → downloading → downloaded → rendering → rendered → uploading
--           → done | failed
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT    NOT NULL UNIQUE,
    video_id        TEXT,                       -- platform-side video ID (e.g. YouTube watch ID)
    title           TEXT,                       -- original title from source platform
    description     TEXT,                       -- original description from source platform
    tags            TEXT,                       -- JSON array of strings  e.g. '["tag1","tag2"]'
    status          TEXT    NOT NULL DEFAULT 'pending',
    raw_path        TEXT,                       -- absolute path to downloaded source file
    rendered_path   TEXT,                       -- absolute path to FFmpeg-processed file
    meta_path       TEXT,                       -- absolute path to JSON metadata sidecar
    ai_title        TEXT,                       -- AI-generated title
    ai_description  TEXT,                       -- AI-generated description / caption
    ai_tags         TEXT,                       -- JSON array of AI-generated hashtags
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    error_count     INTEGER  DEFAULT 0
);

-- -----------------------------------------------------------------------
-- platform_uploads
-- -----------------------------------------------------------------------
-- One row per (video, platform) pair, tracking the upload lifecycle.
-- Status values: pending | uploading | done | failed | skipped
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_uploads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    platform    TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    upload_url  TEXT,                           -- URL of the published post (when available)
    error_msg   TEXT,                           -- last error message on failure
    attempts    INTEGER DEFAULT 0,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(video_id, platform)
);

-- -----------------------------------------------------------------------
-- error_log
-- -----------------------------------------------------------------------
-- Append-only log of all errors encountered across all modules.
-- video_id and platform may be NULL for infrastructure-level errors.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    platform    TEXT,
    module      TEXT    NOT NULL,
    error_msg   TEXT    NOT NULL,
    stack_trace TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_videos_status
    ON videos(status);

CREATE INDEX IF NOT EXISTS idx_platform_uploads_status
    ON platform_uploads(status);

CREATE INDEX IF NOT EXISTS idx_platform_uploads_video_id
    ON platform_uploads(video_id);

-- -----------------------------------------------------------------------
-- Triggers — auto-update updated_at columns
-- -----------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS videos_updated_at
    AFTER UPDATE ON videos
    BEGIN
        UPDATE videos SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS platform_uploads_updated_at
    AFTER UPDATE ON platform_uploads
    BEGIN
        UPDATE platform_uploads SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;
"""


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------


def get_conn(db_path: str | Path, timeout: float = 15.0) -> sqlite3.Connection:
    """
    Open a :class:`sqlite3.Connection` with WAL mode and production PRAGMA settings.

    PRAGMA configuration applied
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    * ``journal_mode = WAL`` — write-ahead logging for concurrent readers.
    * ``synchronous = NORMAL`` — good durability / performance balance in WAL mode.
    * ``busy_timeout = 5000`` — wait up to 5 s before raising ``OperationalError``
      when the database is locked by another process.
    * ``cache_size = -32000`` — 32 MB page cache (negative value = kibibytes).
    * ``foreign_keys = ON`` — enforce referential integrity constraints.
    * ``temp_store = MEMORY`` — store temp tables/indices in RAM.
    * ``mmap_size = 134217728`` — enable 128 MB memory-mapped I/O.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  The parent directory *must* already
        exist (call :func:`init_db` or create it explicitly first).
    timeout:
        Seconds that the Python-level connection will wait for the database
        lock before raising :class:`sqlite3.OperationalError`.  The SQLite
        busy_timeout PRAGMA is set separately (5 s) and operates independently.

    Returns
    -------
    sqlite3.Connection
        A fully configured connection with ``row_factory = sqlite3.Row`` so
        that query results can be accessed by column name.
    """
    conn = sqlite3.connect(
        str(db_path),
        timeout=timeout,
        check_same_thread=False,
        isolation_level=None,  # autocommit off — we manage transactions manually
    )
    conn.row_factory = sqlite3.Row

    # Apply PRAGMAs.  These must be executed outside of an explicit transaction
    # (isolation_level=None gives us that control).
    pragmas: list[str] = [
        "PRAGMA journal_mode = WAL;",
        "PRAGMA synchronous = NORMAL;",
        "PRAGMA busy_timeout = 5000;",
        "PRAGMA cache_size = -32000;",
        "PRAGMA foreign_keys = ON;",
        "PRAGMA temp_store = MEMORY;",
        "PRAGMA mmap_size = 134217728;",
    ]
    for pragma in pragmas:
        conn.execute(pragma)

    return conn


# ---------------------------------------------------------------------------
# Context-manager session
# ---------------------------------------------------------------------------


@contextmanager
def db_session(
    db_path: str | Path,
    timeout: float = 15.0,
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that provides a :class:`sqlite3.Connection` and handles
    transaction lifecycle automatically.

    On clean exit the transaction is **committed**.
    On any exception the transaction is **rolled back** before re-raising.
    The connection is always **closed** on exit regardless of outcome.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    timeout:
        Forwarded to :func:`get_conn`.

    Yields
    ------
    sqlite3.Connection
        An open, PRAGMA-configured connection inside a ``BEGIN`` transaction.

    Example
    -------
    ::

        from osap.db.models import db_session

        with db_session("./osap.db") as conn:
            conn.execute("INSERT INTO videos (url) VALUES (?)", ("https://...",))
    """
    conn = get_conn(db_path, timeout=timeout)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------


def init_db(db_path: str | Path) -> None:
    """
    Initialise the OSAP database idempotently.

    Creates all parent directories for *db_path*, then executes :data:`SCHEMA`
    via :meth:`~sqlite3.Connection.executescript` to create tables, indices,
    and triggers if they do not already exist.

    This function is safe to call on every application startup — it will never
    drop or alter existing data.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file to initialise.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # executescript implicitly commits any pending transaction and then runs
    # the supplied SQL as a series of statements.  We use a raw connection here
    # (not db_session) because executescript cannot run inside an open BEGIN.
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
