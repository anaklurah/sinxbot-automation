"""
osap/modules/scheduler.py
─────────────────────────
Prime-Time Automated Scheduler for OSAP.
Automatically posts videos 3 times a day during prime-time hours
(default: 12:00, 18:00, 21:00 local time).
"""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import List, Optional, Tuple

from osap.config import get_config
from osap.modules.on_demand import run_jit_video_pipeline, run_single_video_pipeline
from osap.utils.logger import get_logger

logger = get_logger("osap.scheduler")

# Default Prime-Time Slots (24-hour format)
DEFAULT_PRIME_TIME_SLOTS: List[str] = ["12:00", "18:00", "21:00"]


def get_configured_timezone(tz_name: Optional[str] = None) -> datetime.tzinfo:
    """
    Returns a tzinfo object for the configured timezone.
    Supports standard IANA names ("Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura", "UTC")
    and Indonesian abbreviations ("WIB", "WITA", "WIT").
    Falls back gracefully to fixed offset if tzdata is not available on Windows.
    """
    if not tz_name:
        try:
            cfg = get_config()
            tz_name = getattr(cfg, "TIMEZONE", "Asia/Jakarta")
        except Exception:
            tz_name = "Asia/Jakarta"

    aliases = {
        "WIB": "Asia/Jakarta",
        "WITA": "Asia/Makassar",
        "WIT": "Asia/Jayapura",
    }
    raw_name = (tz_name or "Asia/Jakarta").strip()
    canonical = aliases.get(raw_name.upper(), raw_name)

    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(canonical)
    except Exception:
        # Fallback offsets in case system/Python has no tzdata database (e.g. Windows without tzdata package)
        offsets = {
            "Asia/Jakarta": 7,
            "WIB": 7,
            "Asia/Makassar": 8,
            "WITA": 8,
            "Asia/Jayapura": 9,
            "WIT": 9,
            "UTC": 0,
        }
        hours = offsets.get(canonical, 7)
        name = "WIB" if hours == 7 else ("WITA" if hours == 8 else ("WIT" if hours == 9 else canonical))
        return datetime.timezone(datetime.timedelta(hours=hours), name=name)


def get_next_prime_time(
    slots: Optional[List[str]] = None,
    tz: Optional[datetime.tzinfo] = None,
) -> Tuple[datetime.datetime, float, str]:
    """
    Calculate the next prime-time slot and seconds remaining in the configured timezone.
    
    Returns:
        (target_datetime, seconds_remaining, slot_str)
    """
    cfg = get_config()
    if not slots:
        slots = getattr(cfg, "PRIME_TIME_SLOTS", None) or DEFAULT_PRIME_TIME_SLOTS

    if tz is None:
        tz = get_configured_timezone(getattr(cfg, "TIMEZONE", "Asia/Jakarta"))

    now = datetime.datetime.now(tz)
    today = now.date()

    candidates: List[Tuple[datetime.datetime, str]] = []

    # Check today's slots
    for s in sorted(slots):
        h, m = map(int, s.split(":"))
        candidate = datetime.datetime(today.year, today.month, today.day, h, m, 0, tzinfo=tz)
        if candidate > now:
            candidates.append((candidate, s))

    # If no more slots today, pick the first slot tomorrow
    if not candidates:
        tomorrow = today + datetime.timedelta(days=1)
        first_slot = sorted(slots)[0]
        h, m = map(int, first_slot.split(":"))
        candidate = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m, 0, tzinfo=tz)
        candidates.append((candidate, first_slot))

    target_dt, slot_str = candidates[0]
    remaining_secs = max(0.0, (target_dt - now).total_seconds())
    return target_dt, remaining_secs, slot_str


