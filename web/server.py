"""
OmniShorts Auto-Publisher (OSAP) — Web Dashboard Backend (FastAPI)
"""

import asyncio
import datetime
import logging
import json
import multiprocessing
import os
import re
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from osap.config import get_config
from osap.db.models import init_db, db_session, PLATFORMS
from osap.db.queue import (
    get_stats, add_urls_batch, get_pending_count, reset_stuck
)
from osap.utils.hardware import get_system_info
from osap.utils.logger import get_logger

logger = get_logger("osap.web")

# ─────────────────────────────────────────────
# SSE Log Handler
# ─────────────────────────────────────────────
log_subscribers: List[asyncio.Queue] = []

class SSELogHandler(logging.Handler):
    """Logging handler that broadcasts log messages to active SSE clients."""
    def emit(self, record: logging.LogRecord):
        try:
            log_entry = {
                "timestamp": self.format_time(record),
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage()
            }
            log_json = json.dumps(log_entry)
            for queue in list(log_subscribers):
                try:
                    queue.put_nowait(log_json)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)

    def format_time(self, record: logging.LogRecord) -> str:
        import datetime
        return datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

sse_handler = SSELogHandler()
sse_handler.setLevel(logging.INFO)
root_logger = logging.getLogger()
root_logger.addHandler(sse_handler)


# ─────────────────────────────────────────────
# Pipeline Process Manager
# ─────────────────────────────────────────────
class PipelineManager:
    def __init__(self):
        self.processes: Dict[str, multiprocessing.Process] = {}

    def is_running(self) -> bool:
        return any(p and p.is_alive() for p in self.processes.values())

    def status(self) -> Dict[str, bool]:
        return {name: (proc is not None and proc.is_alive()) for name, proc in self.processes.items()}

    def start_pipeline(self, db_path: str):
        if self.is_running():
            raise HTTPException(status_code=400, detail="Pipeline is already running")

        from manage import _run_downloader_proc, _run_renderer_proc, _run_publisher_proc
        cfg = get_config()

        p_dl = multiprocessing.Process(target=_run_downloader_proc, args=(db_path, cfg.WORKERS_DOWNLOADER), name="osap_downloader", daemon=True)
        p_rd = multiprocessing.Process(target=_run_renderer_proc, args=(db_path,), name="osap_renderer", daemon=True)
        p_pb = multiprocessing.Process(target=_run_publisher_proc, args=(db_path,), name="osap_publisher", daemon=True)

        p_dl.start()
        p_rd.start()
        p_pb.start()

        self.processes = {
            "downloader": p_dl,
            "renderer": p_rd,
            "publisher": p_pb
        }
        logger.info("Pipeline started via Web Dashboard")

    def stop_pipeline(self):
        stopped = []
        for name, proc in self.processes.items():
            if proc and proc.is_alive():
                proc.terminate()
                proc.join(timeout=3)
                stopped.append(name)
        self.processes.clear()
        logger.info(f"Pipeline stopped via Web Dashboard. Stopped processes: {stopped}")
        return stopped

pipeline_mgr = PipelineManager()


def _run_scheduler_proc(db_path: str):
    """Top-level process target for prime-time scheduler (must be picklable on Windows)."""
    import asyncio
    from osap.modules.scheduler import run_scheduler
    try:
        asyncio.run(run_scheduler(db_path=db_path))
    except (KeyboardInterrupt, SystemExit):
        pass


class SchedulerManager:
    def __init__(self):
        self.process: Optional[multiprocessing.Process] = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def start_scheduler(self, db_path: str):
        if self.is_running():
            raise HTTPException(status_code=400, detail="Scheduler is already running")

        p = multiprocessing.Process(
            target=_run_scheduler_proc,
            args=(db_path,),
            name="osap_scheduler",
            daemon=True,
        )
        p.start()
        self.process = p
        logger.info("Prime-Time Scheduler started via Web Dashboard")

    def stop_scheduler(self):
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=3)
        self.process = None
        logger.info("Prime-Time Scheduler stopped via Web Dashboard")

scheduler_mgr = SchedulerManager()


# ─────────────────────────────────────────────
# FastAPI Lifespan & App Setup
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    cfg.ensure_dirs()
    init_db(cfg.DB_PATH)
    logger.info("OSAP Web Dashboard API starting up...")
    yield
    logger.info("OSAP Web Dashboard API shutting down...")
    pipeline_mgr.stop_pipeline()
    scheduler_mgr.stop_scheduler()
    # Unblock any active SSE log subscribers so uvicorn shuts down cleanly
    for q in list(log_subscribers):
        try:
            q.put_nowait(json.dumps({"message": "Server shutdown"}))
        except Exception:
            pass
    log_subscribers.clear()

app = FastAPI(
    title="OmniShorts Auto-Publisher Dashboard API",
    version="1.0.0",
    lifespan=lifespan
)

# Serve static files
STATIC_DIR = PROJECT_ROOT / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=FileResponse)
async def read_root():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index_path))


