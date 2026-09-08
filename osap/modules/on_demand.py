"""
osap/modules/on_demand.py
─────────────────────────
On-demand single video pipeline for the "Post Now" button.
Takes 1 video from the queue, processes any pending steps (Download -> Render -> Caption),
and immediately publishes it to the specified target platform.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from osap.config import get_config
from osap.db.queue import (
    claim_next,
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


async def run_single_video_pipeline(platform: str, db_path: Optional[str] = None) -> bool:
    """
    End-to-end execution of a single video for a specific platform.
    
    Priority:
    1. If a video is already 'rendered', use it immediately.
    2. Else if a video is 'downloaded', render it with FFmpeg, then publish.
    3. Else if a video is 'pending', download it with yt-dlp, render with FFmpeg, then publish.
    
    Returns True if successfully published, False otherwise.
    """
    cfg = get_config()
    db_path = db_path or cfg.DB_PATH
    
    logger.info(f"[Post Now] Starting on-demand pipeline for platform: {platform}")

    # ─────────────────────────────────────────────────────────────
    # Step 1: Claim or advance a video to 'rendered' state
    # ─────────────────────────────────────────────────────────────
    video = None

    # Priority 1: Try claiming an already rendered video first
    video = claim_next("rendered", "uploading", db_path)
    
    # Priority 2: Try claiming a downloaded video to render
    if video is None:
        video = claim_next("downloaded", "rendering", db_path)
        if video is not None:
            vid_id = video["id"]
            logger.info(f"[Post Now] Video #{vid_id} is downloaded. Rendering with FFmpeg...")
            processor = VideoProcessor(db_path=db_path)
            rendered_path = processor._render_video(video)
            if not rendered_path:
                logger.error(f"[Post Now] Rendering failed for video #{vid_id}")
                update_video(vid_id, {"status": "failed"}, db_path=db_path)
                return False
            update_video(vid_id, {"status": "uploading", "rendered_path": rendered_path}, db_path=db_path)
            video = get_video_by_id(vid_id, db_path=db_path)

    # Priority 3: Claim a pending video to download and render
    if video is None:
        video = claim_next("pending", "downloading", db_path)
        if video is not None:
            vid_id = video["id"]
            url = video.get("url")
            logger.info(f"[Post Now] Downloading video #{vid_id} ({url})...")
            
            downloader = DownloadWorker(db_path=db_path)
            dl_res = downloader._download_video(video)
            if not dl_res:
                logger.error(f"[Post Now] Download failed for video #{vid_id}")
                update_video(vid_id, {"status": "failed"}, db_path=db_path)
                return False

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
            init_platform_rows(vid_id, [platform], db_path=db_path)
            video = get_video_by_id(vid_id, db_path=db_path)

            logger.info(f"[Post Now] Rendering video #{vid_id} with FFmpeg...")
            processor = VideoProcessor(db_path=db_path)
            rendered_path = processor._render_video(video)
            if not rendered_path:
                logger.error(f"[Post Now] Rendering failed for video #{vid_id}")
                update_video(vid_id, {"status": "failed"}, db_path=db_path)
                return False
            update_video(vid_id, {"status": "uploading", "rendered_path": rendered_path}, db_path=db_path)
            video = get_video_by_id(vid_id, db_path=db_path)

    if video is None:
        logger.warning("[Post Now] No available videos found in pending, downloaded, or rendered states.")
        return False

    vid_id = video["id"]
    rendered_path = video.get("rendered_path")
    if not rendered_path or not Path(rendered_path).exists():
        logger.error(f"[Post Now] Rendered file missing for video #{vid_id}: {rendered_path}")
        update_video(vid_id, {"status": "failed"}, db_path=db_path)
        log_error(vid_id, "on_demand", "Rendered file missing", platform=platform, db_path=db_path)
        return False

    # ─────────────────────────────────────────────────────────────
    # Step 2: Generate AI captions (DeepSeek)
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
            logger.info(f"[Post Now] Generating AI viral caption with DeepSeek...")
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
            logger.info(f"[Post Now] AI Title: {captions.get('title')}")
        except Exception as e:
            logger.warning(f"[Post Now] DeepSeek caption generation fallback: {e}")

    # ─────────────────────────────────────────────────────────────
    # Step 3: Publish to Target Platform
    # ─────────────────────────────────────────────────────────────
    registry = _load_publishers()
    publisher_cls = registry.get(platform)
    if not publisher_cls:
        msg = f"Publisher class for '{platform}' not found in registry."
        logger.error(f"[Post Now] {msg}")
        update_video(vid_id, {"status": "failed"}, db_path=db_path)
        log_error(vid_id, "on_demand", msg, platform=platform, db_path=db_path)
        return False

    init_platform_rows(vid_id, [platform], db_path=db_path)
    mark_platform_uploading(vid_id, platform, db_path=db_path)

    logger.info(f"[Post Now] Launching {platform.title()} publisher automation via Playwright...")
    try:
        publisher = publisher_cls()
        upload_title = captions.get("title") or title
        upload_desc = captions.get("description") or description
        upload_tags = captions.get("hashtags") or []

        success = await publisher.run_upload(
            video_path=rendered_path,
            title=upload_title,
            description=upload_desc,
            tags=upload_tags,
        )

        if success:
            mark_platform_done(vid_id, platform, db_path=db_path)
            update_video(vid_id, {"status": "done"}, db_path=db_path)
            logger.info(f"[Post Now] Successfully published video #{vid_id} to {platform.title()}!")
            return True
        else:
            mark_platform_failed(vid_id, platform, "Upload failed or returned False", db_path=db_path)
            update_video(vid_id, {"status": "rendered"}, db_path=db_path)
            logger.warning(f"[Post Now] Upload to {platform.title()} returned False for video #{vid_id}. Status kept as 'rendered' for retry.")
            return False

    except Exception as e:
        msg = f"Exception during upload to {platform}: {e}"
        logger.exception(f"[Post Now] {msg}")
        mark_platform_failed(vid_id, platform, str(e), db_path=db_path)
        update_video(vid_id, {"status": "rendered"}, db_path=db_path)
        log_error(vid_id, "on_demand", str(e), platform=platform, db_path=db_path)
        return False
