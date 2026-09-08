"""
OSAP Job Queue — CRUD operations for the video processing pipeline.
====================================================================
All public functions accept an optional *db_path* keyword argument that
defaults to the value from :func:`osap.config.get_config`.  This makes them
easy to use standalone or override in tests.

State machines
--------------
**videos.status**::

    pending → downloading → downloaded → rendering → rendered → uploading
            → done | failed

**platform_uploads.status**::

    pending → uploading → done | failed | skipped
"""
from __future__ import annotations

import sqlite3
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_db_path() -> str:
    """
    Resolve the default DB path from the global Config singleton.

    Imported lazily to avoid circular imports at module load time.
    """
    from osap.config import get_config  # noqa: PLC0415

    return get_config().DB_PATH


@contextmanager
def _session(db_path: str | Path | None) -> Generator[sqlite3.Connection, None, None]:
    """
    Internal thin wrapper that resolves *db_path* and delegates to
    :func:`osap.db.models.db_session`.
    """
    from osap.db.models import db_session  # noqa: PLC0415

    resolved = db_path if db_path is not None else _get_db_path()
    with db_session(resolved) as conn:
        yield conn


@contextmanager
def _immediate(db_path: str | Path | None) -> Generator[sqlite3.Connection, None, None]:
    """
    Open a connection with ``BEGIN IMMEDIATE`` for atomic read-modify-write
    operations that must not interleave with concurrent writers.
    """
    from osap.db.models import get_conn  # noqa: PLC0415

    resolved = db_path if db_path is not None else _get_db_path()
    conn = get_conn(resolved)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Convert a :class:`sqlite3.Row` to a plain :class:`dict`, or return ``None``."""
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_url(url: str, db_path: str | Path | None = None) -> bool:
    """
    Add a single URL to the video queue.

    Uses ``BEGIN IMMEDIATE`` to avoid race conditions when multiple producers
    submit URLs concurrently.  The INSERT is ``OR IGNORE`` so duplicate URLs
    are silently skipped.

    Parameters
    ----------
    url:
        The source video URL to enqueue (must be unique).
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.

    Returns
    -------
    bool
        ``True`` if the URL was newly inserted, ``False`` if it was already
        present (duplicate).
    """
    with _immediate(db_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO videos (url, status) VALUES (?, 'pending')",
            (url,),
        )
        return cursor.rowcount > 0


def add_urls_batch(
    urls: list[str],
    db_path: str | Path | None = None,
    account_id: int | None = None,
) -> tuple[int, int]:
    """
    Add multiple URLs to the video queue in a single transaction.

    Parameters
    ----------
    urls:
        Sequence of source video URLs to enqueue.
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    account_id:
        Optional target account ID.

    Returns
    -------
    tuple[int, int]
        ``(added, skipped)`` where *added* is the number of newly inserted
        rows and *skipped* is the number of duplicates ignored.
    """
    added = 0
    skipped = 0
    acc_id = account_id
    if acc_id is None:
        try:
            active_acc = get_active_account(db_path)
            acc_id = active_acc["id"]
        except Exception:
            acc_id = 1

    with _immediate(db_path) as conn:
        for url in urls:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO videos (url, status, account_id) VALUES (?, 'pending', ?)",
                (url, acc_id),
            )
            if cursor.rowcount > 0:
                added += 1
            else:
                skipped += 1
    return added, skipped


def claim_next(
    from_status: str,
    to_status: str,
    db_path: str | Path | None = None,
    account_id: int | None = None,
) -> dict | None:
    """
    Atomically claim the next video in *from_status* and advance it to *to_status*.

    Uses ``BEGIN IMMEDIATE`` to guarantee that two concurrent workers cannot
    claim the same row.

    Parameters
    ----------
    from_status:
        The current status to filter on (e.g. ``"pending"``).
    to_status:
        The status to transition the claimed row to (e.g. ``"downloading"``).
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    account_id:
        Optional account filter.

    Returns
    -------
    dict | None
        The full row as a :class:`dict` (with its new *to_status* already
        reflected) or ``None`` if no row is available.
    """
    with _immediate(db_path) as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT * FROM videos WHERE status = ? AND (account_id = ? OR account_id IS NULL) ORDER BY created_at ASC LIMIT 1",
                (from_status, account_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM videos WHERE status = ? ORDER BY created_at ASC LIMIT 1",
                (from_status,),
            ).fetchone()

        if row is None:
            return None

        video_id: int = row["id"]
        conn.execute(
            "UPDATE videos SET status = ? WHERE id = ?",
            (to_status, video_id),
        )
        # Re-fetch to include updated_at from the trigger
        updated = conn.execute(
            "SELECT * FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
        return _row_to_dict(updated)


def update_video(
    video_id: int,
    fields: dict,
    db_path: str | Path | None = None,
) -> None:
    """
    Update arbitrary columns on a videos row.

    Parameters
    ----------
    video_id:
        Primary key of the video to update.
    fields:
        Dictionary mapping column names to their new values.  Only columns
        that exist in the ``videos`` table should be provided.
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.

    Raises
    ------
    ValueError
        If *fields* is empty.
    """
    if not fields:
        raise ValueError("update_video: 'fields' dict must not be empty")

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [video_id]

    with _session(db_path) as conn:
        conn.execute(
            f"UPDATE videos SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )


def init_platform_rows(
    video_id: int,
    platforms: list[str],
    db_path: str | Path | None = None,
) -> None:
    """
    Insert one ``platform_uploads`` row per platform for *video_id*.

    Rows that already exist are silently skipped (``INSERT OR IGNORE``), so
    this function is safe to call multiple times for the same video.

    Parameters
    ----------
    video_id:
        Primary key of the parent video.
    platforms:
        List of platform names to initialise (e.g. ``["youtube", "tiktok"]``).
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    """
    with _session(db_path) as conn:
        for platform in platforms:
            conn.execute(
                """INSERT OR IGNORE INTO platform_uploads
                       (video_id, platform, status, attempts)
                   VALUES (?, ?, 'pending', 0)""",
                (video_id, platform),
            )


def mark_platform_uploading(
    video_id: int,
    platform: str,
    db_path: str | Path | None = None,
) -> None:
    """
    Transition a platform upload row to ``'uploading'`` and increment attempt count.

    Parameters
    ----------
    video_id:
        Primary key of the parent video.
    platform:
        Platform name (e.g. ``"youtube"``).
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    """
    with _session(db_path) as conn:
        conn.execute(
            """UPDATE platform_uploads
               SET status = 'uploading', attempts = attempts + 1
               WHERE video_id = ? AND platform = ?""",
            (video_id, platform),
        )


def mark_platform_done(
    video_id: int,
    platform: str,
    upload_url: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    """
    Mark a platform upload as successfully completed.

    After updating the row, calls :func:`_check_all_platforms_done` to
    potentially advance ``videos.status`` to ``'done'``.

    Parameters
    ----------
    video_id:
        Primary key of the parent video.
    platform:
        Platform name (e.g. ``"youtube"``).
    upload_url:
        Optional URL of the published post/video on the target platform.
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    """
    with _session(db_path) as conn:
        conn.execute(
            """UPDATE platform_uploads
               SET status = 'done', upload_url = ?, error_msg = NULL
               WHERE video_id = ? AND platform = ?""",
            (upload_url, video_id, platform),
        )

    _check_all_platforms_done(video_id, db_path)


def mark_platform_failed(
    video_id: int,
    platform: str,
    error_msg: str,
    db_path: str | Path | None = None,
) -> None:
    """
    Mark a platform upload as failed and record the error message.

    The ``attempts`` counter is **not** incremented here because
    :func:`mark_platform_uploading` already increments it before each attempt.

    Parameters
    ----------
    video_id:
        Primary key of the parent video.
    platform:
        Platform name (e.g. ``"tiktok"``).
    error_msg:
        Human-readable description of why the upload failed.
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    """
    with _session(db_path) as conn:
        conn.execute(
            """UPDATE platform_uploads
               SET status = 'failed', error_msg = ?
               WHERE video_id = ? AND platform = ?""",
            (error_msg, video_id, platform),
        )


def _check_all_platforms_done(
    video_id: int,
    db_path: str | Path | None = None,
) -> None:
    """
    Advance ``videos.status`` to ``'done'`` when every platform upload has
    reached a terminal state (``done``, ``failed``, or ``skipped``).

    This is an internal helper called automatically by :func:`mark_platform_done`.

    Parameters
    ----------
    video_id:
        Primary key of the video to check.
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    """
    terminal_states = {"done", "failed", "skipped"}

    with _session(db_path) as conn:
        rows = conn.execute(
            "SELECT status FROM platform_uploads WHERE video_id = ?",
            (video_id,),
        ).fetchall()

        if not rows:
            # No platform rows at all — nothing to conclude.
            return

        statuses = {row["status"] for row in rows}
        if statuses.issubset(terminal_states):
            conn.execute(
                "UPDATE videos SET status = 'done' WHERE id = ?",
                (video_id,),
            )


def log_error(
    video_id: int | None,
    module: str,
    error_msg: str,
    platform: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    """
    Append a structured error record to the ``error_log`` table.

    The current exception's stack trace (if any) is captured automatically
    via :func:`traceback.format_exc`.

    Parameters
    ----------
    video_id:
        Primary key of the related video, or ``None`` for infrastructure errors.
    module:
        Dotted module name where the error originated (e.g. ``"osap.downloader"``).
    error_msg:
        Short human-readable description of the error.
    platform:
        Platform name if the error is platform-specific, otherwise ``None``.
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.
    """
    stack: str = traceback.format_exc()
    # ``traceback.format_exc()`` returns "NoneType: None\n" when there is no
    # active exception — normalise that to an empty string.
    if stack.strip() in {"NoneType: None", "None"}:
        stack = ""

    with _session(db_path) as conn:
        conn.execute(
            """INSERT INTO error_log
                   (video_id, platform, module, error_msg, stack_trace)
               VALUES (?, ?, ?, ?, ?)""",
            (video_id, platform, module, error_msg, stack or None),
        )
        # Also increment the error_count on the parent video row (if any)
        if video_id is not None:
            conn.execute(
                "UPDATE videos SET error_count = error_count + 1 WHERE id = ?",
                (video_id,),
            )


def get_stats(db_path: str | Path | None = None) -> dict:
    """
    Return an aggregate statistics snapshot of the current queue state.

    Returns
    -------
    dict
        A dictionary with the following keys:

        ``total`` : int
            Total number of video rows.
        ``by_status`` : dict[str, int]
            Count of videos grouped by their ``status`` value.
        ``platforms`` : list[dict]
            Each element has ``platform``, ``status``, and ``count`` keys,
            covering all ``platform_uploads`` combinations.
        ``errors`` : int
            Total number of rows in ``error_log``.

    Example
    -------
    ::

        {
            "total": 42,
            "by_status": {"pending": 10, "done": 30, "failed": 2},
            "platforms": [
                {"platform": "youtube", "status": "done", "count": 25},
                ...
            ],
            "errors": 5,
        }
    """
    with _session(db_path) as conn:
        # Total video count
        total: int = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]

        # Per-status breakdown
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM videos GROUP BY status"
        ).fetchall()
        by_status: dict[str, int] = {row["status"]: row["cnt"] for row in status_rows}

        # Per-platform per-status breakdown
        platform_rows = conn.execute(
            """SELECT platform, status, COUNT(*) AS cnt
               FROM platform_uploads
               GROUP BY platform, status
               ORDER BY platform, status"""
        ).fetchall()
        platforms: list[dict] = [
            {"platform": r["platform"], "status": r["status"], "count": r["cnt"]}
            for r in platform_rows
        ]

        # Error log count
        error_count: int = conn.execute("SELECT COUNT(*) FROM error_log").fetchone()[0]

    return {
        "total": total,
        "by_status": by_status,
        "platforms": platforms,
        "errors": error_count,
    }


def get_video_by_id(
    video_id: int,
    db_path: str | Path | None = None,
) -> dict | None:
    """
    Fetch a single video row by primary key.

    Parameters
    ----------
    video_id:
        Primary key of the video to retrieve.
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.

    Returns
    -------
    dict | None
        The video row as a :class:`dict`, or ``None`` if no row with *video_id*
        exists.
    """
    with _session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
    return _row_to_dict(row)


def get_pending_count(db_path: str | Path | None = None) -> int:
    """
    Return the number of videos currently in ``'pending'`` status.

    Parameters
    ----------
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.

    Returns
    -------
    int
        Count of pending videos.
    """
    with _session(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE status = 'pending'"
        ).fetchone()
    return row[0]


def reset_stuck(db_path: str | Path | None = None) -> int:
    """
    Find and reset videos that are stuck in transient processing states.

    A video is considered **stuck** if its ``updated_at`` timestamp is more
    than 30 minutes in the past while it is in one of the following states:

    * ``'downloading'`` → reset to ``'pending'``
    * ``'rendering'`` → reset to ``'downloaded'``
    * ``'uploading'`` → reset to ``'rendered'``

    An error is logged for every row that is reset so that operators can
    investigate.

    Parameters
    ----------
    db_path:
        Path to the SQLite database.  Defaults to ``Config.DB_PATH``.

    Returns
    -------
    int
        The total number of videos that were reset.
    """
    # Map from stuck status → target recovery status
    recovery_map: dict[str, str] = {
        "downloading": "pending",
        "rendering": "downloaded",
        "uploading": "rendered",
    }

    # SQLite stores CURRENT_TIMESTAMP in UTC; compute the cutoff in UTC.
    cutoff: datetime = datetime.now(tz=timezone.utc) - timedelta(minutes=30)
    # SQLite DATETIME comparison works with ISO-8601 strings
    cutoff_str: str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    total_reset = 0

    for stuck_status, recovery_status in recovery_map.items():
        with _immediate(db_path) as conn:
            stuck_rows = conn.execute(
                """SELECT id, url, updated_at
                   FROM videos
                   WHERE status = ?
                     AND updated_at <= ?""",
                (stuck_status, cutoff_str),
            ).fetchall()

            for row in stuck_rows:
                vid_id: int = row["id"]
                url: str = row["url"]
                updated_at: str = row["updated_at"]

                conn.execute(
                    "UPDATE videos SET status = ?, error_count = error_count + 1 WHERE id = ?",
                    (recovery_status, vid_id),
                )
                total_reset += 1

        # Log each reset outside the IMMEDIATE transaction to avoid nesting
        for row in stuck_rows:  # type: ignore[possibly-undefined]
            vid_id = row["id"]
            url = row["url"]
            updated_at = row["updated_at"]
            log_error(
                video_id=vid_id,
                module="osap.db.queue.reset_stuck",
                error_msg=(
                    f"Video id={vid_id} url={url!r} was stuck in "
                    f"'{stuck_status}' since {updated_at}; "
                    f"reset to '{recovery_status}'."
                ),
                db_path=db_path,
            )

    return total_reset


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def list_accounts(db_path: str | Path | None = None) -> list[dict]:
    """Return all accounts."""
    with _session(db_path) as conn:
        rows = conn.execute("SELECT id, name, is_active, created_at FROM accounts ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def get_active_account(db_path: str | Path | None = None) -> dict:
    """Return the currently active account, or fallback to first account."""
    with _session(db_path) as conn:
        row = conn.execute("SELECT id, name, is_active, created_at FROM accounts WHERE is_active = 1 LIMIT 1").fetchone()
        if not row:
            row = conn.execute("SELECT id, name, is_active, created_at FROM accounts ORDER BY id ASC LIMIT 1").fetchone()
        if not row:
            conn.execute("INSERT INTO accounts (id, name, is_active) VALUES (1, 'Akun 1 (Default)', 1)")
            return {"id": 1, "name": "Akun 1 (Default)", "is_active": 1}
        return dict(row)


def set_active_account(account_id: int, db_path: str | Path | None = None) -> None:
    """Set an account as the active one (and deactivate others)."""
    with _session(db_path) as conn:
        conn.execute("UPDATE accounts SET is_active = 0")
        conn.execute("UPDATE accounts SET is_active = 1 WHERE id = ?", (account_id,))


def create_account(name: str, db_path: str | Path | None = None) -> dict:
    """Create a new account profile."""
    with _session(db_path) as conn:
        cursor = conn.execute("INSERT INTO accounts (name, is_active) VALUES (?, 0)", (name.strip(),))
        acc_id = cursor.lastrowid
        return {"id": acc_id, "name": name.strip(), "is_active": 0}


def delete_account(account_id: int, db_path: str | Path | None = None) -> bool:
    """Delete an account if not default."""
    if account_id == 1:
        return False
    with _session(db_path) as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        # If no active account left, activate id 1
        active = conn.execute("SELECT COUNT(*) FROM accounts WHERE is_active = 1").fetchone()[0]
        if active == 0:
            conn.execute("UPDATE accounts SET is_active = 1 WHERE id = 1")
    return True