# ─────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────
class IngestRequest(BaseModel):
    urls: str = Field(..., description="Newline or comma-separated list of URLs")
    account_id: Optional[int] = None



class CreateAccountRequest(BaseModel):
    name: str

class CreatePlatformTargetRequest(BaseModel):
    platform: str
    name: str
    watermark_text: Optional[str] = ""
    watermark_enabled: Optional[bool] = True

class UpdatePlatformTargetRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    watermark_text: Optional[str] = None
    watermark_enabled: Optional[bool] = None


class ConfigUpdateRequest(BaseModel):
    schedule_slots: Optional[List[str]] = None
    posts_per_hour: Optional[int] = None
    delay_between_platforms_sec: Optional[int] = None
    workers_downloader: Optional[int] = None
    headless: Optional[bool] = None
    ffmpeg_zoom: Optional[float] = None
    ffmpeg_speed: Optional[float] = None
    ffmpeg_noise: Optional[int] = None
    ffmpeg_contrast: Optional[float] = None
    ffmpeg_saturation: Optional[float] = None
    watermark_enabled: Optional[bool] = None
    watermark_text: Optional[str] = None
    watermark_font_size: Optional[int] = None
    deepseek_api_key: Optional[str] = None
    deepseek_model: Optional[str] = None
    enabled_platforms: Optional[Dict[str, bool]] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


class TelegramTestRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


# ─────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────

@app.get("/api/status")
async def get_dashboard_status():
    """Get aggregate DB stats, hardware info, worker status, and prime-time scheduler."""
    cfg = get_config()
    stats = get_stats(cfg.DB_PATH)
    hw_info = get_system_info()
    workers_status = pipeline_mgr.status()
    is_scheduler_active = scheduler_mgr.is_running()
    is_pipeline_active = pipeline_mgr.is_running() or is_scheduler_active

    from osap.modules.scheduler import get_next_prime_time
    active_slots = getattr(cfg, "PRIME_TIME_SLOTS", None) or ["12:00", "18:00", "21:00"]
    _, remaining_secs, next_slot = get_next_prime_time(active_slots)

    scheduler_info = {
        "active": is_scheduler_active,
        "next_slot": next_slot,
        "remaining_seconds": int(remaining_secs),
        "slots": active_slots,
    }

    return {
        "queue_stats": stats,
        "hardware": hw_info,
        "pipeline_active": is_pipeline_active,
        "workers": workers_status,
        "enabled_platforms": cfg.enabled_platforms,
        "scheduler": scheduler_info,
    }