async def run_scheduler(db_path: Optional[str] = None, slots: Optional[List[str]] = None):
    """
    Main asynchronous loop for Prime-Time Scheduler.
    Sleeps until scheduled hour, then triggers JIT video pipeline for all enabled platforms.
    """
    cfg = get_config()
    db_path = db_path or cfg.DB_PATH

    logger.info(f"[Scheduler] 🕒 Smart Scheduler started.")

    while True:
        try:
            current_cfg = get_config(reload=True)
            active_slots = slots or getattr(current_cfg, "PRIME_TIME_SLOTS", None) or DEFAULT_PRIME_TIME_SLOTS
            tz = get_configured_timezone(getattr(current_cfg, "TIMEZONE", "Asia/Jakarta"))

            target_dt, remaining_secs, slot_str = get_next_prime_time(active_slots, tz=tz)
            hours = int(remaining_secs // 3600)
            minutes = int((remaining_secs % 3600) // 60)
            tz_abbr = target_dt.tzname() or "WIB"
            
            logger.info(
                f"[Scheduler] ⏳ Next scheduled post at {slot_str} {tz_abbr} ({target_dt.strftime('%d/%m %H:%M')}) — "
                f"waiting {hours}h {minutes}m (Schedule: {', '.join(active_slots)})..."
            )

            # Sleep in intervals of up to 15 seconds to allow responsive cancellation
            while remaining_secs > 0:
                sleep_chunk = min(remaining_secs, 15.0)
                await asyncio.sleep(sleep_chunk)
                # Recalculate remaining against timezone-aware clock
                now = datetime.datetime.now(tz)
                remaining_secs = (target_dt - now).total_seconds()

            # Time reached!
            logger.info(f"[Scheduler] ⏰ Prime-time slot {slot_str} reached! Initiating multi-account automated posting...")
            
            import random
            from osap.db.models import db_session
            from osap.db.queue import list_platform_targets
            from osap.modules.cleanup import prune_done_videos_and_caches

            active_targets = [t for t in list_platform_targets(db_path) if t.get("enabled", 1) == 1]
            if not active_targets:
                logger.warning("[Scheduler] No active platform targets in database. Skipping this prime-time slot.")
            else:
                # Find all accounts that currently have pending videos
                accounts_with_pending: list[int | None] = []
                with db_session(db_path) as conn:
                    rows = conn.execute(
                        "SELECT DISTINCT account_id FROM videos WHERE status IN ('pending', 'downloaded', 'rendered') ORDER BY account_id"
                    ).fetchall()
                    accounts_with_pending = [r[0] for r in rows]

                if not accounts_with_pending:
                    logger.info("[Scheduler] Tidak ada video pending di seluruh akun. Slot dilewati.")
                else:
                    logger.info(
                        f"[Scheduler] 🚀 Ditemukan {len(accounts_with_pending)} akun memiliki video pending. "
                        f"Menjalankan posting bertahap dengan random jitter..."
                    )
                    success_count = 0
                    for idx, acc_id in enumerate(accounts_with_pending, 1):
                        acc_label = f"Akun #{acc_id}" if acc_id else "Default Akun"
                        logger.info(f"[Scheduler] [{idx}/{len(accounts_with_pending)}] Memproses {acc_label}...")
                        try:
                            res = await run_jit_video_pipeline(
                                target_platforms=None,
                                account_id=acc_id,
                                db_path=db_path,
                                auto_cleanup=True,
                                send_telegram=True,
                            )
                            if res.get("success"):
                                success_count += 1
                                logger.info(f"[Scheduler] ✓ {acc_label} berhasil diposting: {res.get('message')}")
                            else:
                                logger.warning(f"[Scheduler] ⚠️ {acc_label}: {res.get('message')}")
                        except Exception as acc_err:
                            logger.error(f"[Scheduler] Error pada {acc_label}: {acc_err}")

                        # Random jitter delay between accounts (10s to 35s) to avoid slamming server & platforms
                        if idx < len(accounts_with_pending):
                            jitter_sec = random.uniform(10.0, 35.0)
                            logger.info(f"[Scheduler] ⏳ Jeda anti-collision antar akun: {jitter_sec:.1f} detik...")
                            await asyncio.sleep(jitter_sec)

                    logger.info(
                        f"[Scheduler] Selesai slot {slot_str}: {success_count}/{len(accounts_with_pending)} akun berhasil diposting."
                    )

            # Auto-prune old done files and caches after slot completion
            try:
                prune_done_videos_and_caches(db_path)
            except Exception as pe:
                logger.debug(f"[Scheduler] Post-slot prune note: {pe}")

            # Sleep 70 seconds past the target minute to avoid double trigger
            await asyncio.sleep(70)

        except asyncio.CancelledError:
            logger.info("[Scheduler] Scheduler loop cancelled. Shutting down gracefully.")
            break
        except Exception as e:
            logger.exception(f"[Scheduler] Error in scheduler loop: {e}")
            await asyncio.sleep(30)
