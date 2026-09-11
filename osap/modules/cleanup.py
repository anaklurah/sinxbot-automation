"""
osap/modules/cleanup.py
───────────────────────
Garbage collection module for the OmniShorts Auto-Publisher pipeline.

Finds all videos whose status is ``'done'`` and removes the large
raw and rendered files from disk, keeping only the metadata JSON as
an audit trail.

Key behaviours
──────────────
• ``dry_run=True`` – logs what *would* be deleted without touching files.
• ``raw_path`` and ``rendered_path`` are NULLed in the DB after deletion.
• ``meta_path`` is always preserved.
• ``get_disk_usage()`` returns current download directory sizes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from osap.config import get_config
from osap.db.models import db_session
from osap.db.queue import update_video
from osap.utils.logger import get_logger

logger = get_logger(__name__)


class CleanupWorker:
    """Delete raw and rendered files for completed (``done``) videos.

    Parameters
    ----------
    db_path:
        Override path to the SQLite database.  Defaults to ``cfg.DB_PATH``.
    dry_run:
        When ``True``, log what *would* happen but do not delete or update
        anything.
    """

    def __init__(
        self,
        db_path: str | None = None,
        dry_run: bool = False,
    ) -> None:
        self.cfg = get_config()
        self.db_path = db_path or self.cfg.DB_PATH
        self.dry_run = dry_run

        if self.dry_run:
            logger.info("CleanupWorker started in DRY-RUN mode.")
        else:
            logger.info("CleanupWorker started.")

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Find all *done* videos and clean up their files.

        Iterates every ``status='done'`` row in the DB and calls
        :meth:`_cleanup_video` for each.  Prints a summary at the end.
        """
        done_videos = self._fetch_done_videos()

        if not done_videos:
            logger.info("No completed videos found for cleanup.")
            return

        logger.info("Found %d completed video(s) to clean up.", len(done_videos))

        total_raw_freed = 0
        total_rendered_freed = 0
        cleaned = 0
        skipped = 0

        for video in done_videos:
            try:
                raw_freed, rendered_freed = self._cleanup_video(video)
                total_raw_freed += raw_freed
                total_rendered_freed += rendered_freed
                cleaned += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Error cleaning video id=%d: %s", video.get("id", "?"), exc
                )
                skipped += 1

        total_freed = total_raw_freed + total_rendered_freed
        prefix = "[DRY-RUN] " if self.dry_run else ""
        logger.info(
            "%sCleanup complete: %d cleaned, %d errors. "
            "Freed raw=%s, rendered=%s, total=%s.",
            prefix,
            cleaned,
            skipped,
            _fmt_bytes(total_raw_freed),
            _fmt_bytes(total_rendered_freed),
            _fmt_bytes(total_freed),
        )

    # ------------------------------------------------------------------ #
    def _cleanup_video(self, video: dict) -> tuple[int, int]:
        """Delete raw and rendered files for a single video.

        Preserves ``meta_path``.  Updates the DB record to NULL out
        ``raw_path`` and ``rendered_path`` (unless ``dry_run`` is active).

        Parameters
        ----------
        video:
            DB row dict.  Expected keys: ``id``, ``raw_path``,
            ``rendered_path``, ``meta_path``.

        Returns
        -------
        tuple[int, int]
            ``(bytes_freed_raw, bytes_freed_rendered)``
        """
        vid_id: int = video["id"]
        raw_path_str: str | None = video.get("raw_path")
        rendered_path_str: str | None = video.get("rendered_path")

        raw_freed = self._delete_file(raw_path_str, vid_id, "raw")
        rendered_freed = self._delete_file(rendered_path_str, vid_id, "rendered")

        if not self.dry_run:
            update_video(vid_id, {"raw_path": None, "rendered_path": None})
            logger.debug(
                "Nulled raw_path and rendered_path for video id=%d.", vid_id
            )

        return raw_freed, rendered_freed

    # ------------------------------------------------------------------ #
    def _delete_file(
        self,
        path_str: str | None,
        vid_id: int,
        label: str,
    ) -> int:
        """Attempt to delete a file and return the bytes freed.

        Parameters
        ----------
        path_str:
            Absolute path to the file (may be ``None``).
        vid_id:
            Video DB id, used for log messages.
        label:
            Human-readable label (``'raw'`` or ``'rendered'``).

        Returns
        -------
        int
            Number of bytes freed (``0`` if nothing was deleted).
        """
        if not path_str:
            return 0

        path = Path(path_str)

        if not path.exists():
            logger.debug(
                "Video id=%d: %s file not found, skipping: %s", vid_id, label, path
            )
            return 0

        size = path.stat().st_size

        if self.dry_run:
            logger.info(
                "[DRY-RUN] Would delete %s file (%s): %s",
                label,
                _fmt_bytes(size),
                path,
            )
            return size

        try:
            path.unlink()
            logger.info(
                "Deleted %s file (%s): %s", label, _fmt_bytes(size), path
            )
            return size
        except OSError as exc:
            logger.error(
                "Failed to delete %s file for video id=%d (%s): %s",
                label,
                vid_id,
                path,
                exc,
            )
            return 0

    # ------------------------------------------------------------------ #
    def get_disk_usage(self) -> dict:
        """Return current disk usage for the downloads directory.

        Scans ``cfg.raw_dir`` and ``cfg.rendered_dir`` separately.

        Returns
        -------
        dict
            ``{raw_size_bytes, rendered_size_bytes, total_size_bytes, file_count}``
        """
        cfg = self.cfg

        raw_size, raw_count = _dir_size(cfg.raw_dir)
        rendered_size, rendered_count = _dir_size(cfg.rendered_dir)

        result = {
            "raw_size_bytes": raw_size,
            "rendered_size_bytes": rendered_size,
            "total_size_bytes": raw_size + rendered_size,
            "file_count": raw_count + rendered_count,
        }

        logger.debug(
            "Disk usage – raw=%s (%d files), rendered=%s (%d files), total=%s.",
            _fmt_bytes(raw_size),
            raw_count,
            _fmt_bytes(rendered_size),
            rendered_count,
            _fmt_bytes(result["total_size_bytes"]),
        )

        return result

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _fetch_done_videos(self) -> list[dict]:
        """Retrieve all videos with ``status='done'`` from the database."""
        with db_session(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, raw_path, rendered_path, meta_path, video_id "
                "FROM videos WHERE status = 'done'"
            )
            return [dict(row) for row in cursor.fetchall()]