@app.get("/api/videos")
async def list_videos(
    status: Optional[str] = Query(None, description="Filter by status: pending, downloading, downloaded, rendering, rendered, uploading, done, failed"),
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """List videos in queue with pagination and platform status."""
    cfg = get_config()
    offset = (page - 1) * limit

    with db_session(cfg.DB_PATH) as conn:
        cursor = conn.cursor()
        where_conditions = []
        params: List[Any] = []

        if status:
            where_conditions.append("v.status = ?")
            params.append(status)

        if account_id:
            where_conditions.append("v.account_id = ?")
            params.append(account_id)

        where_clause = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""

        # Count total
        count_sql = f"SELECT COUNT(*) FROM videos v {where_clause}"
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]

        # Fetch videos
        query_sql = f"""
            SELECT id, url, video_id, title, status, raw_path, rendered_path, ai_title, created_at, updated_at, error_count, account_id
            FROM videos v
            {where_clause}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query_sql, params + [limit, offset])
        rows = cursor.fetchall()

        videos = []
        for r in rows:
            v_dict = dict(r)

            # Fetch platform upload statuses
            cursor.execute(
                "SELECT platform, status, upload_url, error_msg, attempts FROM platform_uploads WHERE video_id = ?",
                (v_dict["id"],)
            )
            platform_rows = cursor.fetchall()
            v_dict["platforms"] = {p["platform"]: dict(p) for p in platform_rows}
            videos.append(v_dict)

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
        "videos": videos
    }


@app.post("/api/ingest")
async def ingest_urls(req: IngestRequest):
    """Parse and add raw URLs into queue."""
    cfg = get_config()
    raw_lines = req.urls.replace(",", "\n").splitlines()
    cleaned_urls = [line.strip() for line in raw_lines if line.strip() and not line.strip().startswith("#")]

    if not cleaned_urls:
        raise HTTPException(status_code=400, detail="No valid URLs provided")

    added, skipped = add_urls_batch(cleaned_urls, db_path=cfg.DB_PATH, account_id=req.account_id)
    logger.info(f"Ingested via Web Dashboard: {added} added, {skipped} skipped/duplicate into Gudang Konten")

    return {
        "success": True,
        "added": added,
        "skipped": skipped,
        "total_submitted": len(cleaned_urls),
        "message": f"Berhasil menambahkan {added} video ke Gudang Konten."
    }


def _is_valid_new_secret(val: Optional[str]) -> bool:
    """Check if a string is a legitimate new secret and not a masked representation."""
    if not val:
        return False
    v = str(val).strip()
    if not v or "..." in v or v.startswith("****") or v.startswith("***"):
        return False
    return True


def _nested_get(data: dict, *keys, default=None):
    curr = data
    for k in keys:
        if isinstance(curr, dict) and k in curr:
            curr = curr[k]
        else:
            return default
    return curr if curr is not None else default


@app.get("/api/config")
async def read_configuration():
    """Read existing config.yaml and environment settings."""
    cfg = get_config()
    yaml_path = PROJECT_ROOT / "config.yaml"

    yaml_data = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    # Mask API key for security
    api_key_masked = "****"
    raw_deepseek_key = os.environ.get("DEEPSEEK_API_KEY") or cfg.DEEPSEEK_API_KEY
    if raw_deepseek_key:
        key = raw_deepseek_key
        api_key_masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"

    active_slots = getattr(cfg, "PRIME_TIME_SLOTS", None) or ["12:00", "18:00", "21:00"]

    tg_token_masked = "****"
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN") or getattr(cfg, "TELEGRAM_BOT_TOKEN", None) or _nested_get(yaml_data, "telegram", "bot_token", default="")
    if tg_token:
        tg_token_masked = f"{tg_token[:4]}...{tg_token[-4:]}" if len(tg_token) > 8 else "****"

    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID") or getattr(cfg, "TELEGRAM_CHAT_ID", "") or _nested_get(yaml_data, "telegram", "chat_id", default="")

    return {
        "yaml": yaml_data,
        "schedule_slots": active_slots,
        "env": {
            "DEEPSEEK_API_KEY_MASKED": api_key_masked,
            "DEEPSEEK_HAS_KEY": bool(raw_deepseek_key and not raw_deepseek_key.startswith("****") and "..." not in raw_deepseek_key),
            "DEEPSEEK_MODEL": cfg.DEEPSEEK_MODEL,
            "WORKERS_DOWNLOADER": cfg.WORKERS_DOWNLOADER,
            "HEADLESS": cfg.HEADLESS,
            "WATERMARK_ENABLED": getattr(cfg, "WATERMARK_ENABLED", True),
            "WATERMARK_TEXT": getattr(cfg, "WATERMARK_TEXT", "SINXBOT"),
            "WATERMARK_FONT_SIZE": getattr(cfg, "WATERMARK_FONT_SIZE", 32),
            "enabled_platforms": {p: getattr(cfg, f"PLATFORM_{p.upper()}", True) for p in PLATFORMS},
            "TELEGRAM_ENABLED": getattr(cfg, "TELEGRAM_ENABLED", True),
            "TELEGRAM_BOT_TOKEN_MASKED": tg_token_masked,
            "TELEGRAM_HAS_TOKEN": bool(tg_token and not tg_token.startswith("****") and "..." not in tg_token),
            "TELEGRAM_CHAT_ID": tg_chat_id,
        }
    }


@app.post("/api/config")
async def update_configuration(req: ConfigUpdateRequest):
    """Update config.yaml and .env file with new settings."""
    cfg = get_config()
    yaml_path = PROJECT_ROOT / "config.yaml"
    env_path = PROJECT_ROOT / ".env"

    yaml_data = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    # Update YAML fields
    if req.schedule_slots is not None:
        cleaned_slots = [s.strip() for s in req.schedule_slots if ":" in s.strip()]
        if cleaned_slots:
            if "scheduler" not in yaml_data:
                yaml_data["scheduler"] = {}
            yaml_data["scheduler"]["slots"] = cleaned_slots
            cfg.PRIME_TIME_SLOTS = cleaned_slots

    if "rate_limits" not in yaml_data:
        yaml_data["rate_limits"] = {}
    if "ffmpeg" not in yaml_data:
        yaml_data["ffmpeg"] = {}
    if "ai_caption" not in yaml_data:
        yaml_data["ai_caption"] = {}
    if "browser" not in yaml_data:
        yaml_data["browser"] = {}

    if req.posts_per_hour is not None:
        yaml_data["rate_limits"]["posts_per_hour_per_platform"] = req.posts_per_hour
    if req.delay_between_platforms_sec is not None:
        yaml_data["rate_limits"]["delay_between_platforms_sec"] = req.delay_between_platforms_sec
    if req.workers_downloader is not None:
        yaml_data["rate_limits"]["workers_downloader"] = req.workers_downloader

    if req.headless is not None:
        yaml_data["browser"]["headless"] = req.headless

    if req.ffmpeg_zoom is not None:
        yaml_data["ffmpeg"]["zoom_factor"] = req.ffmpeg_zoom
    if req.ffmpeg_speed is not None:
        yaml_data["ffmpeg"]["speed_factor"] = req.ffmpeg_speed
    if req.ffmpeg_noise is not None:
        yaml_data["ffmpeg"]["noise_amount"] = req.ffmpeg_noise
    if req.ffmpeg_contrast is not None:
        yaml_data["ffmpeg"]["contrast"] = req.ffmpeg_contrast
    if req.ffmpeg_saturation is not None:
        yaml_data["ffmpeg"]["saturation"] = req.ffmpeg_saturation

    if req.deepseek_model is not None:
        yaml_data["ai_caption"]["model"] = req.deepseek_model

    if "watermark" not in yaml_data:
        yaml_data["watermark"] = {}
    if req.watermark_enabled is not None:
        yaml_data["watermark"]["enabled"] = req.watermark_enabled
    if req.watermark_text is not None:
        yaml_data["watermark"]["text"] = req.watermark_text
    if req.watermark_font_size is not None:
        yaml_data["watermark"]["font_size"] = req.watermark_font_size

    # Telegram configuration updates
    if "telegram" not in yaml_data:
        yaml_data["telegram"] = {}
    if req.telegram_enabled is not None:
        yaml_data["telegram"]["enabled"] = req.telegram_enabled
    if _is_valid_new_secret(req.telegram_bot_token):
        yaml_data["telegram"]["bot_token"] = req.telegram_bot_token.strip()
    if req.telegram_chat_id is not None and str(req.telegram_chat_id).strip():
        yaml_data["telegram"]["chat_id"] = str(req.telegram_chat_id).strip()

    # Update .env if deepseek key, headless, or platform toggles changed
    env_updates = {}
    if req.telegram_enabled is not None:
        env_updates["TELEGRAM_ENABLED"] = "true" if req.telegram_enabled else "false"
        os.environ["TELEGRAM_ENABLED"] = "true" if req.telegram_enabled else "false"
        cfg.TELEGRAM_ENABLED = req.telegram_enabled
    if _is_valid_new_secret(req.telegram_bot_token):
        clean_token = req.telegram_bot_token.strip()
        env_updates["TELEGRAM_BOT_TOKEN"] = clean_token
        os.environ["TELEGRAM_BOT_TOKEN"] = clean_token
        cfg.TELEGRAM_BOT_TOKEN = clean_token
    if req.telegram_chat_id is not None and str(req.telegram_chat_id).strip():
        clean_chat_id = str(req.telegram_chat_id).strip()
        env_updates["TELEGRAM_CHAT_ID"] = clean_chat_id
        os.environ["TELEGRAM_CHAT_ID"] = clean_chat_id
        cfg.TELEGRAM_CHAT_ID = clean_chat_id
    if req.watermark_enabled is not None:
        env_updates["WATERMARK_ENABLED"] = "true" if req.watermark_enabled else "false"
        os.environ["WATERMARK_ENABLED"] = "true" if req.watermark_enabled else "false"
    if req.watermark_text is not None:
        env_updates["WATERMARK_TEXT"] = req.watermark_text
        os.environ["WATERMARK_TEXT"] = req.watermark_text
    if req.watermark_font_size is not None:
        env_updates["WATERMARK_FONT_SIZE"] = str(req.watermark_font_size)
        os.environ["WATERMARK_FONT_SIZE"] = str(req.watermark_font_size)
    if _is_valid_new_secret(req.deepseek_api_key):
        clean_deepseek_key = req.deepseek_api_key.strip()
        env_updates["DEEPSEEK_API_KEY"] = clean_deepseek_key
        os.environ["DEEPSEEK_API_KEY"] = clean_deepseek_key
        cfg.DEEPSEEK_API_KEY = clean_deepseek_key
    if req.deepseek_model:
        env_updates["DEEPSEEK_MODEL"] = req.deepseek_model
        os.environ["DEEPSEEK_MODEL"] = req.deepseek_model
    if req.headless is not None:
        env_val = "true" if req.headless else "false"
        env_updates["HEADLESS"] = env_val
        os.environ["HEADLESS"] = env_val

    if req.enabled_platforms:
        if "platforms" not in yaml_data:
            yaml_data["platforms"] = {}
        for p, enabled in req.enabled_platforms.items():
            yaml_data["platforms"][p] = enabled
            env_key = f"PLATFORM_{p.upper()}"
            if p == "twitter_nsfw":
                env_key = "PLATFORM_TWITTER_NSF"
            env_val = "true" if enabled else "false"
            env_updates[env_key] = env_val
            os.environ[env_key] = env_val

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, default_flow_style=False)

    if env_updates:
        lines = []
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        updated_keys = set()
        new_lines = []
        for line in lines:
            line_str = line.strip()
            if "=" in line_str and not line_str.startswith("#"):
                k, _ = line_str.split("=", 1)
                k = k.strip()
                if k in env_updates:
                    new_lines.append(f"{k}={env_updates[k]}\n")
                    updated_keys.add(k)
                    continue
            new_lines.append(line)

        for k, v in env_updates.items():
            if k not in updated_keys:
                new_lines.append(f"{k}={v}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    # Reload singleton config in memory
    get_config(reload=True)

    logger.info("Configuration updated via Web Dashboard")
    return {"success": True, "message": "Configuration saved successfully"}


@app.post("/api/telegram/test")
async def test_telegram_endpoint(req: TelegramTestRequest):
    """Test Telegram Bot connection with provided or saved token and chat ID."""
    cfg = get_config()
    yaml_path = PROJECT_ROOT / "config.yaml"
    yaml_data = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    token = req.bot_token.strip() if _is_valid_new_secret(req.bot_token) else (
        os.environ.get("TELEGRAM_BOT_TOKEN") or getattr(cfg, "TELEGRAM_BOT_TOKEN", None) or _nested_get(yaml_data, "telegram", "bot_token", default="")
    )
    chat_id = req.chat_id.strip() if (req.chat_id and str(req.chat_id).strip()) else (
        os.environ.get("TELEGRAM_CHAT_ID") or getattr(cfg, "TELEGRAM_CHAT_ID", None) or _nested_get(yaml_data, "telegram", "chat_id", default="")
    )

    from osap.modules.telegram_notifier import test_telegram_connection
    success, msg = test_telegram_connection(token, str(chat_id))
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.get("/api/accounts")
async def get_accounts_api():
    """List all account profiles and current active account."""
    cfg = get_config()
    from osap.db.queue import list_accounts, get_active_account
    accounts = list_accounts(cfg.DB_PATH)
    active = get_active_account(cfg.DB_PATH)
    return {"accounts": accounts, "active_account": active}


@app.post("/api/accounts")
async def create_account_api(req: CreateAccountRequest):
    """Create a new account profile."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama akun tidak boleh kosong")
    cfg = get_config()
    from osap.db.queue import create_account
    try:
        acc = create_account(name, cfg.DB_PATH)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membuat akun: {e}")
    p_dir = cfg.PROFILES_DIR / f"account_{acc['id']}"
    p_dir.mkdir(parents=True, exist_ok=True)
    return {"success": True, "account": acc, "message": f"Akun '{name}' berhasil dibuat!"}


