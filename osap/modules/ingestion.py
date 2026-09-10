"""
osap/modules/ingestion.py
─────────────────────────
URL parser and downloader module for the OmniShorts Auto-Publisher pipeline.

Responsibilities
────────────────
• parse_urls()        – read a .csv or .txt file and return a deduplicated URL list
• IngestionWorker     – parse → DB → summary report
• DownloadWorker      – claim DB jobs → yt-dlp download → update DB
"""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Any

import yt_dlp

from osap.config import get_config
from osap.db.queue import (
    add_urls_batch,
    claim_next,
    init_platform_rows,
    log_error,
    mark_platform_failed,
    update_video,
)
from osap.utils.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# URL Parser
# ──────────────────────────────────────────────────────────────────────────────

def parse_urls(source_path: str | Path) -> list[str]:
    """Parse a .csv or .txt file and return a deduplicated list of URLs.

    CSV rules
    ─────────
    • Looks for a column named ``url`` or ``URL`` (case-insensitive).
    • Falls back to the *first* column if no recognised header exists.

    TXT rules
    ─────────
    • One URL per line.
    • Lines starting with ``#`` are treated as comments and skipped.
    • Blank / whitespace-only lines are skipped.

    Parameters
    ----------
    source_path:
        Absolute or relative path to the source file.

    Returns
    -------
    list[str]
        Deduplicated list of non-empty URL strings, preserving order.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    suffix = source_path.suffix.lower()

    if suffix == ".csv":
        urls = _parse_csv(source_path)
    elif suffix == ".txt":
        urls = _parse_txt(source_path)
    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. Expected .csv or .txt."
        )

    # Deduplicate while preserving insertion order.
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            deduped.append(url)

    logger.info(
        "Parsed %d unique URL(s) from '%s'.", len(deduped), source_path.name
    )
    return deduped


def _parse_csv(path: Path) -> list[str]:
    """Extract URLs from a CSV file."""
    urls: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        # Find the URL column – prefer 'url' / 'URL', else first column.
        fieldnames = reader.fieldnames or []
        url_col: str | None = None
        for col in fieldnames:
            if col.strip().lower() == "url":
                url_col = col
                break

        if url_col is None and fieldnames:
            # Fall back to first column with a warning.
            url_col = fieldnames[0]
            logger.warning(
                "No 'url'/'URL' column found in CSV; using first column '%s'.",
                url_col,
            )

        if url_col is None:
            logger.error("CSV file '%s' has no columns at all.", path.name)
            return urls

        for row in reader:
            val = (row.get(url_col) or "").strip()
            if val:
                urls.append(val)

    return urls


def _parse_txt(path: Path) -> list[str]:
    """Extract URLs from a plain-text file."""
    urls: list[str] = []
    with path.open(encoding="utf-8-sig") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


# ──────────────────────────────────────────────────────────────────────────────
# Ingestion Worker
# ──────────────────────────────────────────────────────────────────────────────

class IngestionWorker:
    """Parse a URL source file, persist the URLs into the DB, and print a summary.

    Parameters
    ----------
    source_file:
        Path to the .csv or .txt file containing video URLs.
    db_path:
        Override path to the SQLite database.  Defaults to ``cfg.DB_PATH``.
    """

    def __init__(self, source_file: str | Path, db_path: str | None = None) -> None:
        self.source_file = Path(source_file)
        self.cfg = get_config()
        self.db_path = db_path or self.cfg.DB_PATH

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Parse URLs → add to DB → print rich summary."""
        logger.info("IngestionWorker starting for '%s'.", self.source_file)

        try:
            urls = parse_urls(self.source_file)
        except (FileNotFoundError, ValueError) as exc:
            logger.error("Failed to parse source file: %s", exc)
            self._print_summary(total=0, added=0, skipped=0, error=str(exc))
            return

        if not urls:
            logger.warning("No URLs found in '%s'. Nothing to ingest.", self.source_file)
            self._print_summary(total=0, added=0, skipped=0, error=None)
            return

        try:
            added, skipped = add_urls_batch(urls, db_path=self.db_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("DB error during batch insert: %s", exc)
            self._print_summary(total=len(urls), added=0, skipped=0, error=str(exc))
            return

        self._print_summary(total=len(urls), added=added, skipped=skipped, error=None)
        logger.info(
            "Ingestion complete: %d new / %d skipped (duplicates).", added, skipped
        )

    # ------------------------------------------------------------------ #
    def _print_summary(
        self,
        total: int,
        added: int,
        skipped: int,
        error: str | None,
    ) -> None:
        """Print a human-readable ingestion summary.

        Uses *rich* if available, falls back to plain ``print``.
        """
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table

            console = Console()
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_row("[bold]Source file[/bold]", str(self.source_file))
            table.add_row("[bold]Total URLs parsed[/bold]", str(total))
            table.add_row("[green bold]Added to DB[/green bold]", str(added))
            table.add_row("[yellow bold]Skipped (duplicates)[/yellow bold]", str(skipped))
            if error:
                table.add_row("[red bold]Error[/red bold]", error)

            console.print(
                Panel(
                    table,
                    title="[bold cyan]OSAP – Ingestion Summary[/bold cyan]",
                    border_style="cyan",
                )
            )
        except ImportError:
            # Fallback without rich.
            print("=" * 50)
            print("OSAP – Ingestion Summary")
            print(f"  Source file : {self.source_file}")
            print(f"  Total URLs  : {total}")
            print(f"  Added       : {added}")
            print(f"  Skipped     : {skipped}")
            if error:
                print(f"  ERROR       : {error}")
            print("=" * 50)


# ──────────────────────────────────────────────────────────────────────────────
# YouTube Cookies Resolver & Auto-Exporter
# ──────────────────────────────────────────────────────────────────────────────

def _get_youtube_cookiefile(cfg) -> Path | None:
    """Find or auto-export YouTube cookies from browser profile or storage json to Netscape format."""
    profiles_dir = getattr(cfg, "PROFILES_DIR", None) or (Path(__file__).resolve().parents[2] / "assets" / "profiles")
    yt_netscape = profiles_dir / "youtube_cookies.txt"

    from osap.modules.publisher.cookie_loader import export_netscape_cookies, load_cookies

    # If youtube_storage.json exists and is newer than youtube_cookies.txt, update it
    storage_candidates = sorted(
        profiles_dir.glob("youtube*_storage.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if storage_candidates and (
        not yt_netscape.exists()
        or yt_netscape.stat().st_size == 0
        or storage_candidates[0].stat().st_mtime > yt_netscape.stat().st_mtime
    ):
        try:
            parsed = load_cookies(storage_candidates[0])
            if parsed:
                export_netscape_cookies(parsed, yt_netscape)
                logger.info("  [yt-dlp] Updated %s from %s (%d cookies)", yt_netscape.name, storage_candidates[0].name, len(parsed))
        except Exception as exc:
            logger.debug("  [yt-dlp] Could not update from storage json: %s", exc)

    candidate_cookies = [
        yt_netscape,
        profiles_dir / "youtube.txt",
        profiles_dir / "cookies.txt",
    ]
    for c_path in candidate_cookies:
        if c_path.exists() and c_path.stat().st_size > 0:
            return c_path

    # Try auto-exporting from persistent YouTube profile if available
    yt_profile_dir = profiles_dir / "youtube"
    if yt_profile_dir.exists():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(str(yt_profile_dir), headless=True)
                cookies = ctx.cookies()
                ctx.close()
                if cookies:
                    export_netscape_cookies(cookies, yt_netscape)
                    logger.info("  [yt-dlp] Auto-exported %d YouTube cookies from profile to %s", len(cookies), yt_netscape.name)
                    return yt_netscape
        except Exception as exc:
            logger.debug("  [yt-dlp] Note: Could not auto-export cookies from profile: %s", exc)

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Download Worker
# ──────────────────────────────────────────────────────────────────────────────

class DownloadWorker:
    """Claim pending jobs from the database and download them via yt-dlp.

    Parameters
    ----------
    db_path:
        Override path to the SQLite database.
    workers:
        Reserved for future concurrent implementation.  Currently only a
        single sequential worker is used.
    """

    def __init__(self, db_path: str | None = None, workers: int = 1) -> None:
        self.cfg = get_config()
        self.db_path = db_path or self.cfg.DB_PATH
        self.workers = workers

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Drain the download queue until no more pending jobs remain."""
        logger.info("DownloadWorker started (workers=%d).", self.workers)
        processed = 0
        while True:
            did_work = self._process_one()
            if not did_work:
                break
            processed += 1
        logger.info("DownloadWorker finished. Processed %d video(s).", processed)

    # ------------------------------------------------------------------ #
    def _process_one(self) -> bool:
        """Claim one pending job, download it, and update the DB.

        Returns
        -------
        bool
            ``True`` if a job was claimed and processed; ``False`` if the
            queue is empty.
        """
        video = claim_next("pending", "downloading")
        if video is None:
            logger.debug("No pending videos in queue.")
            return False

        vid_id: int = video["id"]
        url: str = video["url"]
        logger.info("Downloading video id=%d  url=%s", vid_id, url)

        result = self._download_video(video)
        if result is None:
            # Error already logged inside _download_video.
            return True

        # Persist successful download metadata.
        update_video(
            vid_id,
            {
                "status": "downloaded",
                "video_id": result["video_id"],
                "title": result["title"],
                "description": result["description"],
                "tags": result["tags"],
                "raw_path": result["raw_path"],
                "meta_path": result["meta_path"],
            },
        )

        # Initialise per-platform rows for downstream publishing.
        platforms: list[str] = self.cfg.enabled_platforms
        if platforms:
            init_platform_rows(vid_id, platforms)

        logger.info(
            "Downloaded video id=%d → %s", vid_id, result["raw_path"]
        )
        return True

    # ------------------------------------------------------------------ #
    def _download_video(self, video: dict) -> dict | None:
        """Download a single video using yt-dlp as a Python module.

        Parameters
        ----------
        video:
            DB row dict; must contain at minimum ``id`` and ``url``.

        Returns
        -------
        dict | None
            On success: ``{video_id, title, description, tags, raw_path, meta_path}``.
            On failure: ``None`` (DB is updated to *failed*).
        """
        vid_id: int = video["id"]
        url: str = video["url"]
        cfg = self.cfg

        # Ensure output directories exist.
        cfg.raw_dir.mkdir(parents=True, exist_ok=True)
        cfg.meta_dir.mkdir(parents=True, exist_ok=True)

        # yt-dlp progress hook ─────────────────────────────────────────── #
        def _progress_hook(d: dict[str, Any]) -> None:
            status = d.get("status", "")
            if status == "downloading":
                pct = d.get("_percent_str", "?%").strip()
                speed = d.get("_speed_str", "?/s").strip()
                logger.debug("  [yt-dlp] %s  speed=%s", pct, speed)
            elif status == "finished":
                logger.info(
                    "  [yt-dlp] Download finished: %s", d.get("filename", "")
                )
            elif status == "error":
                logger.error("  [yt-dlp] Error hook triggered for url=%s", url)

        ydl_opts: dict[str, Any] = {
            "format": "bestvideo*+bestaudio/best",
            "outtmpl": str(cfg.raw_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "writeinfojson": False,
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
            ],
            "merge_output_format": "mp4",
            "progress_hooks": [_progress_hook],
            "js_runtimes": {"node": {}},
        }

        # Inject proxy if configured
        proxy_url = getattr(cfg, "PROXY_URL", None) or os.environ.get("PROXY_URL")
        if proxy_url:
            ydl_opts["proxy"] = proxy_url

        # Resolve YouTube cookies if available
        cookie_file = _get_youtube_cookiefile(cfg)

        # Try to fetch PO Token (Proof of Origin) to bypass VPS IP bot detection
        # This is needed because YouTube blocks datacenter IPs without a valid browser-sourced token
        po_token: str | None = None
        visitor_data: str | None = None
        try:
            from osap.modules.pot_provider import fetch_po_token
            pot_result = fetch_po_token(cookie_file=cookie_file)
            if pot_result:
                po_token, visitor_data = pot_result
                logger.info("  [yt-dlp] PO Token acquired (%s...)", po_token[:16])
        except Exception as pot_err:
            logger.debug("  [yt-dlp] PO token fetch skipped: %s", pot_err)

        def _make_opts(include_cookies: bool = True, client: list[str] | None = None, use_po: bool = True) -> dict[str, Any]:
            """Build yt-dlp options dict with optional cookies, clients, and PO token."""
            opts = dict(ydl_opts)
            if include_cookies and cookie_file:
                opts["cookiefile"] = str(cookie_file)
                logger.info("  [yt-dlp] Using cookies: %s", cookie_file.name)
            ea: dict = dict(opts.get("extractor_args") or {})
            yt_ea: dict = dict(ea.get("youtube") or {})
            if client:
                yt_ea["player_client"] = client
            if use_po and po_token:
                yt_ea["po_token"] = [
                    f"web+{po_token}",
                    f"web.gvs+{po_token}",
                    f"web_embedded+{po_token}",
                    f"default+{po_token}",
                ]
                if visitor_data:
                    yt_ea["visitor_data"] = [visitor_data]
            if yt_ea:
                ea["youtube"] = yt_ea
                opts["extractor_args"] = ea
            return opts

        def _save_and_build_result(info_dict: dict) -> dict:
            yt_id: str = info_dict.get("id", f"vid_{vid_id}")
            title: str = info_dict.get("title") or ""
            description: str = info_dict.get("description") or ""
            raw_tags: list = info_dict.get("tags") or []
            tags_json: str = json.dumps(raw_tags)
            raw_path = cfg.raw_dir / f"{yt_id}.mp4"
            meta_path = cfg.meta_dir / f"{yt_id}.json"
            meta_payload = {
                "id": yt_id,
                "title": title,
                "description": description,
                "tags": raw_tags,
                "webpage_url": info_dict.get("webpage_url", url),
                "uploader": info_dict.get("uploader"),
                "upload_date": info_dict.get("upload_date"),
                "duration": info_dict.get("duration"),
                "view_count": info_dict.get("view_count"),
                "like_count": info_dict.get("like_count"),
            }
            meta_path.write_text(
                json.dumps(meta_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("Metadata saved to %s", meta_path)
            return {
                "video_id": yt_id,
                "title": title,
                "description": description,
                "tags": tags_json,
                "raw_path": str(raw_path),
                "meta_path": str(meta_path),
            }

        # ── Cascade of strategies to bypass YouTube bot blocks on VPS ────── #

        # Strategy 1: Cookies + PO token + Web/TV clients
        try:
            logger.info("  [yt-dlp] Strategy 1: Cookies + PO Token (web/tv clients)...")
            s1_opts = _make_opts(include_cookies=True, client=["web", "web_embedded", "tv"], use_po=True)
            with yt_dlp.YoutubeDL(s1_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info:
                    info = info["entries"][0]
            return _save_and_build_result(info)
        except Exception as exc1:
            logger.warning("  [yt-dlp] Strategy 1 failed: %s", exc1)

        # Strategy 2: Apple Vision/Safari clients (often bypass BotGuard entirely)
        try:
            logger.info("  [yt-dlp] Strategy 2: visionos/web_safari client (Apple bypass)...")
            s2_opts = _make_opts(include_cookies=False, client=["visionos", "web_safari"], use_po=False)
            with yt_dlp.YoutubeDL(s2_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info:
                    info = info["entries"][0]
            logger.info("  [yt-dlp] Strategy 2 (visionos/safari) succeeded!")
            return _save_and_build_result(info)
        except Exception as exc2:
            logger.warning("  [yt-dlp] Strategy 2 failed: %s", exc2)

        # Strategy 3: TV / Embedded client without cookies
        try:
            logger.info("  [yt-dlp] Strategy 3: TV embedded client...")
            s3_opts = _make_opts(include_cookies=False, client=["tv", "tv_embedded"], use_po=False)
            with yt_dlp.YoutubeDL(s3_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info:
                    info = info["entries"][0]
            logger.info("  [yt-dlp] Strategy 3 (TV embedded) succeeded!")
            return _save_and_build_result(info)
        except Exception as exc3:
            logger.warning("  [yt-dlp] Strategy 3 failed: %s", exc3)

        # Strategy 4: Mobile client (mweb/ios)
        try:
            logger.info("  [yt-dlp] Strategy 4: Mobile client (mweb/ios)...")
            s4_opts = _make_opts(include_cookies=False, client=["mweb", "ios"], use_po=False)
            s4_opts["format"] = "bv*+ba/b/best"
            with yt_dlp.YoutubeDL(s4_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info:
                    info = info["entries"][0]
            logger.info("  [yt-dlp] Strategy 4 (mweb/ios) succeeded!")
            return _save_and_build_result(info)
        except Exception as exc4:
            logger.warning("  [yt-dlp] Strategy 4 failed: %s", exc4)

        # Strategy 5: Clean direct default download (no player_client override)
        try:
            logger.info("  [yt-dlp] Strategy 5: Default multi-client resolver (clean direct)...")
            s5_opts = _make_opts(include_cookies=False, client=None, use_po=False)
            with yt_dlp.YoutubeDL(s5_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info:
                    info = info["entries"][0]
            logger.info("  [yt-dlp] Strategy 5 succeeded!")
            return _save_and_build_result(info)
        except Exception as exc5:
            logger.error("  [yt-dlp] Strategy 5 also failed: %s", exc5)

        msg = f"yt-dlp failed all 5 download strategies. Last error: {exc5}"
        logger.error("Video id=%d failed: %s", vid_id, msg)
        update_video(vid_id, {"status": "failed"})
        log_error(vid_id, "ingestion", msg)
        return None


# Re-export for convenience.
__all__ = [
    "parse_urls",
    "IngestionWorker",
    "DownloadWorker",
]