# ──────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ──────────────────────────────────────────────────────────────────────────────

def _dir_size(directory: Path) -> tuple[int, int]:
    """Return ``(total_bytes, file_count)`` for all files inside *directory*.

    Non-existent directories return ``(0, 0)`` without raising.
    """
    if not directory.exists():
        return 0, 0

    total_bytes = 0
    file_count = 0

    for entry in os.scandir(directory):
        if entry.is_file(follow_symlinks=False):
            try:
                total_bytes += entry.stat().st_size
                file_count += 1
            except OSError:
                pass  # Race condition – file deleted between scandir and stat.

    return total_bytes, file_count


def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string (e.g. ``'1.23 GB'``)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.2f} PB"


def clean_browser_caches(profiles_dir: Path | None = None) -> int:
    """Sweep and purge browser junk caches (IndexedDB blobs, Code Cache, cache2, shader caches)
    from all profile directories while preserving cookies, logins, and session storage."""
    cfg = get_config()
    target_dir = profiles_dir or Path(cfg.PROFILES_DIR)
    if not target_dir.exists():
        return 0

    import shutil
    total_freed = 0
    EXCLUDE_DIR_NAMES = {
        'cache', 'code cache', 'cache2', 'gpucache', 'dawnwebgpucache',
        'dawngraphitecache', 'browsermetrics', 'crashpad', 'startupcache',
        'optimization_guide_model_store', 'grshadercache', 'gpupersistentcache',
        'shadercache', 'extensions_crx_cache', 'component_crx_cache'
    }

    for root, dirs, files in os.walk(target_dir, topdown=True):
        # 1. Purge cache directories and indexeddb video blobs
        for d in list(dirs):
            if d.lower() in EXCLUDE_DIR_NAMES or d.endswith('.blob'):
                dir_path = Path(root) / d
                try:
                    size = sum(f.stat().st_size for f in dir_path.rglob('*') if f.is_file())
                    shutil.rmtree(dir_path, ignore_errors=True)
                    total_freed += size
                    dirs.remove(d)
                except Exception:
                    pass

        # 2. Purge crash dumps and temporary metrics
        for f in files:
            if f.endswith('.pma') or f.endswith('.dmp'):
                f_path = Path(root) / f
                try:
                    total_freed += f_path.stat().st_size
                    f_path.unlink(missing_ok=True)
                except Exception:
                    pass

    if total_freed > 0:
        logger.info("[Cleanup] 🧹 Purged %s of browser junk cache across profiles.", _fmt_bytes(total_freed))
    return total_freed


__all__ = ["CleanupWorker", "clean_browser_caches"]