@app.post("/api/accounts/active/{account_id}")
async def set_active_account_api(account_id: int):
    """Switch active account."""
    cfg = get_config()
    from osap.db.queue import set_active_account, get_active_account
    set_active_account(account_id, cfg.DB_PATH)
    active = get_active_account(cfg.DB_PATH)
    return {"success": True, "active_account": active, "message": f"Akun aktif diubah ke '{active['name']}'"}


@app.delete("/api/accounts/{account_id}")
async def delete_account_api(account_id: int):
    """Delete an account profile."""
    if account_id == 1:
        raise HTTPException(status_code=400, detail="Akun utama (Default) tidak dapat dihapus")
    cfg = get_config()
    from osap.db.queue import delete_account
    delete_account(account_id, cfg.DB_PATH)
    return {"success": True, "message": "Akun berhasil dihapus"}


@app.get("/api/platforms")
async def list_platform_states():
    """List all dynamic platform target cards, enabled status, watermark settings, and auth status."""
    cfg = get_config(reload=True)
    from osap.db.queue import list_platform_targets
    targets = list_platform_targets(cfg.DB_PATH)

    profiles_dir = Path(cfg.PROFILES_DIR)
    persistent_platforms = {"youtube", "febspot"}
    result = []

    for t in targets:
        t_key = t["target_key"]
        p_base = t["platform"]
        enabled = bool(t["enabled"])

        # Check profile auth file/folder
        auth_status = False
        storage_json = profiles_dir / f"{t_key}_storage.json"
        cookies_txt = profiles_dir / f"{t_key}_cookies.txt"
        cookies_json = profiles_dir / f"{t_key}_cookies.json"
        prof_dir = profiles_dir / t_key

        if storage_json.exists() or cookies_txt.exists() or cookies_json.exists() or (prof_dir.exists() and any(prof_dir.iterdir())):
            auth_status = True
        elif p_base in persistent_platforms:
            base_dir = profiles_dir / p_base
            base_storage = profiles_dir / f"{p_base}_storage.json"
            auth_status = (base_dir.exists() and any(base_dir.iterdir())) or base_storage.exists()
        else:
            base_storage = profiles_dir / f"{p_base}_storage.json"
            base_cookies = profiles_dir / f"{p_base}_cookies.txt"
            auth_status = base_storage.exists() or base_cookies.exists()

        result.append({
            "id": t_key,
            "target_key": t_key,
            "platform": p_base,
            "name": t["name"],
            "enabled": enabled,
            "watermark_text": t.get("watermark_text", ""),
            "watermark_enabled": bool(t.get("watermark_enabled", 1)),
            "is_custom": bool(t.get("is_custom", 0)),
            "auth_status": "configured" if auth_status else "missing",
            "auth_type": "Persistent Profile" if p_base in persistent_platforms else "Cookies / Session State"
        })

    return {"platforms": result}


