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


def get_next_prime_time(slots: Optional[List[str]] = None) -> Tuple[datetime.datetime, float, str]:
    """
    Calculate the next prime-time slot and seconds remaining.
    
    Returns:
        (target_datetime, seconds_remaining, slot_str)
    """
    if not slots:
        slots = DEFAULT_PRIME_TIME_SLOTS

    now = datetime.datetime.now()
    today = now.date()

    candidates: List[Tuple[datetime.datetime, str]] = []

    # Check today's slots
    for s in sorted(slots):
        h, m = map(int, s.split(":"))
        candidate = datetime.datetime(today.year, today.month, today.day, h, m, 0)
        if candidate > now:
            candidates.append((candidate, s))

    # If no more slots today, pick the first slot tomorrow
    if not candidates:
        tomorrow = today + datetime.timedelta(days=1)
        first_slot = sorted(slots)[0]
        h, m = map(int, first_slot.split(":"))
        candidate = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m, 0)
        candidates.append((candidate, first_slot))

    target_dt, slot_str = candidates[0]
    remaining_secs = (target_dt - now).total_seconds()
    return target_dt, remaining_secs, slot_str


async def run_scheduler(db_path: Optional[str] = None, slots: Optional[List[str]] = None):
    """
    Main asynchronous loop for Prime-Time Scheduler.
    Sleeps until prime-time, then triggers on-demand pipeline for all enabled platforms.
    """
    cfg = get_config()
    db_path = db_path or cfg.DB_PATH
    slots = slots or getattr(cfg, "PRIME_TIME_SLOTS", DEFAULT_PRIME_TIME_SLOTS)

    logger.info(f"[Scheduler] 🕒 Prime-Time Scheduler started. Configured slots: {', '.join(slots)}")

    while True:
        try:
            target_dt, remaining_secs, slot_str = get_next_prime_time(slots)
            hours = int(remaining_secs // 3600)
            minutes = int((remaining_secs % 3600) // 60)
            
            logger.info(
                f"[Scheduler] ⏳ Next prime-time post at {slot_str} ({target_dt.strftime('%d/%m %H:%M')}) — "
                f"waiting {hours}h {minutes}m..."
            )

            # Sleep in intervals of up to 15 seconds to allow responsive cancellation
            while remaining_secs > 0:
                sleep_chunk = min(remaining_secs, 15.0)
                await asyncio.sleep(sleep_chunk)
                # Recalculate remaining to handle any system clock adjustments
                now = datetime.datetime.now()
                remaining_secs = (target_dt - now).total_seconds()

            # Time reached!
            logger.info(f"[Scheduler] ⏰ Prime-time slot {slot_str} reached! Initiating automated post...")
            
            enabled_platforms = cfg.enabled_platforms
            if not enabled_platforms:
                logger.warning("[Scheduler] No platforms enabled. Skipping this prime-time slot.")
            else:
                from osap.db.queue import get_active_account
                active_acc = get_active_account(db_path)
                logger.info(
                    f"[Scheduler] 🚀 Running scheduled JIT 1-video post across {len(enabled_platforms)} platforms "
                    f"({', '.join(enabled_platforms)}) for Account #{active_acc['id']} ({active_acc['name']})..."
                )
                res = await run_jit_video_pipeline(
                    target_platforms=enabled_platforms,
                    account_id=active_acc["id"],
                    db_path=db_path,
                    auto_cleanup=True,
                )
                if res.get("success"):
                    logger.info(f"[Scheduler] ✓ Successfully executed scheduled post for slot {slot_str}: {res.get('message')}")
                else:
                    logger.warning(f"[Scheduler] ⚠️ Scheduled post for slot {slot_str} finished with issues: {res.get('message')}")

            # Sleep 70 seconds past the target minute to avoid double trigger
            await asyncio.sleep(70)

        except asyncio.CancelledError:
            logger.info("[Scheduler] Scheduler loop cancelled. Shutting down gracefully.")
            break
        except Exception as e:
            logger.exception(f"[Scheduler] Error in scheduler loop: {e}")
            await asyncio.sleep(30)
