"""
OSAP Launcher — Client Lokal Dedicated
======================================
Desktop client for OmniShorts Auto-Publisher (OSAP).
Features:
- Fixed server URL normalization (auto-fixes https://https://...)
- Dashboard: Real-time status cards & stats for employee account
- Gudang Konten: Bulk URL ingest & queue table per-employee
- Config Karyawan:
    * Smart Schedule & Jam Posting (Prime-Time presets, timezone)
    * FFmpeg Anti-Hash Filters (Zoom, Speed, Noise, Contrast, Saturation)
    * Video Watermark (Middle-Left) (Enable, Text, Size, Opacity, Color)
    * Notifikasi Bot Telegram (Enable, Token, Chat ID, Test Button)
    * Dedicated Proxy Setup (Proxy URL + Test Connection)
- Live Logs: Real-time SSE streaming logs directly from server
- Cookies & Browser: Upload cookies or Login via native Edge/Chrome
- Account Security: Change password & session management
- Native custom icon branding
"""

import os
import sys
import json
import time
import queue
import urllib.parse
import threading
import webbrowser
import configparser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import requests
except ImportError:
    requests = None

try:
    import playwright
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# ─────────────────────────────────────────────
# Theme & Colors (Modern Clay / Slate Dark)
# ─────────────────────────────────────────────
BG = "#0f172a"          # Slate 900
CARD_BG = "#1e293b"     # Slate 800
CARD_BORDER = "#334155" # Slate 700
ACCENT = "#6366f1"      # Indigo 500
ACCENT_HOVER = "#4f46e5"
ACCENT_CYAN = "#06b6d4" # Cyan 500
SUCCESS = "#10b981"     # Emerald 500
WARNING = "#f59e0b"     # Amber 500
DANGER = "#ef4444"      # Rose 500
TEXT = "#f8fafc"        # Slate 50
TEXT_DIM = "#94a3b8"    # Slate 400
INPUT_BG = "#0f172a"

PLATFORMS = [
    ("youtube", "YouTube"),
    ("instagram", "Instagram"),
    ("tiktok", "TikTok"),
    ("facebook", "Facebook"),
    ("twitter", "Twitter/X"),
    ("twitter_nsfw", "Twitter NSFW"),
    ("upscrolled", "Upscrolled"),
    ("febspot", "Febspot"),
]

def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    while url.startswith("https://https://") or url.startswith("http://https://"):
        url = url.replace("https://https://", "https://").replace("http://https://", "https://")
    while url.startswith("http://http://") or url.startswith("https://http://"):
        url = url.replace("http://http://", "http://").replace("https://http://", "http://")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url.rstrip("/")

CONFIG_DIR = Path.home() / ".osap_launcher"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.ini"

def load_config() -> dict:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH), encoding="utf-8")
    raw_url = cfg.get("app", "server_url", fallback="https://server.kntl.cc")
    return {
        "server_url": normalize_url(raw_url),
        "username": cfg.get("app", "username", fallback=""),
        "token": cfg.get("auth", "token", fallback=""),
    }

def save_config(server_url: str, username: str, token: str = ""):
    cfg = configparser.ConfigParser()
    cfg["app"] = {"server_url": normalize_url(server_url), "username": username}
    cfg["auth"] = {"token": token}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)

def api_get(server_url: str, path: str, token: str = "", timeout: int = 12) -> tuple:
    if requests is None:
        raise RuntimeError("Modul requests belum terinstall.")
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    r = requests.get(f"{base}{path}", headers=headers, timeout=timeout)
    return r.json(), r.status_code

def api_post(server_url: str, path: str, data: dict = None, token: str = "", files=None, timeout: int = 15) -> tuple:
    if requests is None:
        raise RuntimeError("Modul requests belum terinstall.")
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    if files:
        r = requests.post(f"{base}{path}", headers=headers, files=files, timeout=40)
    else:
        headers["Content-Type"] = "application/json"
        r = requests.post(f"{base}{path}", headers=headers, json=data, timeout=timeout)
    return r.json(), r.status_code

class OSAPLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sin'X Automation — Client Karyawan")
        self.geometry("760x840")
        self.minsize(700, 750)
        self.configure(bg=BG)

        self._set_app_icon()

        self.cfg = load_config()
        self.token = self.cfg.get("token", "")
        self.current_user = None
        self.user_settings = {}
        self.sse_active = False
        self.log_queue = queue.Queue()

        self._build_ui()
        self._start_log_consumer()
        self._auto_login_if_token()

    def _set_app_icon(self):
        try:
            exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
            bundle_dir = getattr(sys, '_MEIPASS', None)
            candidates = [
                exe_dir / "icon.ico",
                Path(__file__).parent / "icon.ico",
                Path(bundle_dir) / "icon.ico" if bundle_dir else None,
            ]
            for icon_path in candidates:
                if icon_path and icon_path.exists():
                    self.iconbitmap(str(icon_path))
                    break
        except Exception:
            pass

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CARD_BG, pady=10, padx=16)
        hdr.pack(fill="x")

        title_box = tk.Frame(hdr, bg=CARD_BG)
        title_box.pack(side="left")

        tk.Label(title_box, text="SIN'X AUTOMATION", font=("Segoe UI", 15, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        tk.Label(title_box, text="Multi-Platform Cloud Automation • Client Karyawan", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")

        right_box = tk.Frame(hdr, bg=CARD_BG)
        right_box.pack(side="right")

        self.status_dot = tk.Label(right_box, text="●", font=("Segoe UI", 13), bg=CARD_BG, fg=DANGER)
        self.status_dot.pack(side="left", padx=(0, 4))
        self.status_lbl = tk.Label(right_box, text="Belum Login", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT_DIM)
        self.status_lbl.pack(side="left")

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD_BG, foreground=TEXT_DIM,
                        padding=[12, 7], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("TFrame", background=BG)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=8)

        self.tab_dash = ttk.Frame(self.nb)
        self.tab_gudang = ttk.Frame(self.nb)
        self.tab_config = ttk.Frame(self.nb)
        self.tab_logs = ttk.Frame(self.nb)
        self.tab_cookies = ttk.Frame(self.nb)
        self.tab_login = ttk.Frame(self.nb)

        self.nb.add(self.tab_dash, text=" 📊 Dashboard ")
        self.nb.add(self.tab_gudang, text=" 📦 Gudang Konten ")
        self.nb.add(self.tab_config, text=" ⚙️ Config ")
        self.nb.add(self.tab_logs, text=" 📜 Live Logs ")
        self.nb.add(self.tab_cookies, text=" 🍪 Cookies & Browser ")
        self.nb.add(self.tab_login, text=" 🔑 Akun & Login ")

        self._build_dashboard_tab()
        self._build_gudang_tab()
        self._build_config_tab()
        self._build_logs_tab()
        self._build_cookies_tab()
        self._build_login_tab()

    def _build_dashboard_tab(self):
        f = self.tab_dash
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        u_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid")
        u_card.pack(fill="x", pady=(0, 12))
        
        u_inner = tk.Frame(u_card, bg=CARD_BG, padx=14, pady=10)
        u_inner.pack(fill="x")

        self.dash_user_lbl = tk.Label(u_inner, text="Akun: Belum Terhubung", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT)
        self.dash_user_lbl.pack(side="left")

        self.dash_acc_badge = tk.Label(u_inner, text="Account ID: -", font=("Segoe UI", 9), bg="#2d3748", fg=TEXT_DIM, padx=8, pady=2)
        self.dash_acc_badge.pack(side="right")

        stats_frame = tk.Frame(outer, bg=BG)
        stats_frame.pack(fill="x", pady=(0, 14))

        self.stat_total = self._create_stat_card(stats_frame, "Total Video", "0", ACCENT, 0)
        self.stat_ready = self._create_stat_card(stats_frame, "Siap Upload", "0", SUCCESS, 1)
        self.stat_proc = self._create_stat_card(stats_frame, "Diproses", "0", WARNING, 2)
        self.stat_done = self._create_stat_card(stats_frame, "Selesai", "0", ACCENT_CYAN, 3)
        self.stat_failed = self._create_stat_card(stats_frame, "Gagal", "0", DANGER, 4)

        sch_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        sch_card.pack(fill="x", pady=(0, 14))

        tk.Label(sch_card, text="⏰ Status Smart Scheduler & Jam Tayang", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 6))

        self.dash_sch_next = tk.Label(sch_card, text="Jadwal Berikutnya: Memuat...", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_next.pack(anchor="w", pady=2)

        self.dash_sch_slots = tk.Label(sch_card, text="Jam Tayang Aktif: -", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_slots.pack(anchor="w", pady=2)

        self.dash_sch_tz = tk.Label(sch_card, text="Timezone Acuan: -", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_tz.pack(anchor="w", pady=2)

        btn_frame = tk.Frame(outer, bg=BG)
        btn_frame.pack(fill="x", pady=6)

        self.refresh_dash_btn = tk.Button(btn_frame, text="🔄  Refresh Statistik", font=("Segoe UI", 9, "bold"),
                                          bg=ACCENT, fg="white", relief="flat", cursor="hand2", padx=12, pady=7,
                                          command=self.refresh_dashboard_data)
        self.refresh_dash_btn.pack(side="left", padx=(0, 6))

        self.open_dash_web_btn = tk.Button(btn_frame, text="🌐  Buka Web Dashboard", font=("Segoe UI", 9),
                                           bg="#1e293b", fg=TEXT, relief="flat", cursor="hand2", padx=12, pady=7,
                                           command=self.open_dashboard)
        self.open_dash_web_btn.pack(side="left")

    def _create_stat_card(self, parent, title: str, value: str, color: str, col_idx: int):
        parent.columnconfigure(col_idx, weight=1)
        card = tk.Frame(parent, bg=CARD_BG, bd=1, relief="solid", padx=8, pady=10)
        card.grid(row=0, column=col_idx, padx=3, sticky="ew")

        val_lbl = tk.Label(card, text=value, font=("Segoe UI", 16, "bold"), bg=CARD_BG, fg=color)
        val_lbl.pack()
        tk.Label(card, text=title, font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack()
        return val_lbl

    def _build_gudang_tab(self):
        f = self.tab_gudang
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        tk.Label(outer, text="Gudang Konten Video", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Input link video shorts/reels/tiktok (1 URL per baris) ke antrean posting lo:",
                 font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 6))

        self.url_text = scrolledtext.ScrolledText(outer, height=4, font=("Consolas", 9), bg=INPUT_BG, fg=TEXT,
                                                 insertbackground=TEXT, relief="solid", bd=1)
        self.url_text.pack(fill="x", pady=(0, 8))

        btn_box = tk.Frame(outer, bg=BG)
        btn_box.pack(fill="x", pady=(0, 10))

        self.add_urls_btn = tk.Button(btn_box, text="📥  Tambah ke Gudang Konten", font=("Segoe UI", 9, "bold"),
                                      bg=SUCCESS, fg="white", relief="flat", cursor="hand2", pady=6,
                                      command=self.submit_urls)
        self.add_urls_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.refresh_queue_btn = tk.Button(btn_box, text="🔄  Refresh Antrean", font=("Segoe UI", 9),
                                           bg=CARD_BG, fg=TEXT, relief="flat", cursor="hand2", pady=6,
                                           command=self.load_my_videos)
        self.refresh_queue_btn.pack(side="right")

        tk.Label(outer, text="Daftar Status Antrean Video Lo:", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(4, 4))

        q_frame = tk.Frame(outer, bg=INPUT_BG, bd=1, relief="solid")
        q_frame.pack(fill="both", expand=True)

        self.queue_box = scrolledtext.ScrolledText(q_frame, font=("Consolas", 9), bg=INPUT_BG, fg=TEXT,
                                                  state="disabled", relief="flat", bd=4)
        self.queue_box.pack(fill="both", expand=True)

    def _build_config_tab(self):
        f = self.tab_config
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=BG)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(xscrollcommand=None, yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=8)
        scrollbar.pack(side="right", fill="y", pady=8)

        # 1. Smart Schedule
        s1 = tk.LabelFrame(scroll_frame, text=" ⏰ 1. Smart Schedule & Jam Posting ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s1.pack(fill="x", padx=8, pady=(0, 10))

        tk.Label(s1, text="Jam Posting / Prime-Time Slots (pisahkan koma):", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_slots = tk.StringVar(value="12:00, 18:00, 21:00")
        tk.Entry(s1, textvariable=self.sv_slots, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 6))

        p_row = tk.Frame(s1, bg=CARD_BG)
        p_row.pack(fill="x", pady=(0, 6))
        tk.Button(p_row, text="3x (12, 18, 21)", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM, relief="flat",
                  command=lambda: self.sv_slots.set("12:00, 18:00, 21:00")).pack(side="left", padx=(0, 4))
        tk.Button(p_row, text="4x (09, 13, 17, 21)", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM, relief="flat",
                  command=lambda: self.sv_slots.set("09:00, 13:00, 17:00, 21:00")).pack(side="left", padx=4)
        tk.Button(p_row, text="5x (08, 11, 14, 17, 20)", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM, relief="flat",
                  command=lambda: self.sv_slots.set("08:00, 11:00, 14:00, 17:00, 20:00")).pack(side="left", padx=4)

        tk.Label(s1, text="Timezone Acuan:", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_tz = tk.StringVar(value="Asia/Jakarta")
        tz_box = ttk.Combobox(s1, textvariable=self.sv_tz, values=["Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura", "UTC"], state="readonly")
        tz_box.pack(fill="x", pady=(2, 6))

        r_row = tk.Frame(s1, bg=CARD_BG)
        r_row.pack(fill="x")
        r_col1 = tk.Frame(r_row, bg=CARD_BG)
        r_col1.pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Label(r_col1, text="Maks Post/Jam:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_pph = tk.StringVar(value="2")
        tk.Entry(r_col1, textvariable=self.sv_pph, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        r_col2 = tk.Frame(r_row, bg=CARD_BG)
        r_col2.pack(side="left", fill="x", expand=True, padx=(4, 0))
        tk.Label(r_col2, text="Delay Platform (dtk):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_delay = tk.StringVar(value="30")
        tk.Entry(r_col2, textvariable=self.sv_delay, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        # 2. FFmpeg Anti-Hash
        s2 = tk.LabelFrame(scroll_frame, text=" 🛡️ 2. FFmpeg Anti-Hash Filters ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s2.pack(fill="x", padx=8, pady=(0, 10))

        grid2 = tk.Frame(s2, bg=CARD_BG)
        grid2.pack(fill="x")
        grid2.columnconfigure(0, weight=1)
        grid2.columnconfigure(1, weight=1)

        c1 = tk.Frame(grid2, bg=CARD_BG)
        c1.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=2)
        tk.Label(c1, text="Zoom Crop (1.05 = 5%):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_zoom = tk.StringVar(value="1.05")
        tk.Entry(c1, textvariable=self.sv_zoom, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        c2 = tk.Frame(grid2, bg=CARD_BG)
        c2.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=2)
        tk.Label(c2, text="Speed Factor (1.05 = 5%):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_speed = tk.StringVar(value="1.05")
        tk.Entry(c2, textvariable=self.sv_speed, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        c3 = tk.Frame(grid2, bg=CARD_BG)
        c3.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=4)
        tk.Label(c3, text="Noise Amount (1 - 5):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_noise = tk.StringVar(value="3")
        tk.Entry(c3, textvariable=self.sv_noise, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        c4 = tk.Frame(grid2, bg=CARD_BG)
        c4.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=4)
        tk.Label(c4, text="Contrast Multiplier:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_contrast = tk.StringVar(value="1.05")
        tk.Entry(c4, textvariable=self.sv_contrast, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        tk.Label(s2, text="Saturation Multiplier (contoh: 1.08):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 0))
        self.sv_saturation = tk.StringVar(value="1.08")
        tk.Entry(s2, textvariable=self.sv_saturation, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        # 3. Watermark
        s3 = tk.LabelFrame(scroll_frame, text=" 🏷️ 3. Video Watermark (Middle-Left) ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s3.pack(fill="x", padx=8, pady=(0, 10))

        self.sv_wm_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(s3, text="Aktifkan Watermark Otomatis", variable=self.sv_wm_enabled, font=("Segoe UI", 9, "bold"),
                       bg=CARD_BG, fg=TEXT, selectcolor=ACCENT, activebackground=CARD_BG, activeforeground=TEXT).pack(anchor="w")

        tk.Label(s3, text="Teks Watermark (contoh: @channel_lo):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(4, 0))
        self.sv_wm_text = tk.StringVar(value="")
        tk.Entry(s3, textvariable=self.sv_wm_text, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        wm_grid = tk.Frame(s3, bg=CARD_BG)
        wm_grid.pack(fill="x", pady=4)
        wm_grid.columnconfigure(0, weight=1)
        wm_grid.columnconfigure(1, weight=1)
        wm_grid.columnconfigure(2, weight=1)

        wm1 = tk.Frame(wm_grid, bg=CARD_BG)
        wm1.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        tk.Label(wm1, text="Font Size:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_wm_size = tk.StringVar(value="15")
        tk.Entry(wm1, textvariable=self.sv_wm_size, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        wm2 = tk.Frame(wm_grid, bg=CARD_BG)
        wm2.grid(row=0, column=1, sticky="ew", padx=3)
        tk.Label(wm2, text="Opacity (0.1-1.0):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_wm_opacity = tk.StringVar(value="0.3")
        tk.Entry(wm2, textvariable=self.sv_wm_opacity, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        wm3 = tk.Frame(wm_grid, bg=CARD_BG)
        wm3.grid(row=0, column=2, sticky="ew", padx=(3, 0))
        tk.Label(wm3, text="Warna:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_wm_color = tk.StringVar(value="white")
        tk.Entry(wm3, textvariable=self.sv_wm_color, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        tk.Label(s3, text="📍 Posisi: Sisi Kiri-Tengah (Middle-Left) otomatis.", font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 0))

        # 4. Telegram
        s4 = tk.LabelFrame(scroll_frame, text=" 🔔 4. Notifikasi Bot Telegram Pribadi ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s4.pack(fill="x", padx=8, pady=(0, 10))

        self.sv_tg_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(s4, text="Aktifkan Notifikasi Posting ke Telegram", variable=self.sv_tg_enabled,
                       font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT, selectcolor=ACCENT,
                       activebackground=CARD_BG, activeforeground=TEXT).pack(anchor="w")

        tk.Label(s4, text="Bot Token (dari @BotFather):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(4, 0))
        self.sv_tg_token = tk.StringVar(value="")
        tk.Entry(s4, textvariable=self.sv_tg_token, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        tk.Label(s4, text="Chat ID (dari @userinfobot):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(4, 0))
        self.sv_tg_chatid = tk.StringVar(value="")
        tk.Entry(s4, textvariable=self.sv_tg_chatid, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        tk.Button(s4, text="🔔  Test Kirim Notifikasi Telegram", font=("Segoe UI", 8, "bold"), bg="#1e293b", fg=TEXT,
                  relief="flat", cursor="hand2", pady=5, command=self.test_telegram).pack(anchor="w", pady=(6, 0))

        # 5. Proxy
        s5 = tk.LabelFrame(scroll_frame, text=" 🌐 5. Dedicated Proxy Setup (Per-Karyawan) ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s5.pack(fill="x", padx=8, pady=(0, 14))

        tk.Label(s5, text="Proxy URL (HTTP/HTTPS/SOCKS5):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_proxy_url = tk.StringVar(value="")
        tk.Entry(s5, textvariable=self.sv_proxy_url, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT,
                 insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 4))
        tk.Label(s5, text="Contoh: http://user:pass@ip:port atau socks5://ip:port. Kosongkan = Direct Mode.",
                 font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")

        p_test_row = tk.Frame(s5, bg=CARD_BG)
        p_test_row.pack(fill="x", pady=(6, 0))

        self.test_proxy_btn = tk.Button(p_test_row, text="🌐  Test Koneksi Proxy", font=("Segoe UI", 8, "bold"),
                                        bg="#1e293b", fg=TEXT, relief="flat", cursor="hand2", pady=5,
                                        command=self.test_proxy_connection)
        self.test_proxy_btn.pack(side="left", padx=(0, 8))

        self.proxy_status_lbl = tk.Label(p_test_row, text="", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM)
        self.proxy_status_lbl.pack(side="left")

        # Save Button
        save_btn = tk.Button(scroll_frame, text="💾  SIMPAN SEMUA PENGATURAN AKUN SAYA",
                             font=("Segoe UI", 11, "bold"), bg=ACCENT, fg="white",
                             relief="flat", cursor="hand2", pady=10, command=self.save_all_settings)
        save_btn.pack(fill="x", padx=8, pady=(0, 20))

    def _build_logs_tab(self):
        f = self.tab_logs
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        hdr_log = tk.Frame(outer, bg=BG)
        hdr_log.pack(fill="x", pady=(0, 8))

        tk.Label(hdr_log, text="Live Server Logs (SSE Stream)", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(side="left")

        self.auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(hdr_log, text="Auto-scroll", variable=self.auto_scroll_var, font=("Segoe UI", 8),
                       bg=BG, fg=TEXT_DIM, selectcolor=CARD_BG, activebackground=BG, activeforeground=TEXT).pack(side="right", padx=(8, 0))

        tk.Button(hdr_log, text="🧹  Bersihkan", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM, relief="flat",
                  command=self.clear_logs).pack(side="right")

        log_frame = tk.Frame(outer, bg="#0d1117", bd=1, relief="solid")
        log_frame.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(log_frame, font=("Consolas", 9), bg="#0d1117", fg=TEXT,
                                                 insertbackground=TEXT, state="disabled", relief="flat", bd=6, wrap="word")
        self.log_box.pack(fill="both", expand=True)

    def _build_cookies_tab(self):
        f = self.tab_cookies
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="Upload Cookie Akun Sosmed Lo", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Export cookies dari browser lo (Get cookies.txt LOCALLY / Cookie-Editor):", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 10))

        tk.Label(outer, text="Pilih Platform:", font=("Segoe UI", 9, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_platform = tk.StringVar(value="youtube")
        plat_frame = tk.Frame(outer, bg=BG)
        plat_frame.pack(fill="x", pady=(4, 10))
        for val, label in PLATFORMS:
            tk.Radiobutton(plat_frame, text=label, variable=self.sv_platform, value=val, bg=BG, fg=TEXT_DIM, selectcolor=ACCENT, activebackground=BG, activeforeground=TEXT, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))

        tk.Label(outer, text="Target Key (opsional, kosongkan = default):", font=("Segoe UI", 9, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_target = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_target, font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 10))

        tk.Button(outer, text="📂  Pilih & Upload File Cookie (.json / .txt)", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.upload_cookie_file).pack(fill="x", pady=(0, 14))

        ttk.Separator(outer).pack(fill="x", pady=10)

        tk.Label(outer, text="Login Otomatis via Browser Lokal (Edge / Chrome)", font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Buka jendela browser lokal (Edge/Chrome bawaan Windows) untuk login manual & kirim cookies otomatis ke server:", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 8))

        tk.Button(outer, text="🖥️  Buka Browser Lokal & Ekstrak Cookie", font=("Segoe UI", 10, "bold"), bg="#0f3460", fg="white", relief="flat", cursor="hand2", pady=8, command=self.do_local_browser_login).pack(fill="x")

    def _build_login_tab(self):
        f = self.tab_login
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="Server Dedicated OSAP", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        self.sv_url = tk.StringVar(value=self.cfg["server_url"])
        tk.Entry(outer, textvariable=self.sv_url, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(4, 12))

        tk.Label(outer, text="Username Karyawan:", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_user = tk.StringVar(value=self.cfg["username"])
        tk.Entry(outer, textvariable=self.sv_user, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(4, 12))

        tk.Label(outer, text="Password:", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_pass = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_pass, show="*", font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(4, 16))

        self.login_btn = tk.Button(outer, text="🔑  Login ke Server", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.do_login)
        self.login_btn.pack(fill="x", pady=(0, 8))

        self.logout_btn = tk.Button(outer, text="Keluar / Logout", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM, relief="flat", cursor="hand2", pady=6, command=self.do_logout, state="disabled")
        self.logout_btn.pack(fill="x", pady=(0, 14))

        ttk.Separator(outer).pack(fill="x", pady=10)

        tk.Label(outer, text="Ganti Password Akun", font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(anchor="w", pady=(0, 6))
        
        tk.Label(outer, text="Password Saat Ini:", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_cur_pw = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_cur_pw, show="*", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 6))

        tk.Label(outer, text="Password Baru (min 6 karakter):", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_new_pw = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_new_pw, show="*", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 8))

        tk.Button(outer, text="🔒  Ubah Password", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg=TEXT, relief="flat", cursor="hand2", pady=6, command=self.change_password).pack(fill="x")

    def log(self, msg: str, color: str = None):
        self.log_queue.put((msg, color))

    def _start_log_consumer(self):
        def _consume():
            while True:
                try:
                    msg, color = self.log_queue.get(timeout=0.2)
                    self.after(0, lambda m=msg, c=color: self._append_log(m, c))
                except queue.Empty:
                    pass
                except Exception:
                    pass
        threading.Thread(target=_consume, daemon=True).start()

    def _append_log(self, msg: str, color: str = None):
        self.log_box.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        tag = f"t_{ts}_{color or 'n'}"
        self.log_box.insert("end", f"[{ts}] {msg}\n", tag)
        if color:
            self.log_box.tag_configure(tag, foreground=color)
        if self.auto_scroll_var.get():
            self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_logs(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def set_status(self, text: str, ok: bool = False):
        self.status_dot.configure(fg=SUCCESS if ok else DANGER)
        self.status_lbl.configure(fg=SUCCESS if ok else TEXT_DIM, text=text)

    def _set_logged_in(self, user: dict):
        self.current_user = user
        self.logout_btn.configure(state="normal")
        self.login_btn.configure(state="disabled")
        name = user.get("username", "?")
        acc = user.get("account_id", "?")
        admin = " [ADMIN]" if user.get("is_admin") else " [Karyawan]"

        self.dash_user_lbl.configure(text=f"Akun: {name}{admin}")
        self.dash_acc_badge.configure(text=f"Account ID: #{acc}")
        self.set_status(f"Connected: {name}", ok=True)

        self.load_user_settings()
        self.load_my_videos()
        self.refresh_dashboard_data()
        self._start_sse_stream()

    def _set_logged_out(self):
        self.current_user = None
        self.token = ""
        self.logout_btn.configure(state="disabled")
        self.login_btn.configure(state="normal")
        self.dash_user_lbl.configure(text="Akun: Belum Terhubung")
        self.dash_acc_badge.configure(text="Account ID: -")
        self.set_status("Belum Login", ok=False)
        self.sse_active = False

    def do_login(self):
        url = normalize_url(self.sv_url.get().strip())
        user = self.sv_user.get().strip()
        pw = self.sv_pass.get()
        if not url or not user or not pw:
            messagebox.showerror("Error", "Server URL, username, dan password wajib diisi.")
            return

        self.sv_url.set(url)
        self.log(f"Menghubungkan ke server {url} sebagai '{user}'...")
        self.login_btn.configure(state="disabled", text="Memverifikasi...")

        def _do():
            try:
                data, code = api_post(url, "/api/auth/login", {"username": user, "password": pw})
                if code == 200 and data.get("token"):
                    self.token = data["token"]
                    save_config(url, user, self.token)
                    self.after(0, lambda: self._set_logged_in(data))
                    self.after(0, lambda: self.log(f"Login sukses! Selamat datang, {data['username']}.", SUCCESS))
                    self.after(0, lambda: self.nb.select(self.tab_dash))
                else:
                    err = data.get("detail", "Username atau password salah")
                    self.after(0, lambda: self.log(f"Login gagal: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Login Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"Error koneksi: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Koneksi Error", str(e)))
            finally:
                self.after(0, lambda: self.login_btn.configure(state="normal", text="🔑  Login ke Server"))

        threading.Thread(target=_do, daemon=True).start()

    def do_logout(self):
        url = normalize_url(self.sv_url.get().strip())
        if self.token:
            try:
                api_post(url, "/api/auth/logout", token=self.token)
            except Exception:
                pass
        self.token = ""
        save_config(url, self.sv_user.get(), "")
        self._set_logged_out()
        self.log("Logout berhasil.", TEXT_DIM)
        self.nb.select(self.tab_login)

    def _auto_login_if_token(self):
        if not self.token:
            return
        url = normalize_url(self.cfg["server_url"])
        self.log("Memverifikasi sesi tersimpan di server...")
        def _do():
            try:
                data, code = api_get(url, "/api/auth/me", self.token)
                if code == 200:
                    data["token"] = self.token
                    self.after(0, lambda: self._set_logged_in(data))
                    self.after(0, lambda: self.log(f"Sesi aktif: {data['username']}", SUCCESS))
                else:
                    self.token = ""
                    self.after(0, lambda: self.log("Sesi kadaluarsa, silakan login ulang.", TEXT_DIM))
            except Exception:
                self.after(0, lambda: self.log("Server tidak dapat dijangkau saat startup.", DANGER))
        threading.Thread(target=_do, daemon=True).start()

    def change_password(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        cur_p = self.sv_cur_pw.get()
        new_p = self.sv_new_pw.get()
        if not cur_p or not new_p:
            messagebox.showerror("Error", "Password saat ini dan password baru wajib diisi.")
            return
        if len(new_p) < 6:
            messagebox.showerror("Error", "Password baru minimal 6 karakter.")
            return
        url = normalize_url(self.sv_url.get().strip())
        def _do():
            try:
                data, code = api_post(url, "/api/auth/change-password", {"current_password": cur_p, "new_password": new_p}, token=self.token)
                if code == 200:
                    self.after(0, lambda: messagebox.showinfo("Sukses", "Password berhasil diubah! Silakan login ulang."))
                    self.after(0, self.do_logout)
                else:
                    err = data.get("detail", "Gagal mengubah password")
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def open_dashboard(self):
        url = normalize_url(self.sv_url.get().strip())
        if not url:
            return
        full_url = f"{url}/?token={self.token}" if self.token else url
        webbrowser.open(full_url)
        self.log(f"Membuka browser dashboard: {url}", TEXT_DIM)

    def refresh_dashboard_data(self):
        if not self.token:
            return
        url = normalize_url(self.sv_url.get().strip())
        def _do():
            try:
                data, code = api_get(url, "/api/status", self.token)
                if code == 200:
                    stats = data.get("queue_stats", {})
                    sch = data.get("scheduler", {})
                    
                    self.after(0, lambda: self.stat_total.configure(text=str(stats.get("total", 0))))
                    self.after(0, lambda: self.stat_ready.configure(text=str(stats.get("pending", 0))))
                    self.after(0, lambda: self.stat_proc.configure(text=str(stats.get("processing", 0))))
                    self.after(0, lambda: self.stat_done.configure(text=str(stats.get("done", 0))))
                    self.after(0, lambda: self.stat_failed.configure(text=str(stats.get("failed", 0))))

                    next_slot = sch.get("next_slot", "-")
                    rem = sch.get("remaining_seconds", 0)
                    rem_str = f" ({rem // 3600}j {(rem % 3600) // 60}m lagi)" if rem > 0 else ""
                    slots_str = ", ".join(sch.get("slots", []))
                    tz_str = f"{sch.get('timezone', 'Asia/Jakarta')} ({sch.get('timezone_abbr', 'WIB')}) — Jam Server: {sch.get('current_time', '')}"

                    self.after(0, lambda: self.dash_sch_next.configure(text=f"Jadwal Berikutnya: {next_slot}{rem_str}"))
                    self.after(0, lambda: self.dash_sch_slots.configure(text=f"Jam Tayang Aktif: {slots_str}"))
                    self.after(0, lambda: self.dash_sch_tz.configure(text=f"Timezone Acuan: {tz_str}"))
            except Exception as e:
                self.log(f"Gagal memuat statistik dashboard: {e}", TEXT_DIM)
        threading.Thread(target=_do, daemon=True).start()

    def submit_urls(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        raw = self.url_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showerror("Error", "Masukkan minimal 1 link video.")
            return
        url = normalize_url(self.sv_url.get().strip())
        self.log("Menambahkan URL ke Gudang Konten...")
        self.add_urls_btn.configure(state="disabled")
        def _do():
            try:
                data, code = api_post(url, "/api/ingest", {"urls": raw}, token=self.token)
                if code == 200:
                    added = data.get("added", 0)
                    msg = data.get("message", f"{added} video berhasil ditambahkan!")
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Sukses", msg))
                    self.after(0, lambda: self.url_text.delete("1.0", "end"))
                    self.after(0, self.load_my_videos)
                    self.after(0, self.refresh_dashboard_data)
                else:
                    err = data.get("detail", "Gagal input URLs")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.after(0, lambda: self.add_urls_btn.configure(state="normal"))
        threading.Thread(target=_do, daemon=True).start()

    def load_my_videos(self):
        if not self.token:
            return
        url = normalize_url(self.sv_url.get().strip())
        def _do():
            try:
                data, code = api_get(url, "/api/videos?limit=40", token=self.token)
                if code == 200:
                    videos = data.get("videos", [])
                    total = data.get("total", 0)
                    lines = [f"Total Video Lo di Server: {total}\n" + "═" * 55]
                    if not videos:
                        lines.append("Belum ada video di gudang konten lo. Input URL di atas untuk memulai!")
                    else:
                        for v in videos:
                            vid_id = v.get("id", "?")
                            title = v.get("title") or v.get("url", "Tanpa Judul")
                            if len(title) > 42:
                                title = title[:39] + "..."
                            st = (v.get("status") or "PENDING").upper()
                            created = (v.get("created_at") or "")[:16]
                            lines.append(f"#{vid_id:<4} [{st:<10}] {title} ({created})")
                    text_content = "\n".join(lines)
                    self.after(0, lambda: self._update_queue_box(text_content))
            except Exception as e:
                self.log(f"Gagal memuat antrean video: {e}", TEXT_DIM)
        threading.Thread(target=_do, daemon=True).start()

    def _update_queue_box(self, content: str):
        self.queue_box.configure(state="normal")
        self.queue_box.delete("1.0", "end")
        self.queue_box.insert("end", content)
        self.queue_box.configure(state="disabled")

    def load_user_settings(self):
        if not self.token:
            return
        url = normalize_url(self.sv_url.get().strip())
        def _do():
            try:
                data, code = api_get(url, "/api/user/settings", self.token)
                if code == 200 and data.get("settings"):
                    s = data["settings"]
                    self.user_settings = s
                    slots = s.get("schedule_slots") or ["12:00", "18:00", "21:00"]
                    if isinstance(slots, list):
                        slots = ", ".join(slots)
                    self.after(0, lambda: self.sv_slots.set(str(slots)))
                    self.after(0, lambda: self.sv_tz.set(str(s.get("timezone", "Asia/Jakarta"))))
                    self.after(0, lambda: self.sv_pph.set(str(s.get("posts_per_hour", 2))))
                    self.after(0, lambda: self.sv_delay.set(str(s.get("delay_between_platforms_sec", 30))))

                    self.after(0, lambda: self.sv_zoom.set(str(s.get("ffmpeg_zoom", 1.05))))
                    self.after(0, lambda: self.sv_speed.set(str(s.get("ffmpeg_speed", 1.05))))
                    self.after(0, lambda: self.sv_noise.set(str(s.get("ffmpeg_noise", 3))))
                    self.after(0, lambda: self.sv_contrast.set(str(s.get("ffmpeg_contrast", 1.05))))
                    self.after(0, lambda: self.sv_saturation.set(str(s.get("ffmpeg_saturation", 1.08))))

                    self.after(0, lambda: self.sv_wm_enabled.set(bool(s.get("watermark_enabled", 1))))
                    self.after(0, lambda: self.sv_wm_text.set(str(s.get("watermark_text", ""))))
                    self.after(0, lambda: self.sv_wm_size.set(str(s.get("watermark_font_size", 15))))
                    self.after(0, lambda: self.sv_wm_opacity.set(str(s.get("watermark_opacity", 0.3))))
                    self.after(0, lambda: self.sv_wm_color.set(str(s.get("watermark_color", "white"))))

                    self.after(0, lambda: self.sv_tg_enabled.set(bool(s.get("telegram_enabled", 0))))
                    self.after(0, lambda: self.sv_tg_token.set(str(s.get("telegram_bot_token", ""))))
                    self.after(0, lambda: self.sv_tg_chatid.set(str(s.get("telegram_chat_id", ""))))

                    self.after(0, lambda: self.sv_proxy_url.set(str(s.get("proxy_url", ""))))
                    self.after(0, lambda: self.log("Pengaturan akun berhasil dimuat dari server.", SUCCESS))
            except Exception as e:
                self.log(f"Gagal memuat pengaturan akun: {e}", TEXT_DIM)
        threading.Thread(target=_do, daemon=True).start()

    def save_all_settings(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        raw_slots = [s.strip() for s in self.sv_slots.get().split(",") if s.strip()]
        payload = {
            "schedule_slots": raw_slots,
            "timezone": self.sv_tz.get().strip() or "Asia/Jakarta",
            "posts_per_hour": int(self.sv_pph.get() or 2),
            "delay_between_platforms_sec": int(self.sv_delay.get() or 30),
            "ffmpeg_zoom": float(self.sv_zoom.get() or 1.05),
            "ffmpeg_speed": float(self.sv_speed.get() or 1.05),
            "ffmpeg_noise": int(self.sv_noise.get() or 3),
            "ffmpeg_contrast": float(self.sv_contrast.get() or 1.05),
            "ffmpeg_saturation": float(self.sv_saturation.get() or 1.08),
            "watermark_enabled": bool(self.sv_wm_enabled.get()),
            "watermark_text": self.sv_wm_text.get().strip(),
            "watermark_font_size": int(self.sv_wm_size.get() or 15),
            "watermark_opacity": float(self.sv_wm_opacity.get() or 0.3),
            "watermark_color": self.sv_wm_color.get().strip() or "white",
            "telegram_enabled": bool(self.sv_tg_enabled.get()),
            "telegram_bot_token": self.sv_tg_token.get().strip(),
            "telegram_chat_id": self.sv_tg_chatid.get().strip(),
            "proxy_url": self.sv_proxy_url.get().strip(),
        }

        url = normalize_url(self.sv_url.get().strip())
        self.log("Menyimpan semua konfigurasi akun ke server...")
        def _do():
            try:
                data, code = api_post(url, "/api/user/settings", payload, token=self.token)
                if code == 200:
                    self.after(0, lambda: self.log("✓ Konfigurasi akun berhasil disimpan!", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Sukses", "Pengaturan Jadwal, Anti-Hash, Watermark, Telegram, dan Proxy berhasil disimpan ke akun lo!"))
                    self.after(0, self.refresh_dashboard_data)
                else:
                    err = data.get("detail", "Gagal menyimpan")
                    self.after(0, lambda: self.log(f"✗ Gagal: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def test_telegram(self):
        if not self.token:
            messagebox.showerror("Error", "Login terlebih dahulu.")
            return
        token = self.sv_tg_token.get().strip()
        chat_id = self.sv_tg_chatid.get().strip()
        if not token or not chat_id:
            messagebox.showerror("Error", "Bot Token dan Chat ID wajib diisi untuk test!")
            return
        url = normalize_url(self.sv_url.get().strip())
        self.log("Mengirim test notifikasi ke Telegram...")
        def _do():
            try:
                data, code = api_post(url, "/api/user/telegram/test", {"bot_token": token, "chat_id": chat_id}, token=self.token)
                if code == 200:
                    self.after(0, lambda: self.log("✓ Notifikasi Telegram berhasil terkirim!", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil", "Pesan test Telegram berhasil dikirim! Cek aplikasi Telegram lo."))
                else:
                    err = data.get("detail", "Gagal mengirim Telegram")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def test_proxy_connection(self):
        target_proxy = self.sv_proxy_url.get().strip()
        if not target_proxy:
            self.proxy_status_lbl.configure(text="Direct Mode (Tanpa Proxy)", fg=TEXT_DIM)
            messagebox.showinfo("Direct Mode", "Proxy URL kosong. Akun ini berjalan dalam Direct Mode (koneksi langsung).")
            return
        
        self.proxy_status_lbl.configure(text="Menguji koneksi proxy...", fg=WARNING)
        self.test_proxy_btn.configure(state="disabled")
        url = normalize_url(self.sv_url.get().strip())
        
        def _do():
            try:
                data, code = api_post(url, "/api/proxy/check", {"proxy_url": target_proxy}, token=self.token)
                msg = data.get("message", "")
                if data.get("reachable"):
                    self.after(0, lambda: self.proxy_status_lbl.configure(text="✓ ONLINE", fg=SUCCESS))
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Proxy Sukses", msg))
                else:
                    self.after(0, lambda: self.proxy_status_lbl.configure(text="✗ OFFLINE / GAGAL", fg=DANGER))
                    self.after(0, lambda: self.log(f"✗ {msg}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Proxy Gagal", msg))
            except Exception as e:
                self.after(0, lambda: self.proxy_status_lbl.configure(text="✗ Error", fg=DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.after(0, lambda: self.test_proxy_btn.configure(state="normal"))
        threading.Thread(target=_do, daemon=True).start()

    def _start_sse_stream(self):
        if self.sse_active or not self.token:
            return
        self.sse_active = True
        url = normalize_url(self.sv_url.get().strip())
        
        def _stream():
            while self.sse_active and self.token:
                try:
                    headers = {"X-Auth-Token": self.token, "Accept": "text/event-stream"}
                    with requests.get(f"{url}/api/logs/stream", headers=headers, stream=True, timeout=60) as r:
                        if r.status_code != 200:
                            time.sleep(5)
                            continue
                        for line in r.iter_lines(decode_unicode=True):
                            if not self.sse_active:
                                break
                            if line and line.startswith("data:"):
                                raw_json = line[5:].strip()
                                try:
                                    item = json.loads(raw_json)
                                    msg = item.get("message") or item.get("line") or str(item)
                                    lvl = (item.get("level") or "").upper()
                                    col = DANGER if "ERROR" in lvl or "FAIL" in lvl else (WARNING if "WARN" in lvl else None)
                                    self.log(msg, col)
                                except Exception:
                                    self.log(raw_json)
                except Exception:
                    time.sleep(4)
        threading.Thread(target=_stream, daemon=True).start()

    def upload_cookie_file(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        path = filedialog.askopenfilename(
            title="Pilih File Cookies",
            filetypes=[("Cookie Files", "*.json;*.txt"), ("All Files", "*.*")]
        )
        if not path:
            return
        platform = self.sv_platform.get()
        target_key = self.sv_target.get().strip() or platform
        server_url = normalize_url(self.sv_url.get().strip())
        self.log(f"Mengupload cookie untuk target '{target_key}'...")
        def _do():
            try:
                with open(path, "rb") as fh:
                    files = {"file": (Path(path).name, fh, "application/octet-stream")}
                    data, code = api_post(server_url, f"/api/upload-cookies/{target_key}", token=self.token, files=files)
                if code == 200:
                    msg = data.get("message", "Cookies berhasil diupload!")
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nPlatform {target_key} siap digunakan."))
                else:
                    err = data.get("detail", "Upload gagal")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def do_local_browser_login(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login ke server terlebih dahulu.")
            return
        platform = self.sv_platform.get()
        target_key = self.sv_target.get().strip() or platform
        url_map = {
            "youtube": "https://accounts.google.com",
            "instagram": "https://www.instagram.com/accounts/login/",
            "tiktok": "https://www.tiktok.com/login",
            "facebook": "https://www.facebook.com/login",
            "twitter": "https://twitter.com/i/flow/login",
            "twitter_nsfw": "https://twitter.com/i/flow/login",
            "upscrolled": "https://upscrolled.com/login",
            "febspot": "https://www.febspot.com/login",
        }
        login_url = url_map.get(platform, f"https://{platform}.com")
        self.log(f"Membuka browser lokal untuk login {platform}...", TEXT_DIM)

        def _do():
            if not HAS_PLAYWRIGHT:
                self.after(0, lambda: messagebox.showinfo(
                    "Gunakan Upload Cookies",
                    "💡 Solusi Paling Cepat & Aman:\n"
                    "1. Buka browser Chrome/Edge biasa, login ke sosmed Anda.\n"
                    "2. Gunakan ekstensi 'Get cookies.txt LOCALLY' atau 'Cookie-Editor'.\n"
                    "3. Klik tombol 'Pilih & Upload File Cookie' di atas."
                ))
                return
            try:
                import tempfile
                with sync_playwright() as p:
                    browser = None
                    for ch in ("msedge", "chrome", None):
                        try:
                            browser = p.chromium.launch(channel=ch, headless=False, args=["--disable-blink-features=AutomationControlled"]) if ch else p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
                            if browser:
                                break
                        except Exception:
                            continue

                    if not browser:
                        raise RuntimeError("Tidak dapat menemukan browser Microsoft Edge atau Google Chrome.")

                    context = browser.new_context(viewport={"width": 1280, "height": 720})
                    page = context.new_page()
                    page.goto(login_url)
                    self.after(0, lambda: self.log(f"Browser terbuka: {login_url}", SUCCESS))
                    self.after(0, lambda: self.log("Silakan login di browser. Setelah selesai, TUTUP jendela browser.", TEXT_DIM))

                    try:
                        page.wait_for_event("close", timeout=300_000)
                    except Exception:
                        pass
                    cookies = context.cookies()
                    context.close()
                    browser.close()

                if not cookies:
                    self.after(0, lambda: self.log("Tidak ada cookies yang berhasil diekstrak.", DANGER))
                    return

                self.after(0, lambda: self.log(f"✓ {len(cookies)} cookies diekstrak. Mengupload ke server...", SUCCESS))
                server_url = normalize_url(self.sv_url.get().strip())
                tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
                json.dump(cookies, tmp)
                tmp.close()

                with open(tmp.name, "rb") as fh:
                    files = {"file": (f"{target_key}_cookies.json", fh, "application/json")}
                    data, code = api_post(server_url, f"/api/upload-cookies/{target_key}", token=self.token, files=files)
                os.unlink(tmp.name)

                if code == 200:
                    msg = data.get("message", "Cookies berhasil diupload!")
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nPlatform {target_key} siap digunakan!"))
                else:
                    err = data.get("detail", "Upload cookies gagal")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Gagal Membuka Browser", str(e)))
        threading.Thread(target=_do, daemon=True).start()

if __name__ == "__main__":
    app = OSAPLauncher()
    app.mainloop()