@app.post("/api/platform-targets")
async def create_platform_target_endpoint(req: CreatePlatformTargetRequest):
    """Add a new target card (e.g. 'Youtube 2', 'Instagram 2')."""
    cfg = get_config()
    from osap.db.queue import create_platform_target, list_platform_targets
    platform = req.platform.lower().strip()
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid base platform: {platform}")

    existing = list_platform_targets(cfg.DB_PATH)
    existing_keys = {t["target_key"] for t in existing}

    # Generate unique slug target_key
    slug = re.sub(r'[^a-zA-Z0-9_]', '_', req.name.strip().lower())
    slug = re.sub(r'_+', '_', slug).strip('_')
    if not slug:
        slug = f"{platform}_target"

    candidate = slug
    idx = 2
    while candidate in existing_keys:
        candidate = f"{slug}_{idx}"
        idx += 1

    target = create_platform_target(
        target_key=candidate,
        platform=platform,
        name=req.name.strip(),
        watermark_text=req.watermark_text or "",
        watermark_enabled=1 if req.watermark_enabled else 0,
        is_custom=1,
        db_path=cfg.DB_PATH
    )
    return {"success": True, "target": target, "message": f"Kartu target '{req.name}' berhasil ditambahkan!"}


@app.patch("/api/platform-targets/{target_key}")
async def update_platform_target_endpoint(target_key: str, req: UpdatePlatformTargetRequest):
    """Update watermark, toggle status, or name for a target card."""
    cfg = get_config()
    from osap.db.queue import update_platform_target, get_platform_target
    fields = {}
    if req.name is not None:
        fields["name"] = req.name
    if req.enabled is not None:
        fields["enabled"] = 1 if req.enabled else 0
    if req.watermark_text is not None:
        fields["watermark_text"] = req.watermark_text
    if req.watermark_enabled is not None:
        fields["watermark_enabled"] = 1 if req.watermark_enabled else 0

    success = update_platform_target(target_key, db_path=cfg.DB_PATH, **fields)
    if not success:
        raise HTTPException(status_code=404, detail=f"Target '{target_key}' not found or no changes made")

    target = get_platform_target(target_key, db_path=cfg.DB_PATH)
    return {"success": True, "target": target}


