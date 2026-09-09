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
    send_telegram: bool = True,
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

    from osap.db.queue import list_platform_targets
    all_targets = list_platform_targets(db_path)
    target_map = {t["target_key"]: t for t in all_targets}

    # Resolve target platforms / cards
    if target_platforms is None:
        targets_to_run = [
            t for t in all_targets 
            if t.get("enabled", 1) == 1 and t.get("platform") in registry
        ]
    else:
        targets_to_run = []
        for p in target_platforms:
            if p in target_map:
                tgt = target_map[p]
                if tgt.get("platform") in registry:
                    targets_to_run.append(tgt)
            else:
                matching = [t for t in all_targets if t.get("platform") == p and t.get("platform") in registry]
                if matching:
                    targets_to_run.extend(matching)
                elif p in registry:
                    targets_to_run.append({
                        "target_key": p,
                        "platform": p,
                        "name": p.replace("_", " ").title(),
                        "enabled": 1,
                        "watermark_text": "",
                        "watermark_enabled": 1,
                    })

    # Deduplicate targets while preserving order
    seen_keys = set()
    unique_targets = []
    for t in targets_to_run:
        if t["target_key"] not in seen_keys:
            seen_keys.add(t["target_key"])
            unique_targets.append(t)
    targets_to_run = unique_targets

    if not targets_to_run:
        msg = "Tidak ada platform target yang aktif / diaktifkan untuk publikasi video."
        logger.warning(f"[JIT Pipeline] {msg}")
        return {"success": False, "message": msg, "results": {}}

    target_display_names = [t.get("name") or t["target_key"] for t in targets_to_run]
    logger.info(
        f"[JIT Pipeline] Starting distribution across {len(targets_to_run)} target(s): {', '.join(target_display_names)}"
    )

    # ─────────────────────────────────────────────────────────────
    # Step 1: Claim or JIT-Download 1 Video from Gudang Konten
    # ─────────────────────────────────────────────────────────────
    video = None

    # Priority 1: Already rendered or downloaded video
    video = claim_next("rendered", "uploading", db_path, account_id=account_id)
    if video is None:
        video = claim_next("downloaded", "uploading", db_path, account_id=account_id)

    # Priority 2: Pending video from Gudang Konten (JIT Download)
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
                    "status": "uploading",
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

    if video is None:
        msg = "Gudang Konten kosong. Tidak ada video pending/siap unggah."
        logger.warning(f"[JIT Pipeline] {msg}")
        return {"success": False, "message": msg, "results": {}}

    vid_id = video["id"]
    raw_path = video.get("raw_path")
    meta_path = video.get("meta_path")

    # If raw_path missing but rendered_path exists, use rendered_path as base
    if (not raw_path or not Path(raw_path).exists()) and video.get("rendered_path"):
        raw_path = video.get("rendered_path")

    if not raw_path or not Path(raw_path).exists():
        msg = f"File video mentah tidak ditemukan untuk video #{vid_id}"
        logger.error(f"[JIT Pipeline] {msg}: {raw_path}")
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
    # Step 3: Render and Distribute with Per-Target Watermark
    # ─────────────────────────────────────────────────────────────
    target_keys_to_run = [t["target_key"] for t in targets_to_run]
    init_platform_rows(vid_id, target_keys_to_run, db_path=db_path)

    processor = VideoProcessor(db_path=db_path)
    rendered_cache: Dict[tuple, str] = {}  # (watermark_text, watermark_enabled) -> file_path
    platform_results: Dict[str, bool] = {}
    any_success = False

    for i, target in enumerate(targets_to_run):
        target_key = target["target_key"]
        base_platform = target["platform"]
        target_name = target.get("name") or target_key.replace("_", " ").title()
        wm_text = target.get("watermark_text") or ""
        wm_enabled = bool(target.get("watermark_enabled", 1))

        if i > 0:
            import random
            base_delay = cfg.DELAY_BETWEEN_PLATFORMS if cfg.DELAY_BETWEEN_PLATFORMS > 0 else 25
            jitter = random.randint(-5, 12)
            smart_delay = max(15, base_delay + jitter)
            logger.info(f"[JIT Pipeline] 🛡️ Smart Anti-Ban: Menunggu jeda natural {smart_delay}s sebelum posting ke {target_name}...")
            await asyncio.sleep(smart_delay)

        mark_platform_uploading(vid_id, target_key, db_path=db_path)
        publisher_cls = registry[base_platform]

        # Render custom video for this target if watermark is unique
        cache_key = (wm_text, wm_enabled)
        if cache_key not in rendered_cache:
            logger.info(f"[JIT Pipeline] Rendering video #{vid_id} with watermark: '{wm_text}' (active={wm_enabled}) for {target_name}...")
            rendered_file = processor._render_video(
                video,
                watermark_text=wm_text,
                watermark_enabled=wm_enabled,
                output_suffix=f"_{target_key}"
            )
            if not rendered_file:
                logger.error(f"[JIT Pipeline] Failed to render video for target {target_name}")
                mark_platform_failed(vid_id, target_key, "Render failed", db_path=db_path)
                platform_results[target_key] = False
                continue
            rendered_cache[cache_key] = rendered_file

        target_rendered_path = rendered_cache[cache_key]

        logger.info(f"[JIT Pipeline] 🚀 Publishing video #{vid_id} to {target_name} ({base_platform})...")
        try:
            publisher = publisher_cls(account_id=account_id, target_key=target_key)
            upload_title = captions.get("title") or title
            upload_desc = captions.get("description") or description
            upload_tags = captions.get("hashtags") or []

            pub_success = await publisher.run_upload(
                video_path=target_rendered_path,
                title=upload_title,
                description=upload_desc,
                tags=upload_tags,
            )

            if pub_success:
                mark_platform_done(vid_id, target_key, db_path=db_path)
                platform_results[target_key] = True
                any_success = True
                logger.info(f"[JIT Pipeline] ✓ Berhasil publikasi ke {target_name}!")
            else:
                mark_platform_failed(vid_id, target_key, "Upload returned False", db_path=db_path)
                platform_results[target_key] = False
                logger.warning(f"[JIT Pipeline] ✗ Gagal publikasi ke {target_name}")

        except Exception as exc:
            logger.exception(f"[JIT Pipeline] Error uploading to {target_name}: {exc}")
            mark_platform_failed(vid_id, target_key, str(exc), db_path=db_path)
            platform_results[target_key] = False

    # ─────────────────────────────────────────────────────────────
    # Step 4: Extract Latest Post Links from Profiles & Send Telegram Report
    # ─────────────────────────────────────────────────────────────
    post_links = {}
    successful_targets = [t for t in targets_to_run if platform_results.get(t.get("target_key")) is True]
    failed_target_names = [t.get("name") or t.get("target_key") for t in targets_to_run if platform_results.get(t.get("target_key")) is not True]

    if successful_targets:
        fetch_delay_sec = int(os.environ.get("POST_FETCH_DELAY_SEC") or getattr(cfg, "POST_FETCH_DELAY_SEC", 180))
        if fetch_delay_sec > 0:
            delay_min = fetch_delay_sec // 60
            delay_remainder = fetch_delay_sec % 60
            time_str = f"{delay_min} menit" if delay_remainder == 0 else f"{delay_min} menit {delay_remainder} detik"
            logger.info(
                f"[JIT Pipeline] ⏳ Menunggu jeda {time_str} ({fetch_delay_sec} detik) agar semua platform selesai memproses & memunculkan postingan terbaru di profil..."
            )
            await asyncio.sleep(fetch_delay_sec)

        logger.info(f"[JIT Pipeline] 📲 Mengambil link postingan terbaru dari profil {len(successful_targets)} target sukses...")
        try:
            from osap.modules.post_fetcher import fetch_all_latest_posts
            post_links = await fetch_all_latest_posts(successful_targets, account_id=account_id)
        except Exception as fetch_err:
            logger.warning(f"[JIT Pipeline] Gagal mengekstrak link profil: {fetch_err}")

        # Send Telegram notification (only if send_telegram=True, e.g. NOT for manual card posts)
        if send_telegram:
            try:
                from osap.modules.telegram_notifier import send_post_summary_to_telegram
                upload_title = captions.get("title") or title
                await send_post_summary_to_telegram(
                    video_title=upload_title,
                    post_links=post_links,
                    failed_platforms=failed_target_names if failed_target_names else None,
                )
            except Exception as tg_err:
                logger.warning(f"[JIT Pipeline] Gagal mengirim notifikasi Telegram: {tg_err}")
        else:
            logger.info("[JIT Pipeline] Telegram notification skipped (manual/card post).")

    # ─────────────────────────────────────────────────────────────
    # Step 5: Final Status & Auto-Cleanup of Local Storage
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
        all_cleanup_paths = [raw_path, meta_path] + list(rendered_cache.values())
        if video.get("rendered_path"):
            all_cleanup_paths.append(video.get("rendered_path"))

        for file_path_str in all_cleanup_paths:
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
        "post_links": post_links,
    }


async def run_single_video_pipeline(platform: str, db_path: Optional[str] = None) -> bool:
    """Convenience wrapper for single platform upload."""
    res = await run_jit_video_pipeline(target_platforms=[platform], db_path=db_path, auto_cleanup=True)
    return res.get("success", False)
