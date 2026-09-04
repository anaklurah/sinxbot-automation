"""
Publisher Orchestrator — coordinates all 8 platform publishers.

Flow per video:
  1. Claim 'rendered' video → set status 'uploading'
  2. Generate AI captions (DeepSeek)
  3. Create platform_uploads rows
  4. Run each enabled platform publisher with staggered delays
  5. Rate-limit: max posts_per_hour per platform
  6. Update final video status when all platforms finish
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Optional

from osap.config import get_config
from osap.db.queue import (
    claim_next,
    init_platform_rows,
    log_error,
    mark_platform_done,
    mark_platform_failed,
    mark_platform_uploading,
    update_video,
)
from osap.modules.caption_ai import CaptionAI
from osap.utils.logger import get_logger

logger = get_logger(__name__)

# Registry: platform_name → publisher class (lazy import to avoid heavy deps at startup)
PUBLISHER_REGISTRY: dict[str, type] = {}


def _load_publishers() -> dict[str, type]:
    """Lazy-load publisher classes to avoid import errors if optional deps missing."""
    global PUBLISHER_REGISTRY
    if PUBLISHER_REGISTRY:
        return PUBLISHER_REGISTRY

    _imports = [
        ("youtube", "osap.modules.publisher.youtube", "YouTubePublisher"),
        ("facebook", "osap.modules.publisher.facebook", "FacebookPublisher"),
        ("instagram", "osap.modules.publisher.instagram", "InstagramPublisher"),
        ("twitter", "osap.modules.publisher.twitter", "TwitterPublisher"),
        ("twitter_nsfw", "osap.modules.publisher.twitter_nsfw", "TwitterNSFWPublisher"),
        ("tiktok", "osap.modules.publisher.tiktok", "TikTokPublisher"),
        ("upscrolled", "osap.modules.publisher.upscrolled", "UpscrolledPublisher"),
        ("febspot", "osap.modules.publisher.febspot", "FebspotPublisher"),
    ]

    for platform, module_path, class_name in _imports:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            PUBLISHER_REGISTRY[platform] = getattr(mod, class_name)
        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not load publisher for '{platform}': {e}")

    return PUBLISHER_REGISTRY


class PublisherOrchestrator:
    """
    Orchestrates multi-platform video publishing with rate limiting.

    Runs as a continuous worker: polls DB for 'rendered' videos,
    generates AI captions, then publishes to all enabled platforms
    with staggered delays (and per-platform rate limiting).
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        platform_filter: Optional[str] = None,
    ):
        self.cfg = get_config()
        self.db_path = db_path or self.cfg.DB_PATH
        self.platform_filter = platform_filter

        # Rate limiting: {platform: [post_timestamp, ...]}
        self._post_timestamps: dict[str, list[float]] = defaultdict(list)

        # AI caption generator
        self._caption_ai: Optional[CaptionAI] = None
        if self.cfg.DEEPSEEK_API_KEY:
            self._caption_ai = CaptionAI(
                api_key=self.cfg.DEEPSEEK_API_KEY,
                model=self.cfg.DEEPSEEK_MODEL,
                system_prompt=self.cfg.CAPTION_SYSTEM_PROMPT or None,
            )
        else:
            logger.warning(
                "DEEPSEEK_API_KEY not set — captions will fall back to original metadata"
            )

    # ─────────────────────────────────────────
    # Rate Limiting
    # ─────────────────────────────────────────

    def _clean_timestamps(self, platform: str) -> None:
        """Remove timestamps older than 1 hour."""
        cutoff = time.time() - 3600
        self._post_timestamps[platform] = [
            ts for ts in self._post_timestamps[platform] if ts > cutoff
        ]

    def _is_rate_limited(self, platform: str) -> bool:
        """Return True if platform has hit posts_per_hour limit."""
        self._clean_timestamps(platform)
        return len(self._post_timestamps[platform]) >= self.cfg.POSTS_PER_HOUR

    def _record_post(self, platform: str) -> None:
        """Record a successful post timestamp for rate limiting."""
        self._post_timestamps[platform].append(time.time())

    # ─────────────────────────────────────────
    # Caption Generation
    # ─────────────────────────────────────────

    async def _generate_captions(self, video: dict) -> dict:
        """
        Generate AI captions for a video.
        Returns dict with: title (str), description (str), hashtags (list[str])
        """
        original_tags: list[str] = []
        if video.get("tags"):
            try:
                original_tags = json.loads(video["tags"])
            except (json.JSONDecodeError, TypeError):
                original_tags = []

        if self._caption_ai:
            try:
                result = await self._caption_ai.generate(
                    title=video.get("title") or "",
                    description=video.get("description") or "",
                    tags=original_tags,
                )
                return result
            except Exception as e:
                logger.warning(f"Caption AI failed for video {video['id']}: {e}")

        # Fallback: use original metadata
        return {
            "title": (video.get("title") or "")[:100],
            "description": (video.get("description") or "")[:300],
            "hashtags": [f"#{t}" for t in original_tags[:15]],
        }

    # ─────────────────────────────────────────
    # Per-Platform Upload Task
    # ─────────────────────────────────────────

    async def _upload_to_platform(
        self,
        platform: str,
        publisher_cls: type,
        video: dict,
        captions: dict,
    ) -> None:
        """Upload video to a single platform with full error handling."""
        video_id = video["id"]
        rendered_path = video.get("rendered_path")

        if not rendered_path:
            logger.error(f"[{platform}] No rendered_path for video {video_id}")
            mark_platform_failed(video_id, platform, "No rendered file path", self.db_path)
            return

        # Check rate limit
        if self._is_rate_limited(platform):
            logger.info(
                f"[{platform}] Rate limited ({self.cfg.POSTS_PER_HOUR} posts/hr) — "
                "marking as failed (retry next cycle)"
            )
            mark_platform_failed(
                video_id, platform,
                f"Rate limited: {self.cfg.POSTS_PER_HOUR} posts/hr exceeded",
                self.db_path,
            )
            return

        mark_platform_uploading(video_id, platform, self.db_path)

        title = captions.get("title") or video.get("title") or ""
        description = captions.get("description") or video.get("description") or ""
        hashtags: list[str] = captions.get("hashtags") or []

        logger.info(f"[{platform}] ▶ Uploading video {video_id}: {title[:50]!r}")

        try:
            publisher = publisher_cls()
            success = await publisher.run_upload(
                video_path=rendered_path,
                title=title,
                description=description,
                tags=hashtags,
            )
            if success:
                mark_platform_done(video_id, platform, db_path=self.db_path)
                self._record_post(platform)
                logger.info(f"[{platform}] ✓ Upload successful for video {video_id}")
            else:
                mark_platform_failed(video_id, platform, "Upload returned False", self.db_path)
                logger.warning(f"[{platform}] ✗ Upload returned False for video {video_id}")

        except asyncio.TimeoutError:
            msg = "Upload timed out (10 min)"
            mark_platform_failed(video_id, platform, msg, self.db_path)
            log_error(video_id, "publisher", msg, platform=platform, db_path=self.db_path)
            logger.error(f"[{platform}] Timeout for video {video_id}")

        except Exception as e:
            msg = str(e)
            mark_platform_failed(video_id, platform, msg, self.db_path)
            log_error(video_id, "publisher", msg, platform=platform, db_path=self.db_path)
            logger.exception(f"[{platform}] Exception uploading video {video_id}: {e}")

    # ─────────────────────────────────────────
    # Process One Video
    # ─────────────────────────────────────────

    async def _process_video(self, video: dict) -> None:
        """
        Full publish pipeline for one video:
        1. Generate AI captions
        2. Create platform_uploads rows
        3. Upload to all enabled platforms with inter-platform delays
        """
        video_id = video["id"]
        logger.info(
            f"Processing video {video_id}: "
            f"{(video.get('title') or '')[:60]!r}"
        )

        # --- Step 1: Generate AI captions ---
        captions = await self._generate_captions(video)
        ai_tags_json = json.dumps(captions.get("hashtags", []))
        update_video(video_id, {
            "ai_title": captions.get("title"),
            "ai_description": captions.get("description"),
            "ai_tags": ai_tags_json,
        }, self.db_path)
        logger.debug(f"[{video_id}] AI captions: {captions.get('title')!r}")

        # --- Step 2: Determine target platforms ---
        registry = _load_publishers()
        enabled = list(self.cfg.enabled_platforms)

        if self.platform_filter:
            enabled = [p for p in enabled if p == self.platform_filter]
            if not enabled and self.platform_filter in registry:
                enabled = [self.platform_filter]


        target_platforms = [p for p in enabled if p in registry]

        if not target_platforms:
            logger.warning(
                f"No enabled/available platforms for video {video_id}. "
                "Check config.yaml platform toggles and publisher imports."
            )
            update_video(video_id, {"status": "done"}, self.db_path)
            return

        # --- Step 3: Create platform_uploads rows ---
        init_platform_rows(video_id, target_platforms, self.db_path)

        # --- Step 4: Publish with inter-platform delays ---
        delay_sec = self.cfg.DELAY_BETWEEN_PLATFORMS
        logger.info(
            f"[{video_id}] Publishing to {len(target_platforms)} platforms: "
            f"{', '.join(target_platforms)}"
        )

        for i, platform in enumerate(target_platforms):
            if i > 0 and delay_sec > 0:
                logger.debug(
                    f"Waiting {delay_sec}s before publishing to {platform}..."
                )
                await asyncio.sleep(delay_sec)

            publisher_cls = registry[platform]
            await self._upload_to_platform(platform, publisher_cls, video, captions)

        logger.info(f"✓ Video {video_id} publishing cycle complete")

    # ─────────────────────────────────────────
    # Main Loop
    # ─────────────────────────────────────────

    async def run(self) -> None:
        """
        Main publisher loop.
        Polls DB for 'rendered' videos and processes them continuously.
        Exits gracefully on KeyboardInterrupt or when queue is permanently empty.
        """
        idle_poll = getattr(self.cfg, "IDLE_POLL_INTERVAL", 10)
        logger.info("PublisherOrchestrator started — polling for rendered videos")

        consecutive_idle = 0
        MAX_IDLE_CYCLES = 720  # 12 hours at 60s interval, then exit

        while True:
            try:
                video = claim_next("rendered", "uploading", self.db_path)
            except Exception as e:
                logger.error(f"DB error claiming next job: {e}")
                await asyncio.sleep(10)
                continue

            if video is None:
                consecutive_idle += 1
                if consecutive_idle == 1:
                    logger.info(
                        f"Queue empty — polling every {idle_poll}s "
                        f"(will exit after {MAX_IDLE_CYCLES} idle cycles)"
                    )
                if consecutive_idle >= MAX_IDLE_CYCLES:
                    logger.info("Publisher: max idle cycles reached. Shutting down.")
                    break
                await asyncio.sleep(idle_poll)
                continue

            consecutive_idle = 0

            try:
                await self._process_video(video)
            except asyncio.CancelledError:
                logger.info("Publisher cancelled — shutting down gracefully")
                break
            except Exception as e:
                logger.exception(
                    f"Unexpected error processing video {video['id']}: {e}"
                )
                update_video(video["id"], {"status": "failed"}, self.db_path)
                log_error(video["id"], "orchestrator", str(e), db_path=self.db_path)