@app.delete("/api/platform-targets/{target_key}")
async def delete_platform_target_endpoint(target_key: str):
    """Delete a custom platform target card."""
    cfg = get_config()
    from osap.db.queue import delete_platform_target
    success = delete_platform_target(target_key, db_path=cfg.DB_PATH)
    if not success:
        raise HTTPException(status_code=400, detail=f"Kartu bawaan '{target_key}' tidak dapat dihapus, hanya kartu custom yang dapat dihapus.")
    return {"success": True, "message": f"Kartu target '{target_key}' berhasil dihapus."}


@app.post("/api/pipeline/start")
async def start_pipeline_api():
    """Start prime-time automated scheduler (3x daily: 12:00, 18:00, 21:00)."""
    cfg = get_config()
    scheduler_mgr.start_scheduler(cfg.DB_PATH)
    from osap.modules.scheduler import get_next_prime_time
    _, _, next_slot = get_next_prime_time()
    return {
        "success": True,
        "message": f"Prime-Time Scheduler aktif! Posting otomatis 3x sehari (Jadwal terdekat: {next_slot} WIB)."
    }


@app.post("/api/pipeline/stop")
async def stop_pipeline_api():
    """Stop prime-time automated scheduler and active workers."""
    scheduler_mgr.stop_scheduler()
    stopped = pipeline_mgr.stop_pipeline()
    return {"success": True, "stopped": stopped, "message": "Prime-Time Scheduler dinonaktifkan."}


@app.post("/api/reset-stuck")
async def reset_stuck_jobs_api():
    """Reset jobs stuck in temporary states (>30m)."""
    cfg = get_config()
    reset_stuck(cfg.DB_PATH)
    return {"success": True, "message": "Stuck jobs reset"}


def _run_setup_auth_target(target_key: str):
    """Top-level process target for running setup-auth flow."""
    from manage import cmd_setup_auth
    class SetupArgs:
        def __init__(self, t_key):
            self.platform = t_key
            self.target_key = t_key
            self.account_id = 1

    cmd_setup_auth(SetupArgs(target_key))


@app.post("/api/setup-auth/{target_key}")
async def setup_platform_auth(target_key: str):
    """Run non-headless interactive login browser for a specific target card."""
    cfg = get_config()
    from osap.db.queue import get_platform_target
    target = get_platform_target(target_key, cfg.DB_PATH)
    target_name = target["name"] if target else target_key

    p = multiprocessing.Process(
        target=_run_setup_auth_target,
        args=(target_key,),
        name=f"setup_auth_{target_key}"
    )
    p.start()

    return {
        "success": True,
        "message": f"Jendela login browser untuk '{target_name}' telah dibuka. Silakan login (bisa isi captcha/2FA), sesi otomatis tersimpan saat jendela ditutup!"
    }


