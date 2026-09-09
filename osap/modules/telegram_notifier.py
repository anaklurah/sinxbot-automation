"""
osap/modules/telegram_notifier.py
─────────────────────────────────
Telegram Bot notifier for OSAP.
Sends real-time post summaries, direct content URLs, and system alerts to a Telegram chat.
"""

from __future__ import annotations

import asyncio
import datetime
import html
from typing import Dict, List, Optional, Tuple

import requests

from osap.config import get_config
from osap.utils.logger import get_logger

logger = get_logger("osap.telegram")


def send_telegram_message_sync(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
    timeout: int = 15,
) -> bool:
    """Send a message to Telegram synchronously."""
    cfg = get_config()
    token = token or getattr(cfg, "TELEGRAM_BOT_TOKEN", None)
    chat_id = chat_id or getattr(cfg, "TELEGRAM_CHAT_ID", None)

    if not token or not chat_id:
        logger.debug("[Telegram] Bot token or Chat ID not configured. Skipping.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            logger.info("[Telegram] Message sent successfully to chat %s", chat_id)
            return True
        else:
            err_desc = data.get("description", resp.text)
            logger.error("[Telegram] API error (%d): %s", resp.status_code, err_desc)
            return False
    except Exception as exc:
        logger.exception("[Telegram] Failed to send message: %s", exc)
        return False


async def send_telegram_message(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
) -> bool:
    """Send a message to Telegram asynchronously."""
    return await asyncio.to_thread(
        send_telegram_message_sync,
        text=text,
        token=token,
        chat_id=chat_id,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )


def test_telegram_connection(bot_token: str, chat_id: str) -> Tuple[bool, str]:
    """Test connection by getting bot info and sending a test message."""
    if not bot_token or not chat_id:
        return False, "Bot Token dan Chat ID wajib diisi."

    try:
        # Step 1: Verify Bot Token via getMe
        me_url = f"https://api.telegram.org/bot{bot_token}/getMe"
        resp = requests.get(me_url, timeout=10)
        me_data = resp.json()
        if not (resp.status_code == 200 and me_data.get("ok")):
            return False, f"Bot Token tidak valid: {me_data.get('description', 'Unknown error')}"

        bot_username = me_data.get("result", {}).get("username", "Bot")

        # Step 2: Send test message
        test_msg = (
            f"🤖 <b>Tes Koneksi Sinxbot Automation</b>\n\n"
            f"✅ Bot: <b>@{bot_username}</b>\n"
            f"📅 Waktu: <code>{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
            f"Koneksi Telegram berhasil terhubung dan siap menerima link postingan otomatis!"
        )
        msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        msg_resp = requests.post(
            msg_url,
            json={"chat_id": chat_id, "text": test_msg, "parse_mode": "HTML"},
            timeout=10,
        )
        msg_data = msg_resp.json()
        if msg_resp.status_code == 200 and msg_data.get("ok"):
            return True, f"Koneksi sukses! Pesan uji coba terkirim ke Chat ID {chat_id} via @{bot_username}."
        else:
            return False, f"Gagal mengirim pesan: {msg_data.get('description', 'Unknown error')}"

    except Exception as exc:
        return False, f"Terjadi kesalahan saat menguji koneksi: {exc}"


async def send_post_summary_to_telegram(
    video_title: str,
    post_links: Dict[str, str],
    failed_platforms: Optional[List[str]] = None,
    watermark_info: Optional[str] = None,
) -> bool:
    """Format and send publication summary to Telegram."""
    cfg = get_config()
    enabled = getattr(cfg, "TELEGRAM_ENABLED", True)
    if not enabled:
        logger.debug("[Telegram] Telegram notifications are disabled in config.")
        return False

    now_str = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    safe_title = html.escape(video_title or "Tanpa Judul")

    lines = [
        "🚀 <b>Laporan Publikasi Konten Sinxbot</b>",
        "────────────────────────",
        f"🎬 <b>Judul:</b> {safe_title}",
        f"📅 <b>Waktu:</b> <code>{now_str}</code>",
    ]

    if watermark_info:
        lines.append(f"🏷️ <b>Watermark:</b> <code>{html.escape(watermark_info)}</code>")

    lines.append("")
    lines.append("🔗 <b>Link Postingan Terbaru:</b>")

    platform_icons = {
        "twitter": ("Twitter / X", "🐦"),
        "x": ("Twitter / X", "🐦"),
        "instagram": ("Instagram", "📸"),
        "tiktok": ("TikTok", "🎵"),
        "facebook": ("Facebook", "📘"),
        "upscrolled": ("Upscrolled", "⚡"),
        "febspot": ("Febspot", "📹"),
        "youtube": ("YouTube", "▶️"),
    }

    if post_links:
        for target_key, url in post_links.items():
            base_key = target_key.lower().split("_")[0]
            label, icon = platform_icons.get(base_key, (target_key.replace("_", " ").title(), "🌐"))
            display_name = target_key.replace("_", " ").title()
            if url and url.startswith("http"):
                lines.append(f"{icon} <b>{display_name}:</b> <a href=\"{url}\">Lihat Postingan</a>\n   <code>{url}</code>")
            elif url:
                lines.append(f"{icon} <b>{display_name}:</b> {html.escape(url)}")
            else:
                lines.append(f"{icon} <b>{display_name}:</b> <i>(Link tidak terdeteksi)</i>")
    else:
        lines.append("<i>Tidak ada link postingan yang terdeteksi.</i>")

    if failed_platforms:
        lines.append("")
        lines.append("⚠️ <b>Gagal Publikasi:</b>")
        for fp in failed_platforms:
            lines.append(f"• <s>{html.escape(fp.replace('_', ' ').title())}</s>")

    lines.append("")
    lines.append("✅ <i>Laporan otomatis dari Sinxbot Automation System.</i>")

    full_message = "\n".join(lines)
    return await send_telegram_message(full_message, disable_web_page_preview=False)