#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════╗
║           OmniShorts Auto-Publisher (OSAP) v1.0.0                ║
║           CLI Entry Point — manage.py                             ║
╚═══════════════════════════════════════════════════════════════════╝

Usage:
    python manage.py <command> [options]

Commands:
    ingest      Parse URLs from source file and add to queue
    download    Run downloader worker(s)
    render      Run FFmpeg render worker(s)
    publish     Run publisher worker(s) for all/specific platforms
    run-all     Run full pipeline (all workers in parallel)
    setup-auth  Open browser for manual login (persistent profile platforms)
    cleanup     Delete processed video files to free disk space
    status      Show current pipeline statistics
    reset-stuck Fix jobs stuck in intermediate states (>30 min)
    info        Show system info (OS, GPU, encoder, paths)
"""

import argparse
import asyncio
import multiprocessing
import os
import sys
import time
from pathlib import Path

# Ensure project root is on the Python path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

console = Console()


def _ensure_env():
    """Load .env if it exists."""
    from dotenv import load_dotenv
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
    else:
        console.print(
            "[yellow]Warning:[/yellow] .env file not found. "
            "Copy .env.example to .env and fill in your values.",
            style="yellow"
        )


def _init_db():
    """Initialize the database schema."""
    from osap.config import get_config
    from osap.db.models import init_db
    cfg = get_config()
    cfg.ensure_dirs()
    init_db(cfg.DB_PATH)


# ─────────────────────────────────────────────
# Command: ingest
# ─────────────────────────────────────────────
def cmd_ingest(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config
    from osap.modules.ingestion import IngestionWorker

    cfg = get_config()
    source = args.source or str(cfg.ASSETS_DIR / "urls.txt")
    worker = IngestionWorker(source_file=source, db_path=cfg.DB_PATH)
    worker.run()


# ─────────────────────────────────────────────
# Command: download
# ─────────────────────────────────────────────
def cmd_download(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config
    from osap.modules.ingestion import DownloadWorker

    cfg = get_config()
    workers_count = args.workers or cfg.WORKERS_DOWNLOADER
    worker = DownloadWorker(db_path=cfg.DB_PATH, workers=workers_count)
    worker.run()


# ─────────────────────────────────────────────
# Command: render
# ─────────────────────────────────────────────
def cmd_render(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config
    from osap.modules.processor import VideoProcessor

    cfg = get_config()
    worker = VideoProcessor(db_path=cfg.DB_PATH)
    worker.run()


# ─────────────────────────────────────────────
# Command: publish
# ─────────────────────────────────────────────
def cmd_publish(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config
    from osap.modules.publisher import PublisherOrchestrator

    cfg = get_config()
    platform_filter = args.platform or None
    orchestrator = PublisherOrchestrator(
        db_path=cfg.DB_PATH,
        platform_filter=platform_filter
    )
    asyncio.run(orchestrator.run())


# ─────────────────────────────────────────────
# Command: run-all (full pipeline, parallel)
# ─────────────────────────────────────────────
def _run_downloader_proc(db_path, workers):
    """Target for multiprocessing.Process — runs the download worker."""
    from osap.modules.ingestion import DownloadWorker
    w = DownloadWorker(db_path=db_path, workers=workers)
    w.run()


def _run_renderer_proc(db_path):
    """Target for multiprocessing.Process — runs the render worker."""
    from osap.modules.processor import VideoProcessor
    w = VideoProcessor(db_path=db_path)
    w.run()


def _run_publisher_proc(db_path):
    """Target for multiprocessing.Process — runs the publisher orchestrator."""
    import asyncio
    from osap.modules.publisher import PublisherOrchestrator
    orchestrator = PublisherOrchestrator(db_path=db_path)
    asyncio.run(orchestrator.run())


def cmd_run_all(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config

    cfg = get_config()

    console.print(Panel.fit(
        "[bold green]Starting OSAP Full Pipeline[/bold green]\n"
        "Workers: Downloader + Renderer + Publisher running in parallel",
        border_style="green"
    ))

    processes = []

    # Downloader worker(s)
    dl_proc = multiprocessing.Process(
        target=_run_downloader_proc,
        args=(cfg.DB_PATH, cfg.WORKERS_DOWNLOADER),
        name="OSAP-Downloader",
        daemon=True
    )
    dl_proc.start()
    processes.append(dl_proc)
    console.print(f"[green]✓[/green] Downloader started (PID {dl_proc.pid})")

    # Renderer worker
    rn_proc = multiprocessing.Process(
        target=_run_renderer_proc,
        args=(cfg.DB_PATH,),
        name="OSAP-Renderer",
        daemon=True
    )
    rn_proc.start()
    processes.append(rn_proc)
    console.print(f"[green]✓[/green] Renderer started (PID {rn_proc.pid})")

    # Publisher orchestrator
    pb_proc = multiprocessing.Process(
        target=_run_publisher_proc,
        args=(cfg.DB_PATH,),
        name="OSAP-Publisher",
        daemon=True
    )
    pb_proc.start()
    processes.append(pb_proc)
    console.print(f"[green]✓[/green] Publisher started (PID {pb_proc.pid})")

    console.print("\n[dim]Press Ctrl+C to stop all workers.[/dim]\n")

    try:
        # Monitor processes
        while any(p.is_alive() for p in processes):
            time.sleep(5)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping all workers...[/yellow]")
        for p in processes:
            p.terminate()
        for p in processes:
            p.join(timeout=10)
        console.print("[green]All workers stopped.[/green]")


# ─────────────────────────────────────────────
# Command: setup-auth
# ─────────────────────────────────────────────
def cmd_setup_auth(args):
    """Open a browser with the persistent profile for manual login."""
    _ensure_env()
    from osap.config import get_config

    cfg = get_config()
    target_key = getattr(args, "target_key", None) or platform
    base_platform = getattr(args, "base_platform", None)
    if not base_platform:
        try:
            from osap.db.queue import get_platform_target
            tgt = get_platform_target(target_key, cfg.DB_PATH)
            if tgt:
                base_platform = tgt["platform"]
        except Exception:
            pass

    if not base_platform:
        for bp in ("youtube", "facebook", "instagram", "twitter_nsfw", "twitter", "tiktok", "upscrolled", "febspot"):
            if target_key.startswith(bp):
                base_platform = bp
                break
        if not base_platform:
            base_platform = target_key

    account_id = getattr(args, "account_id", 1) or 1
    profiles_dir = cfg.PROFILES_DIR if account_id == 1 else (cfg.PROFILES_DIR / f"account_{account_id}")
    profiles_dir.mkdir(parents=True, exist_ok=True)

    proxy_url = getattr(cfg, 'PROXY_URL', None) or os.environ.get('PROXY_URL')

    PERSISTENT_PLATFORMS = {"youtube": "https://studio.youtube.com", "febspot": "https://febspot.com"}
    COOKIE_PLATFORMS = {
        "tiktok": "https://www.tiktok.com/login",
        "instagram": "https://www.instagram.com/accounts/login/",
        "facebook": "https://www.facebook.com/login",
        "twitter": "https://x.com/login?lang=id",
        "twitter_nsfw": "https://x.com/login?lang=id",
        "upscrolled": "https://upscrolled.com/login",
    }

    async def _open_browser():
        from playwright.async_api import async_playwright
        from osap.modules.publisher.stealth import apply_stealth, get_launch_options

        launch_args = ['--disable-blink-features=AutomationControlled']
        launch_kwargs = {
            'headless': False,
            'args': launch_args,
        }
        if proxy_url:
            launch_kwargs['proxy'] = {'server': proxy_url}

        async with async_playwright() as p:
            if base_platform in PERSISTENT_PLATFORMS:
                profile_dir = profiles_dir / target_key
                profile_dir.mkdir(parents=True, exist_ok=True)
                url = PERSISTENT_PLATFORMS[base_platform]
                console.print(
                    f"[cyan]Opening persistent browser for [bold]{target_key}[/bold] ({base_platform})[/cyan]\n"
                    f"Profile directory: [dim]{profile_dir}[/dim]\n"
                    f"Navigate to [link]{url}[/link] and log in.\n"
                    f"[yellow]Close the browser window when done.[/yellow]"
                )
                context = await p.chromium.launch_persistent_context(
                    str(profile_dir),
                    **launch_kwargs,
                )
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(url)
                # Keep open until user closes
                try:
                    await page.wait_for_event("close", timeout=0)
                except Exception:
                    pass
                try:
                    storage_path = profiles_dir / f"{target_key}_storage.json"
                    await context.storage_state(path=str(storage_path))
                    console.print(f"[green]✓ Session also saved to {storage_path}[/green]")
                except Exception:
                    pass
                try:
                    cookies = await context.cookies()
                    if cookies:
                        lines = ["# Netscape HTTP Cookie File\n# http://curl.haxx.se/rfc/cookie_spec.html\n\n"]
                        for c in cookies:
                            domain = c.get("domain", "")
                            flag = "TRUE" if domain.startswith(".") else "FALSE"
                            path = c.get("path", "/")
                            secure = "TRUE" if c.get("secure", False) else "FALSE"
                            expires = int(c.get("expires", 0))
                            if expires <= 0:
                                expires = 2147483647
                            name = c.get("name", "")
                            value = c.get("value", "")
                            lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
                        cookie_file = profiles_dir / f"{target_key}_cookies.txt"
                        cookie_file.write_text("".join(lines), encoding="utf-8")
                        console.print(f"[green]✓ Exported {len(cookies)} cookies to {cookie_file.name} for yt-dlp[/green]")
                except Exception:
                    pass
                await context.close()

            elif base_platform in COOKIE_PLATFORMS:
                url = COOKIE_PLATFORMS[base_platform]
                storage_path = profiles_dir / f"{target_key}_storage.json"
                console.print(
                    f"[cyan]Opening browser for [bold]{target_key}[/bold] cookie capture ({base_platform})[/cyan]\n"
                    f"Log in at: [link]{url}[/link]\n"
                    f"[yellow]After login, close the browser and session will be saved automatically.[/yellow]\n"
                    f"Storage state will be saved to: [dim]{storage_path}[/dim]"
                )
                browser = await p.chromium.launch(**launch_kwargs)
                context = await browser.new_context()
                await apply_stealth(context)
                page = await context.new_page()
                await page.goto(url)
                # Wait for user to finish logging in
                console.print("\n[dim]Waiting for you to log in... Close the browser window when done.[/dim]")
                try:
                    await page.wait_for_event("close", timeout=0)
                except Exception:
                    pass
                # Save session
                await context.storage_state(path=str(storage_path))
                await browser.close()
                console.print(f"[green]✓ Session saved to {storage_path}[/green]")
            else:
                console.print(f"[red]Unknown platform:[/red] {base_platform}")
                console.print(f"Available: {', '.join(list(PERSISTENT_PLATFORMS) + list(COOKIE_PLATFORMS))}")
                sys.exit(1)


    asyncio.run(_open_browser())


# ─────────────────────────────────────────────
# Command: cleanup
# ─────────────────────────────────────────────
def cmd_cleanup(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config
    from osap.modules.cleanup import CleanupWorker

    cfg = get_config()
    worker = CleanupWorker(db_path=cfg.DB_PATH, dry_run=args.dry_run)
    worker.run()


# ─────────────────────────────────────────────
# Command: status
# ─────────────────────────────────────────────
def cmd_status(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config
    from osap.db.queue import get_stats

    cfg = get_config()
    stats = get_stats(cfg.DB_PATH)

    # Header
    console.print(Panel.fit(
        "[bold cyan]OSAP Pipeline Status[/bold cyan]",
        border_style="cyan"
    ))

    # Video status table
    video_table = Table(title="Videos by Status", border_style="dim")
    video_table.add_column("Status", style="bold")
    video_table.add_column("Count", justify="right")

    STATUS_COLORS = {
        "pending": "white", "downloading": "yellow", "downloaded": "cyan",
        "rendering": "yellow", "rendered": "cyan", "uploading": "yellow",
        "done": "green", "failed": "red"
    }
    for status, count in stats.get("by_status", {}).items():
        color = STATUS_COLORS.get(status, "white")
        video_table.add_row(f"[{color}]{status}[/{color}]", str(count))
    video_table.add_row("[bold]TOTAL[/bold]", f"[bold]{stats['total']}[/bold]")

    console.print(video_table)

    # Platform stats table
    if stats.get("platforms"):
        plat_table = Table(title="Platform Upload Status", border_style="dim")
        plat_table.add_column("Platform", style="bold cyan")
        plat_table.add_column("Status")
        plat_table.add_column("Count", justify="right")

        for row in stats["platforms"]:
            plat_table.add_row(row["platform"], row["status"], str(row["count"]))
        console.print(plat_table)

    # Errors
    if stats.get("errors", 0) > 0:
        console.print(f"\n[red]⚠  Errors in log:[/red] {stats['errors']}")


# ─────────────────────────────────────────────
# Command: reset-stuck
# ─────────────────────────────────────────────
def cmd_reset_stuck(args):
    _ensure_env()
    _init_db()
    from osap.config import get_config
    from osap.db.queue import reset_stuck

    cfg = get_config()
    reset_stuck(cfg.DB_PATH)
    console.print("[green]✓ Stuck jobs reset.[/green]")


# ─────────────────────────────────────────────
# Command: info
# ─────────────────────────────────────────────
def cmd_info(args):
    _ensure_env()
    from osap.utils.hardware import get_system_info
    from osap.config import get_config

    cfg = get_config()
    info = get_system_info()

    table = Table(title="System Information", border_style="dim")
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")

    for k, v in info.items():
        table.add_row(k, str(v))

    table.add_row("Enabled Platforms", ", ".join(cfg.enabled_platforms) or "(none)")
    table.add_row("DB Path", cfg.DB_PATH)
    table.add_row("Download Dir", str(cfg.DOWNLOAD_DIR))
    table.add_row("Profiles Dir", str(cfg.PROFILES_DIR))

    console.print(table)


# ─────────────────────────────────────────────
# Command: web
# ─────────────────────────────────────────────
def cmd_web(args):
    _ensure_env()
    _init_db()
    import uvicorn
    host = args.host or "0.0.0.0"
    port = args.port or int(os.environ.get("PORT", 8000))
    reload_flag = getattr(args, "reload", False)
    console.print(f"[bold green]Starting OSAP Web Dashboard on http://{host}:{port}[/bold green]")
    uvicorn.run("web.server:app", host=host, port=port, reload=reload_flag)


# ─────────────────────────────────────────────
# Argument Parser
# ─────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="osap",
        description="OmniShorts Auto-Publisher — End-to-end YouTube Shorts redistribution pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Parse URLs from source file and add to queue")
    p_ingest.add_argument("--source", "-s", help="Path to URL source file (default: assets/urls.txt)")

    # download
    p_dl = subparsers.add_parser("download", help="Run downloader worker(s)")
    p_dl.add_argument("--workers", "-w", type=int, help="Number of parallel download workers")

    # render
    subparsers.add_parser("render", help="Run FFmpeg render worker")

    # publish
    p_pub = subparsers.add_parser("publish", help="Run publisher for all or specific platform")
    p_pub.add_argument("--platform", "-p", help="Specific platform to publish to (default: all enabled)")

    # run-all
    subparsers.add_parser("run-all", help="Run full pipeline with all workers in parallel")

    # web
    p_web = subparsers.add_parser("web", help="Start the Web Dashboard UI server")
    p_web.add_argument("--host", default="0.0.0.0", help="Host address to bind to (default: 0.0.0.0)")
    p_web.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    p_web.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")

    # setup-auth
    p_auth = subparsers.add_parser("setup-auth", help="Open browser for manual authentication")
    p_auth.add_argument("--platform", "-p", required=True,
                        help="Platform to set up (youtube, tiktok, instagram, etc.)")

    # cleanup
    p_clean = subparsers.add_parser("cleanup", help="Delete video files for completed jobs")
    p_clean.add_argument("--dry-run", action="store_true", help="Preview what would be deleted")

    # status
    subparsers.add_parser("status", help="Show pipeline statistics")

    # reset-stuck
    subparsers.add_parser("reset-stuck", help="Reset jobs stuck in intermediate states")

    # info
    subparsers.add_parser("info", help="Show system information (OS, GPU, encoder)")

    return parser


COMMANDS = {
    "ingest": cmd_ingest,
    "download": cmd_download,
    "render": cmd_render,
    "publish": cmd_publish,
    "run-all": cmd_run_all,
    "web": cmd_web,
    "setup-auth": cmd_setup_auth,
    "cleanup": cmd_cleanup,
    "status": cmd_status,
    "reset-stuck": cmd_reset_stuck,
    "info": cmd_info,
}



if __name__ == "__main__":
    # Required for multiprocessing on Windows
    multiprocessing.freeze_support()

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handler = COMMANDS.get(args.command)
    if not handler:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Fatal error:[/red] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