@app.post("/api/upload-cookies/{target_key}")
async def upload_platform_cookies(target_key: str, file: UploadFile = File(...)):
    """Upload cookie file (.txt or .json) or storage_state for a specific target card."""
    cfg = get_config()
    profiles_dir = Path(cfg.PROFILES_DIR)
    profiles_dir.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename.lower() if file.filename else ""
    stripped = contents.strip()

    is_json = filename.endswith(".json") or stripped.startswith(b"[") or stripped.startswith(b"{")

    from osap.modules.publisher.cookie_loader import load_cookies, export_netscape_cookies

    if is_json:
        save_path = profiles_dir / f"{target_key}_storage.json"
        with open(save_path, "wb") as f:
            f.write(contents)

        try:
            parsed = load_cookies(save_path)
        except Exception:
            parsed = []

        if parsed:
            try:
                with open(save_path, "w", encoding="utf-8") as sf:
                    json.dump({"cookies": parsed, "origins": []}, sf, indent=2)
            except Exception as e:
                logger.warning(f"Could not write normalized storage state for {target_key}: {e}")

            # If YouTube target, export to Netscape format for yt-dlp
            if "youtube" in target_key.lower():
                yt_netscape = profiles_dir / "youtube_cookies.txt"
                try:
                    export_netscape_cookies(parsed, yt_netscape)
                    logger.info("  [yt-dlp] Exported %d cookies from JSON to %s", len(parsed), yt_netscape.name)
                except Exception as e:
                    logger.warning(f"Could not export yt-dlp cookiefile: {e}")
    else:
        save_path = profiles_dir / f"{target_key}_cookies.txt"
        with open(save_path, "wb") as f:
            f.write(contents)

        # For YouTube target, save exact raw bytes as youtube_cookies.txt for yt-dlp
        if "youtube" in target_key.lower():
            yt_netscape = profiles_dir / "youtube_cookies.txt"
            with open(yt_netscape, "wb") as f:
                f.write(contents)
            logger.info(f"  [yt-dlp] Saved raw Netscape cookies directly to {yt_netscape.name}")

        try:
            parsed = load_cookies(save_path)
        except Exception:
            parsed = []

        # Also write storage_state.json for Playwright browser publishers
        if parsed:
            storage_path = profiles_dir / f"{target_key}_storage.json"
            try:
                with open(storage_path, "w", encoding="utf-8") as sf:
                    json.dump({"cookies": parsed, "origins": []}, sf, indent=2)
            except Exception as e:
                logger.warning(f"Could not write storage state for {target_key}: {e}")

    count = len(parsed)
    logger.info(f"Uploaded cookie file for target {target_key}: {save_path.name} ({count} cookies parsed)")

    if count == 0:
        return {
            "success": True,
            "filename": file.filename,
            "saved_to": save_path.name,
            "cookies_count": 0,
            "message": f"Cookie file disimpan ke {save_path.name}, namun 0 cookies terbaca. Pastikan format file benar."
        }

    return {
        "success": True,
        "filename": file.filename,
        "saved_to": save_path.name,
        "cookies_count": count,
        "message": f"Berhasil mengunggah {count} cookies untuk kartu target '{target_key}'!"
    }


def _run_manual_publish_target(db_path: str, target_key: str):
    """Top-level process target for on-demand single-target publishing (no Telegram report)."""
    import asyncio
    from osap.modules.on_demand import run_jit_video_pipeline
    try:
        asyncio.run(run_jit_video_pipeline(
            target_platforms=[target_key],
            db_path=db_path,
            auto_cleanup=True,
            send_telegram=False,  # Manual card post → no Telegram notification
        ))
    except (KeyboardInterrupt, SystemExit):
        pass


def _run_publish_all_target(db_path: str):
    """Top-level process target for distributing 1 video to ALL enabled targets (sends Telegram report)."""
    import asyncio
    from osap.modules.on_demand import run_jit_video_pipeline
    try:
        asyncio.run(run_jit_video_pipeline(
            target_platforms=None,
            db_path=db_path,
            auto_cleanup=True,
            send_telegram=True,  # Scheduled/publish-all → send Telegram notification
        ))
    except (KeyboardInterrupt, SystemExit):
        pass


@app.post("/api/pipeline/publish-all")
async def trigger_publish_all():
    """Trigger JIT 1-video download, render with per-target watermark & anti-hash, and publish to all active targets."""
    cfg = get_config()

    # Check video availability
    with db_session(cfg.DB_PATH) as conn:
        total_available = conn.execute("SELECT COUNT(*) FROM videos WHERE status IN ('pending', 'downloaded', 'rendered')").fetchone()[0]

    if total_available == 0:
        raise HTTPException(
            status_code=400,
            detail="Gudang Konten kosong. Silakan masukkan link video di tab Ingest terlebih dahulu."
        )

    p = multiprocessing.Process(
        target=_run_publish_all_target,
        args=(cfg.DB_PATH,),
        name="publish_all_targets"
    )
    p.start()

    return {
        "success": True,
        "message": "Memulai distribusi 1 video ke seluruh kartu platform aktif (JIT download & render per-target watermark)... Pantau log di bawah!"
    }


