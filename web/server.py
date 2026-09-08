"""
OmniShorts Auto-Publisher (OSAP) — Web Dashboard Backend (FastAPI)
"""

import asyncio
import logging
import json
import multiprocessing
import os
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


class SchedulerManager:
    def __init__(self):
        self.process: Optional[multiprocessing.Process] = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def start_scheduler(self, db_path: str):
        if self.is_running():
            raise HTTPException(status_code=400, detail="Scheduler is already running")

        def _run_target():
            import asyncio
            from osap.modules.scheduler import run_scheduler
            try:
                asyncio.run(run_scheduler(db_path=db_path))
            except (KeyboardInterrupt, SystemExit):
                pass

        p = multiprocessing.Process(target=_run_target, name="osap_scheduler", daemon=True)
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

class ConfigUpdateRequest(BaseModel):
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

    from osap.modules.scheduler import get_next_prime_time, DEFAULT_PRIME_TIME_SLOTS
    _, remaining_secs, next_slot = get_next_prime_time()

    scheduler_info = {
        "active": is_scheduler_active,
        "next_slot": next_slot,
        "remaining_seconds": int(remaining_secs),
        "slots": DEFAULT_PRIME_TIME_SLOTS,
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
    if cfg.DEEPSEEK_API_KEY:
        key = cfg.DEEPSEEK_API_KEY
        api_key_masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"

    return {
        "yaml": yaml_data,
        "env": {
            "DEEPSEEK_API_KEY_MASKED": api_key_masked,
            "DEEPSEEK_MODEL": cfg.DEEPSEEK_MODEL,
            "WORKERS_DOWNLOADER": cfg.WORKERS_DOWNLOADER,
            "HEADLESS": cfg.HEADLESS,
            "WATERMARK_ENABLED": getattr(cfg, "WATERMARK_ENABLED", True),
            "WATERMARK_TEXT": getattr(cfg, "WATERMARK_TEXT", "SINXBOT"),
            "WATERMARK_FONT_SIZE": getattr(cfg, "WATERMARK_FONT_SIZE", 32),
            "enabled_platforms": {p: getattr(cfg, f"PLATFORM_{p.upper()}", True) for p in PLATFORMS}
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

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, default_flow_style=False)

    # Update .env if deepseek key, headless, or platform toggles changed
    env_updates = {}
    if req.watermark_enabled is not None:
        env_updates["WATERMARK_ENABLED"] = "true" if req.watermark_enabled else "false"
        os.environ["WATERMARK_ENABLED"] = "true" if req.watermark_enabled else "false"
    if req.watermark_text is not None:
        env_updates["WATERMARK_TEXT"] = req.watermark_text
        os.environ["WATERMARK_TEXT"] = req.watermark_text
    if req.watermark_font_size is not None:
        env_updates["WATERMARK_FONT_SIZE"] = str(req.watermark_font_size)
        os.environ["WATERMARK_FONT_SIZE"] = str(req.watermark_font_size)
    if req.deepseek_api_key and not req.deepseek_api_key.startswith("****"):
        env_updates["DEEPSEEK_API_KEY"] = req.deepseek_api_key
        os.environ["DEEPSEEK_API_KEY"] = req.deepseek_api_key
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
async def list_platform_states(account_id: Optional[int] = Query(None)):
    """List 8 supported platforms, enabled status, and auth profile existence for selected account."""
    cfg = get_config(reload=True)
    from osap.db.queue import get_active_account
    acc_id = account_id
    if acc_id is None:
        try:
            active_acc = get_active_account(cfg.DB_PATH)
            acc_id = active_acc["id"]
        except Exception:
            acc_id = 1

    profiles_dir = cfg.PROFILES_DIR if acc_id == 1 else (cfg.PROFILES_DIR / f"account_{acc_id}")

    enabled_set = set(cfg.enabled_platforms)
    result = []
    persistent_platforms = ["febspot"]

    for p in PLATFORMS:
        enabled = (p in enabled_set)
        
        # Check profile auth file/folder
        auth_status = False
        if p in persistent_platforms:
            prof_dir = profiles_dir / p
            auth_status = prof_dir.exists() and any(prof_dir.iterdir()) if prof_dir.exists() else False
        else:
            storage_json = profiles_dir / f"{p}_storage.json"
            cookies_txt = profiles_dir / f"{p}_cookies.txt"
            cookies_json = profiles_dir / f"{p}_cookies.json"
            prof_dir = profiles_dir / p
            auth_status = (
                storage_json.exists()
                or cookies_txt.exists()
                or cookies_json.exists()
                or (prof_dir.exists() and any(prof_dir.iterdir()))
            )

        result.append({
            "id": p,
            "name": p.replace("_", " ").title(),
            "enabled": enabled,
            "auth_status": "configured" if auth_status else "missing",
            "auth_type": "persistent" if p in persistent_platforms else "cookies/storage_state"
        })

    return {"platforms": result, "account_id": acc_id}


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


def _run_setup_auth_target(platform_name: str, account_id: int):
    """Top-level process target for running setup-auth flow."""
    from manage import cmd_setup_auth
    class SetupArgs:
        def __init__(self, p_name, acc_id):
            self.platform = p_name
            self.account_id = acc_id

    cmd_setup_auth(SetupArgs(platform_name, account_id))


@app.post("/api/setup-auth/{platform}")
async def setup_platform_auth(platform: str, account_id: Optional[int] = Query(None)):
    """Run non-headless interactive login browser in a separate process."""
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    cfg = get_config()
    from osap.db.queue import get_active_account
    acc_id = account_id
    if acc_id is None:
        acc = get_active_account(cfg.DB_PATH)
        acc_id = acc["id"]

    p = multiprocessing.Process(
        target=_run_setup_auth_target,
        args=(platform, acc_id),
        name=f"setup_auth_{platform}_{acc_id}"
    )
    p.start()

    return {
        "success": True,
        "message": f"Jendela login browser untuk {platform} (Akun #{acc_id}) telah dibuka. Silakan login (bisa isi captcha/2FA), sesi otomatis tersimpan saat jendela ditutup!"
    }


@app.post("/api/upload-cookies/{platform}")
async def upload_platform_cookies(platform: str, file: UploadFile = File(...), account_id: Optional[int] = Query(None)):
    """Upload cookie file (.txt or .json) or storage_state for a platform."""
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    cfg = get_config()
    from osap.db.queue import get_active_account
    acc_id = account_id
    if acc_id is None:
        acc_id = get_active_account(cfg.DB_PATH)["id"]

    profiles_dir = cfg.PROFILES_DIR if acc_id == 1 else (cfg.PROFILES_DIR / f"account_{acc_id}")
    profiles_dir.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename.lower() if file.filename else ""
    stripped = contents.strip()

    # Determine filename format: storage_state.json vs cookies.txt
    if filename.endswith(".json") or stripped.startswith(b"[") or stripped.startswith(b"{"):
        save_path = profiles_dir / f"{platform}_storage.json"
    else:
        save_path = profiles_dir / f"{platform}_cookies.txt"

    with open(save_path, "wb") as f:
        f.write(contents)

    # Validate cookie readability
    from osap.modules.publisher.cookie_loader import load_cookies
    try:
        parsed = load_cookies(save_path)
    except Exception as e:
        parsed = []

    count = len(parsed)
    logger.info(f"Uploaded cookie file for platform {platform} (Account #{acc_id}): {save_path.name} ({count} cookies parsed)")

    if count > 0:
        storage_path = profiles_dir / f"{platform}_storage.json"
        try:
            with open(storage_path, "w", encoding="utf-8") as sf:
                json.dump({"cookies": parsed, "origins": []}, sf, indent=2)
            save_path = storage_path
        except Exception as e:
            logger.warning(f"Could not write normalized storage state for {platform}: {e}")

    if count == 0:
        return {
            "success": True,
            "filename": file.filename,
            "saved_to": save_path.name,
            "cookies_count": 0,
            "message": f"Cookie file saved to {save_path.name}, but 0 valid cookies were parsed. Verify file format."
        }

    return {
        "success": True,
        "filename": file.filename,
        "saved_to": save_path.name,
        "cookies_count": count,
        "message": f"Successfully uploaded and normalized {count} cookies for {platform} (Account #{acc_id})!"
    }


def _run_manual_publish_target(db_path: str, platform_name: str, account_id: int):
    """Top-level process target for on-demand single-video publishing."""
    import asyncio
    from osap.modules.on_demand import run_jit_video_pipeline
    try:
        asyncio.run(run_jit_video_pipeline(target_platforms=[platform_name], account_id=account_id, db_path=db_path, auto_cleanup=True))
    except (KeyboardInterrupt, SystemExit):
        pass


def _run_publish_all_target(db_path: str, account_id: int):
    """Top-level process target for distributing 1 video to ALL enabled platforms."""
    import asyncio
    from osap.modules.on_demand import run_jit_video_pipeline
    try:
        asyncio.run(run_jit_video_pipeline(target_platforms=None, account_id=account_id, db_path=db_path, auto_cleanup=True))
    except (KeyboardInterrupt, SystemExit):
        pass


@app.post("/api/pipeline/publish-all")
async def trigger_publish_all(account_id: Optional[int] = Query(None)):
    """Trigger JIT 1-video download, render with watermark & anti-hash, and publish to all platforms."""
    cfg = get_config()
    from osap.db.queue import get_active_account

    acc_id = account_id
    if acc_id is None:
        acc_id = get_active_account(cfg.DB_PATH)["id"]

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
        args=(cfg.DB_PATH, acc_id),
        name=f"publish_all_{acc_id}"
    )
    p.start()

    return {
        "success": True,
        "message": f"Memulai distribusi 1 video ke seluruh platform aktif untuk Akun #{acc_id} (Just-In-Time download & render)... Pantau log di bawah!"
    }


@app.post("/api/publish/{platform}")
async def trigger_manual_publish(platform: str, account_id: Optional[int] = Query(None)):
    """Trigger on-demand single-platform publish (JIT Download -> Render -> Caption -> Post)."""
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    cfg = get_config()
    from osap.db.queue import get_active_account

    acc_id = account_id
    if acc_id is None:
        acc_id = get_active_account(cfg.DB_PATH)["id"]

    # Check if platform is enabled in config
    enabled = set(cfg.enabled_platforms)
    if platform not in enabled:
        raise HTTPException(
            status_code=400,
            detail=f"Platform '{platform}' is not enabled. Enable it in the Config tab first."
        )

    with db_session(cfg.DB_PATH) as conn:
        total_available = conn.execute("SELECT COUNT(*) FROM videos WHERE status IN ('pending', 'downloaded', 'rendered')").fetchone()[0]

    if total_available == 0:
        raise HTTPException(
            status_code=400,
            detail="Gudang Konten kosong. Silakan masukkan link video di tab Ingest terlebih dahulu."
        )

    p = multiprocessing.Process(
        target=_run_manual_publish_target,
        args=(cfg.DB_PATH, platform, acc_id),
        name=f"manual_publish_{platform}_{acc_id}",
        daemon=True
    )
    p.start()

    msg = f"On-Demand Post dimulai untuk {platform} (Akun #{acc_id}). Memproses JIT dan upload... Pantau prosesnya di Live Logs!"
    logger.info(msg)
    return {
        "success": True,
        "message": msg,
    }


@app.get("/api/logs/stream")
async def stream_logs(request: Request):
    """SSE endpoint for streaming real-time system logs with graceful disconnect."""
    queue = asyncio.Queue()
    log_subscribers.append(queue)

    async def log_generator():
        try:
            yield "data: {\"message\": \"Connected to OSAP Live Log Stream\"}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    log_msg = await asyncio.wait_for(queue.get(), timeout=1.5)
                    yield f"data: {log_msg}\n\n"
                except asyncio.TimeoutError:
                    continue
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            if queue in log_subscribers:
                log_subscribers.remove(queue)

    return StreamingResponse(log_generator(), media_type="text/event-stream")
