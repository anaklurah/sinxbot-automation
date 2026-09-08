"""
osap/modules/on_demand.py
─────────────────────────
Just-In-Time (JIT) video processing and multi-platform publishing engine.
Links reside in "Gudang Konten" (pending queue) without consuming disk storage.
When publishing is initiated (manually or via prime-time scheduler), 1 video is:
  1. Downloaded Just-In-Time (yt-dlp)
  2. Rendered with full anti-hash filters + center-left watermark (FFmpeg)
  3. AI-captioned (DeepSeek)
  4. Distributed to all enabled platform(s) for the active account
  5. Cleaned up immediately from internal disk storage!
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from osap.config import get_config
from osap.db.queue import (
    claim_next,
    get_active_account,
    get_video_by_id,
    init_platform_rows,
    log_error,
    mark_platform_done,
    mark_platform_failed,
    mark_platform_uploading,
    update_video,
)
from osap.modules.caption_ai import CaptionAI
from osap.modules.ingestion import DownloadWorker
from osap.modules.processor import VideoProcessor
from osap.modules.publisher import _load_publishers
from osap.utils.logger import get_logger

logger = get_logger("osap.on_demand")


async def run_jit_video_pipeline(
    target_platforms: Optional[List[str]] = None,
    account_id: Optional[int] = None,
    db_path: Optional[str] = None,
    auto_cleanup: bool = True,
) -> Dict[str, Any]:
    """
    Execute a Just-In-Time video pipeline:
    1. Resolve active account.
    2. Claim or JIT-download + render 1 video from the "Gudang Konten".
    3. Generate AI viral caption with DeepSeek.
    4. Distribute this 1 video across target platforms.
    5. Clean up raw & rendered video files from disk to prevent internal memory overuse.

    Returns:
        Dict with status, message, video_id, and platform results.
    """
    cfg = get_config()
    db_path = db_path or cfg.DB_PATH

    # Resolve account
    if account_id is None:
        try:
            active_acc = get_active_account(db_path)
            account_id = active_acc["id"]
        except Exception:
            account_id = 1

    registry = _load_publishers()

    # Resolve target platforms
    if target_platforms is None:
        enabled = cfg.enabled_platforms
        platforms_to_run = [p for p in enabled if p in registry]
    else:
        platforms_to_run = [p for p in target_platforms if p in registry]

    if not platforms_to_run:
        msg = "Tidak ada platform yang aktif / diaktifkan untuk publikasi video."
        logger.warning(f"[JIT Pipeline] {msg}")
        return {"success": False, "message": msg, "results": {}}

    logger.info(
        f"[JIT Pipeline] Starting distribution for Account #{account_id} "
        f"across {len(platforms_to_run)} platform(s): {', '.join(platforms_to_run)}"
    )

    # ─────────────────────────────────────────────────────────────
    # Step 1: Claim or JIT-Process 1 Video
    # ─────────────────────────────────────────────────────────────
    video = None

    # Priority 1: Already rendered video
    video = claim_next("rendered", "uploading", db_path, account_id=account_id)

    # Priority 2: Downloaded video waiting to be rendered
    if video is None:
        video = claim_next("downloaded", "rendering", db_path, account_id=account_id)
        if video is not None:
            vid_id = video["id"]
            logger.info(f"[JIT Pipeline] Video #{vid_id} is downloaded. Rendering with FFmpeg anti-hash filters & watermark...")
            processor = VideoProcessor(db_path=db_path)
            rendered_path = processor._render_video(video)
            if not rendered_path:
                logger.error(f"[JIT Pipeline] Rendering failed for video #{vid_id}")
                update_video(vid_id, {"status": "failed"}, db_path=db_path)
                return {"success": False, "message": f"Gagal render video #{vid_id}", "video_id": vid_id}
            update_video(vid_id, {"status": "uploading", "rendered_path": rendered_path}, db_path=db_path)
            video = get_video_by_id(vid_id, db_path=db_path)

    # Priority 3: Pending video from Gudang Konten (JIT Download & Render)
    if video is None:
        video = claim_next("pending", "downloading", db_path, account_id=account_id)
        if video is not None:
            vid_id = video["id"]
            url = video.get("url")
            logger.info(f"[JIT Pipeline] JIT Download for video #{vid_id} ({url})...")

            downloader = DownloadWorker(db_path=db_path)
            dl_res = downloader._download_video(video)
            if not dl_res:
                logger.error(f"[JIT Pipeline] Download failed for video #{vid_id}")
                update_video(vid_id, {"status": "failed"}, db_path=db_path)
                return {"success": False, "message": f"Gagal men-download video #{vid_id}", "video_id": vid_id}

            update_video(
                vid_id,
                {
                    "status": "rendering",
                    "video_id": dl_res["video_id"],
                    "title": dl_res["title"],
                    "description": dl_res["description"],
                    "tags": dl_res["tags"],
                    "raw_path": dl_res["raw_path"],
                    "meta_path": dl_res["meta_path"],
                },
                db_path=db_path,
            )
            video = get_video_by_id(vid_id, db_path=db_path)

            logger.info(f"[JIT Pipeline] JIT Rendering video #{vid_id} with FFmpeg anti-hash & watermark...")
            processor = VideoProcessor(db_path=db_path)
            rendered_path = processor._render_video(video)
            if not rendered_path:
                logger.error(f"[JIT Pipeline] Rendering failed for video #{vid_id}")
                update_video(vid_id, {"status": "failed"}, db_path=db_path)
                return {"success": False, "message": f"Gagal render video #{vid_id}", "video_id": vid_id}
            update_video(vid_id, {"status": "uploading", "rendered_path": rendered_path}, db_path=db_path)
            video = get_video_by_id(vid_id, db_path=db_path)

    if video is None:
        msg = "Gudang Konten kosong. Tidak ada video pending/siap unggah."
        logger.warning(f"[JIT Pipeline] {msg}")
        return {"success": False, "message": msg, "results": {}}

    vid_id = video["id"]
    rendered_path = video.get("rendered_path")
    raw_path = video.get("raw_path")
    meta_path = video.get("meta_path")

    if not rendered_path or not Path(rendered_path).exists():
        msg = f"File hasil render tidak ditemukan untuk video #{vid_id}"
        logger.error(f"[JIT Pipeline] {msg}: {rendered_path}")
        update_video(vid_id, {"status": "failed"}, db_path=db_path)
        return {"success": False, "message": msg, "video_id": vid_id}

    # ─────────────────────────────────────────────────────────────
    # Step 2: Generate AI Captions (DeepSeek)
    # ─────────────────────────────────────────────────────────────
    title = video.get("title") or "Shorts Video"
    description = video.get("description") or ""
    original_tags = []
    if video.get("tags"):
        try:
            original_tags = json.loads(video["tags"])
        except Exception:
            original_tags = []

    captions = {
        "title": title[:100],
        "description": description[:300],
        "hashtags": original_tags[:15] or ["#shorts", "#viral", "#trending"],
    }

    if cfg.DEEPSEEK_API_KEY:
        try:
            logger.info("[JIT Pipeline] Generating viral caption with DeepSeek AI...")
            caption_ai = CaptionAI(
                api_key=cfg.DEEPSEEK_API_KEY,
                model=cfg.DEEPSEEK_MODEL,
                system_prompt=cfg.CAPTION_SYSTEM_PROMPT or None,
            )
            captions = await caption_ai.generate(
                title=title,
                description=description,
                tags=original_tags,
            )
            update_video(
                vid_id,
                {
                    "ai_title": captions.get("title"),
                    "ai_description": captions.get("description"),
                    "ai_tags": json.dumps(captions.get("hashtags", [])),
                },
                db_path=db_path,
            )
            logger.info(f"[JIT Pipeline] AI Title: {captions.get('title')}")
        except Exception as e:
            logger.warning(f"[JIT Pipeline] DeepSeek AI fallback: {e}")

    # ─────────────────────────────────────────────────────────────
    # Step 3: Distribute this 1 video across target platforms
    # ─────────────────────────────────────────────────────────────
    init_platform_rows(vid_id, platforms_to_run, db_path=db_path)

    platform_results: Dict[str, bool] = {}
    any_success = False

    for i, platform in enumerate(platforms_to_run):
        if i > 0 and cfg.DELAY_BETWEEN_PLATFORMS > 0:
            logger.info(f"[JIT Pipeline] Jeda {cfg.DELAY_BETWEEN_PLATFORMS}s sebelum platform berikutnya ({platform})...")
            await asyncio.sleep(cfg.DELAY_BETWEEN_PLATFORMS)

        mark_platform_uploading(vid_id, platform, db_path=db_path)
        publisher_cls = registry[platform]

        logger.info(f"[JIT Pipeline] 🚀 Publishing video #{vid_id} to {platform.title()} (Account #{account_id})...")
        try:
            publisher = publisher_cls(account_id=account_id)
            upload_title = captions.get("title") or title
            upload_desc = captions.get("description") or description
            upload_tags = captions.get("hashtags") or []

            pub_success = await publisher.run_upload(
                video_path=rendered_path,
                title=upload_title,
                description=upload_desc,
                tags=upload_tags,
            )

            if pub_success:
                mark_platform_done(vid_id, platform, db_path=db_path)
                platform_results[platform] = True
                any_success = True
                logger.info(f"[JIT Pipeline] ✓ Berhasil publikasi ke {platform.title()}!")
            else:
                mark_platform_failed(vid_id, platform, "Upload returned False", db_path=db_path)
                platform_results[platform] = False
                logger.warning(f"[JIT Pipeline] ✗ Gagal publikasi ke {platform.title()}")

        except Exception as exc:
            logger.exception(f"[JIT Pipeline] Error uploading to {platform}: {exc}")
            mark_platform_failed(vid_id, platform, str(exc), db_path=db_path)
            platform_results[platform] = False

    # ─────────────────────────────────────────────────────────────
    # Step 4: Final Status & Auto-Cleanup of Local Storage
    # ─────────────────────────────────────────────────────────────
    if any_success:
        update_video(vid_id, {"status": "done"}, db_path=db_path)
        status_text = "done"
    else:
        update_video(vid_id, {"status": "failed"}, db_path=db_path)
        status_text = "failed"

    # Auto-cleanup files to keep internal disk space minimal
    if auto_cleanup:
        cleaned_files = []
        for file_path_str in (raw_path, rendered_path, meta_path):
            if file_path_str:
                fp = Path(file_path_str)
                if fp.exists():
                    try:
                        fp.unlink()
                        cleaned_files.append(fp.name)
                    except Exception as clean_err:
                        logger.warning(f"[JIT Cleanup] Could not delete {fp}: {clean_err}")

        # Clear path pointers from DB
        update_video(vid_id, {"raw_path": None, "rendered_path": None, "meta_path": None}, db_path=db_path)
        logger.info(
            f"[JIT Cleanup] 🧹 Internal storage preserved: cleaned {len(cleaned_files)} files for video #{vid_id} ({', '.join(cleaned_files)})"
        )

    summary_msg = f"Video #{vid_id} selesai diproses ({'sukses' if any_success else 'gagal'})."
    return {
        "success": any_success,
        "message": summary_msg,
        "video_id": vid_id,
        "status": status_text,
        "results": platform_results,
    }


async def run_single_video_pipeline(platform: str, db_path: Optional[str] = None) -> bool:
    """Convenience wrapper for single platform upload."""
    res = await run_jit_video_pipeline(target_platforms=[platform], db_path=db_path, auto_cleanup=True)
    return res.get("success", False)