@app.post("/api/publish/{target_key}")
async def trigger_manual_publish(target_key: str):
    """Trigger on-demand single-target publish (JIT Download -> Render with Watermark -> Caption -> Post)."""
    cfg = get_config()
    from osap.db.queue import get_platform_target

    target = get_platform_target(target_key, cfg.DB_PATH)
    target_name = target["name"] if target else target_key

    with db_session(cfg.DB_PATH) as conn:
        total_available = conn.execute("SELECT COUNT(*) FROM videos WHERE status IN ('pending', 'downloaded', 'rendered')").fetchone()[0]

    if total_available == 0:
        raise HTTPException(
            status_code=400,
            detail="Gudang Konten kosong. Silakan masukkan link video di tab Ingest terlebih dahulu."
        )

    p = multiprocessing.Process(
        target=_run_manual_publish_target,
        args=(cfg.DB_PATH, target_key),
        name=f"manual_publish_{target_key}",
        daemon=True
    )
    p.start()

    msg = f"On-Demand Post dimulai untuk '{target_name}'. Memproses JIT dan upload... Pantau prosesnya di Live Logs!"
    logger.info(msg)
    return {
        "success": True,
        "message": msg,
    }



def _parse_log_line(line: str) -> Optional[Dict[str, str]]:
    """Parse a '%(asctime)s | %(name)s | %(levelname)s | %(message)s' line from osap.log."""
    raw = line.rstrip("\r\n")
    if not raw:
        return None
    parts = raw.split(" | ", 3)
    if len(parts) == 4:
        date_time = parts[0].strip()
        time_str = date_time.split(" ")[-1] if " " in date_time else date_time
        return {
            "timestamp": time_str,
            "name": parts[1].strip(),
            "level": parts[2].strip(),
            "message": parts[3]
        }
    else:
        lvl = "ERROR" if ("Traceback" in raw or "Error" in raw or "Exception" in raw) else "INFO"
        return {
            "timestamp": "",
            "name": "system",
            "level": lvl,
            "message": raw
        }


def get_recent_logs(max_lines: int = 50) -> List[Dict[str, str]]:
    """Read last N log entries from osap.log."""
    log_file = Path(__file__).resolve().parent.parent / "osap.log"
    if not log_file.exists():
        return []
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        recent = lines[-max_lines:] if len(lines) > max_lines else lines
        parsed = []
        for l in recent:
            p = _parse_log_line(l)
            if p:
                parsed.append(p)
        return parsed
    except Exception as e:
        logger.warning(f"Error reading osap.log: {e}")
        return []


@app.get("/api/logs/recent")
async def get_recent_logs_endpoint(limit: int = Query(50, ge=1, le=200)):
    """Fetch recent historical logs as JSON."""
    return {"logs": get_recent_logs(max_lines=limit)}


@app.get("/api/logs/stream")
async def stream_logs(request: Request):
    """
    SSE endpoint for streaming real-time system logs.
    Tails osap.log for all processes (FastAPI + multiprocessing workers),
    with backlog replay and periodic keepalive comments.
    """
    log_file = Path(__file__).resolve().parent.parent / "osap.log"
    log_file.touch(exist_ok=True)

    async def log_generator():
        try:
            # 1. Connected banner
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            yield f'data: {json.dumps({"timestamp": now_str, "level": "INFO", "name": "system", "message": "Connected to OSAP Live Log Stream"})}\n\n'

            # 2. Replay backlog (last 40 lines)
            backlog = get_recent_logs(max_lines=40)
            for entry in backlog:
                yield f"data: {json.dumps(entry)}\n\n"

            # 3. Tail osap.log
            last_pos = 0
            if log_file.exists():
                try:
                    last_pos = log_file.stat().st_size
                except Exception:
                    last_pos = 0

            idle_ticks = 0

            while True:
                if await request.is_disconnected():
                    break

                had_new_lines = False
                if log_file.exists():
                    try:
                        curr_size = log_file.stat().st_size
                        if curr_size > last_pos:
                            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                                f.seek(last_pos)
                                lines = f.readlines()
                                last_pos = f.tell()
                            for line in lines:
                                parsed = _parse_log_line(line)
                                if parsed:
                                    yield f"data: {json.dumps(parsed)}\n\n"
                                    had_new_lines = True
                        elif curr_size < last_pos:
                            last_pos = 0
                    except Exception:
                        pass

                if had_new_lines:
                    idle_ticks = 0
                else:
                    idle_ticks += 1

                # Send SSE comment heartbeat every 3 seconds (6 ticks * 0.5s) to keep connection alive
                if idle_ticks >= 6:
                    idle_ticks = 0
                    yield ": keepalive\n\n"

                await asyncio.sleep(0.5)

        except (asyncio.CancelledError, GeneratorExit):
            pass

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream"
    }
    return StreamingResponse(log_generator(), media_type="text/event-stream", headers=headers)


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("web.server:app", host="0.0.0.0", port=port, reload=False)

