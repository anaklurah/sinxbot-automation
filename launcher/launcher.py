"""
Sin'X Automation — Client Desktop Karyawan
==========================================
Desktop client for Sin'X Automation (OmniShorts Auto-Publisher).
Designed for employees and managers with dedicated cloud integration:
- Modern sleek dark slate theme with responsive layout (fits all laptop & desktop screens)
- Dashboard: Real-time stat cards, scheduler monitor, On-Demand Publish trigger, & Debug Screenshot viewer
- Gudang Konten: Bulk URL ingest, interactive Treeview queue table with status badges, & queue clear tool
- Config Akun: Smart Schedule, FFmpeg Anti-Hash, Middle-Left Watermark, Telegram Notifier, & Dedicated Proxy
- Cookies & Browser: Upload cookie (.txt/.json), Upload full profile archive (.zip), & Local Browser extractor
- Live Logs: Real-time colored SSE log stream directly from server with auto-reconnect
- Account Security: Fast login persistence, logout, and change password
"""

import os
import sys
import json
import time
import queue
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

# ─────────────────────────────────────────────────────────────
# Theme Colors (Modern Slate & Clay Aesthetic)
# ─────────────────────────────────────────────────────────────
BG = "#0b0f19"              # Deep Midnight Slate
CARD_BG = "#151e2e"         # Elevated Slate Card
CARD_BORDER = "#222f44"     # Subtle border
HEADER_BG = "#0f172a"       # Slate 900
INPUT_BG = "#0a0e17"        # Inset dark input
INPUT_BORDER = "#29374d"    # Input outline

ACCENT = "#6366f1"          # Modern Indigo 500
ACCENT_HOVER = "#4f46e5"    # Indigo 600
ACCENT_CYAN = "#06b6d4"     # Cyan 500
ACCENT_PURPLE = "#a855f7"   # Purple 500
SUCCESS = "#10b981"         # Emerald 500
SUCCESS_HOVER = "#059669"   # Emerald 600
WARNING = "#f59e0b"         # Amber 500
DANGER = "#f43f5e"          # Rose 500
DANGER_HOVER = "#e11d48"    # Rose 600
TEXT = "#f8fafc"            # Slate 50
TEXT_MUTED = "#cbd5e1"      # Slate 300
TEXT_DIM = "#94a3b8"        # Slate 400

PLATFORMS = [
    ("youtube", "YouTube (Shorts/Studio)"),
    ("instagram", "Instagram (Reels)"),
    ("tiktok", "TikTok"),
    ("facebook", "Facebook (Reels)"),
    ("twitter", "Twitter/X"),
    ("twitter_nsfw", "Twitter NSFW"),
    ("upscrolled", "Upscrolled"),
    ("febspot", "Febspot"),
]

def normalize_url(url: str) -> str:
    """Safely normalizes server URL by removing double schemes and trailing slashes."""
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

def api_get(server_url: str, path: str, token: str = "", timeout: int = 15) -> tuple:
    if requests is None:
        raise RuntimeError("Modul 'requests' belum terinstall.")
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    r = requests.get(f"{base}{path}", headers=headers, timeout=timeout)
    return r.json(), r.status_code

def api_post(server_url: str, path: str, data: dict = None, token: str = "", files=None, timeout: int = 20) -> tuple:
    if requests is None:
        raise RuntimeError("Modul 'requests' belum terinstall.")
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    if files:
        r = requests.post(f"{base}{path}", headers=headers, files=files, timeout=60)
    else:
        headers["Content-Type"] = "application/json"
        r = requests.post(f"{base}{path}", headers=headers, json=data, timeout=timeout)
    return r.json(), r.status_code


class SinXLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sin'X Automation — Desktop Client")
        self.geometry("860x720")
        self.minsize(800, 600)
        self.configure(bg=BG)

        self._set_app_icon()

        self.cfg = load_config()
        self.token = self.cfg.get("token", "")
        self.current_user = None
        self.user_settings = {}
        self.sse_active = False
        self.log_queue = queue.Queue()

        self._setup_styles()
        self._build_header()
        self._build_notebook()
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

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("default")

        # Notebook tabs
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=CARD_BG,
            foreground=TEXT_DIM,
            padding=[14, 8],
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT), ("active", "#22334f")],
            foreground=[("selected", "white"), ("active", TEXT)],
        )

        # Combobox
        style.configure(
            "TCombobox",
            background=INPUT_BG,
            foreground=TEXT,
            fieldbackground=INPUT_BG,
            darkcolor=INPUT_BORDER,
            lightcolor=INPUT_BORDER,
            arrowcolor=TEXT,
        )

        # Treeview (Table)
        style.configure(
            "Treeview",
            background=INPUT_BG,
            foreground=TEXT,
            fieldbackground=INPUT_BG,
            rowheight=26,
            font=("Segoe UI", 9),
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=CARD_BG,
            foreground=TEXT_MUTED,
            font=("Segoe UI", 9, "bold"),
            padding=[6, 4],
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", "#312e81")],
            foreground=[("selected", "white")],
        )

        # Scrollbar
        style.configure("Vertical.TScrollbar", background=CARD_BG, troughcolor=BG, borderwidth=0, arrowcolor=TEXT_DIM)

    def _build_header(self):
        hdr = tk.Frame(self, bg=HEADER_BG, pady=10, padx=16, bd=0)
        hdr.pack(fill="x")

        # Left branding
        left_box = tk.Frame(hdr, bg=HEADER_BG)
        left_box.pack(side="left")

        brand_lbl = tk.Label(left_box, text="⚡ SIN'X AUTOMATION", font=("Segoe UI", 14, "bold"), bg=HEADER_BG, fg=TEXT)
        brand_lbl.pack(anchor="w")

        sub_lbl = tk.Label(left_box, text="Multi-Platform Cloud Publishing • Client Karyawan", font=("Segoe UI", 8), bg=HEADER_BG, fg=TEXT_DIM)
        sub_lbl.pack(anchor="w")

        # Right status badge pill
        self.right_pill = tk.Frame(hdr, bg=CARD_BG, bd=1, relief="solid", padx=10, pady=4)
        self.right_pill.pack(side="right")

        self.status_dot = tk.Label(self.right_pill, text="●", font=("Segoe UI", 12), bg=CARD_BG, fg=DANGER)
        self.status_dot.pack(side="left", padx=(0, 5))

        self.status_lbl = tk.Label(self.right_pill, text="Offline / Belum Login", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT_DIM)
        self.status_lbl.pack(side="left")

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self.tab_dash = tk.Frame(self.nb, bg=BG)
        self.tab_gudang = tk.Frame(self.nb, bg=BG)
        self.tab_config = tk.Frame(self.nb, bg=BG)
        self.tab_cookies = tk.Frame(self.nb, bg=BG)
        self.tab_logs = tk.Frame(self.nb, bg=BG)
        self.tab_login = tk.Frame(self.nb, bg=BG)

        self.nb.add(self.tab_dash, text="  📊 Dashboard  ")
        self.nb.add(self.tab_gudang, text="  📦 Gudang Konten  ")
        self.nb.add(self.tab_config, text="  ⚙️ Pengaturan  ")
        self.nb.add(self.tab_cookies, text="  🍪 Cookies & Profil  ")
        self.nb.add(self.tab_logs, text="  📜 Live Logs  ")
        self.nb.add(self.tab_login, text="  🔑 Akun & Server  ")

        self._build_dashboard_tab()
        self._build_gudang_tab()
        self._build_config_tab()
        self._build_cookies_tab()
        self._build_logs_tab()
        self._build_login_tab()

    # ─────────────────────────────────────────────────────────────
    # Tab 1: Dashboard
    # ─────────────────────────────────────────────────────────────
    def _build_dashboard_tab(self):
        f = self.tab_dash
        outer = tk.Frame(f, bg=BG, padx=14, pady=10)
        outer.pack(fill="both", expand=True)

        # User Card
        u_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=12, pady=10)
        u_card.pack(fill="x", pady=(0, 10))

        self.dash_user_lbl = tk.Label(u_card, text="Akun: Belum Terhubung", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT)
        self.dash_user_lbl.pack(side="left")

        self.dash_server_lbl = tk.Label(u_card, text=f"Server: {self.cfg['server_url']}", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_server_lbl.pack(side="left", padx=16)

        self.dash_acc_badge = tk.Label(u_card, text="Account ID: -", font=("Segoe UI", 8, "bold"), bg="#1e293b", fg=ACCENT_CYAN, padx=8, pady=3)
        self.dash_acc_badge.pack(side="right")

        # 5 Stat Cards Row
        stats_box = tk.Frame(outer, bg=BG)
        stats_box.pack(fill="x", pady=(0, 10))

        self.stat_total = self._create_stat_card(stats_box, "Total Video", "0", ACCENT, 0)
        self.stat_ready = self._create_stat_card(stats_box, "Siap Post", "0", SUCCESS, 1)
        self.stat_proc = self._create_stat_card(stats_box, "Diproses", "0", WARNING, 2)
        self.stat_done = self._create_stat_card(stats_box, "Selesai", "0", ACCENT_CYAN, 3)
        self.stat_failed = self._create_stat_card(stats_box, "Gagal", "0", DANGER, 4)

        # Scheduler Monitor Card
        sch_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=10)
        sch_card.pack(fill="x", pady=(0, 10))

        tk.Label(sch_card, text="⏰ Status Smart Prime-Time Scheduler", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 4))
        
        self.dash_sch_next = tk.Label(sch_card, text="Jadwal Berikutnya: Memuat status...", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_next.pack(anchor="w", pady=1)

        self.dash_sch_slots = tk.Label(sch_card, text="Jam Tayang Aktif: -", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_slots.pack(anchor="w", pady=1)

        self.dash_sch_tz = tk.Label(sch_card, text="Timezone Acuan: -", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_tz.pack(anchor="w", pady=1)

        # Action Buttons Section
        act_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        act_card.pack(fill="x", pady=(0, 6))

        tk.Label(act_card, text="🚀 Tombol Operasional Cepat", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 8))

        btn_row = tk.Frame(act_card, bg=CARD_BG)
        btn_row.pack(fill="x")

        # 1. On-Demand Publish
        self.btn_publish = tk.Button(
            btn_row, text="🚀  Post Sekarang (On-Demand)", font=("Segoe UI", 9, "bold"),
            bg=ACCENT, fg="white", activebackground=ACCENT_HOVER, activeforeground="white",
            relief="flat", cursor="hand2", padx=12, pady=7, command=self.prompt_publish_now
        )
        self.btn_publish.pack(side="left", padx=(0, 6))

        # 2. Debug Screenshot
        self.btn_screenshot = tk.Button(
            btn_row, text="📸  Cek Screenshot Browser", font=("Segoe UI", 9, "bold"),
            bg="#0f3460", fg="white", activebackground="#16213e", activeforeground="white",
            relief="flat", cursor="hand2", padx=12, pady=7, command=self.prompt_debug_screenshot
        )
        self.btn_screenshot.pack(side="left", padx=(0, 6))

        # 3. Refresh Stats
        self.btn_refresh = tk.Button(
            btn_row, text="🔄  Refresh Data", font=("Segoe UI", 9),
            bg=CARD_BORDER, fg=TEXT, activebackground="#3b4b63", activeforeground=TEXT,
            relief="flat", cursor="hand2", padx=12, pady=7, command=self.refresh_dashboard_data
        )
        self.btn_refresh.pack(side="left", padx=(0, 6))

        # 4. Open Web Dashboard
        self.btn_web = tk.Button(
            btn_row, text="🌐  Buka Web Dashboard", font=("Segoe UI", 9),
            bg=CARD_BORDER, fg=TEXT, activebackground="#3b4b63", activeforeground=TEXT,
            relief="flat", cursor="hand2", padx=12, pady=7, command=self.open_dashboard
        )
        self.btn_web.pack(side="left")

    def _create_stat_card(self, parent, title: str, value: str, color: str, col_idx: int):
        parent.columnconfigure(col_idx, weight=1)
        card = tk.Frame(parent, bg=CARD_BG, bd=1, relief="solid", padx=6, pady=8)
        card.grid(row=0, column=col_idx, padx=3, sticky="ew")

        val_lbl = tk.Label(card, text=value, font=("Segoe UI", 16, "bold"), bg=CARD_BG, fg=color)
        val_lbl.pack()
        tk.Label(card, text=title, font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack()
        return val_lbl

    # ─────────────────────────────────────────────────────────────
    # Tab 2: Gudang Konten
    # ─────────────────────────────────────────────────────────────
    def _build_gudang_tab(self):
        f = self.tab_gudang
        outer = tk.Frame(f, bg=BG, padx=14, pady=10)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="📥 Tambah Stok Video Baru", font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Masukkan link video Shorts / Reels / TikTok (1 URL per baris):", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(1, 4))

        self.url_text = scrolledtext.ScrolledText(outer, height=3, font=("Consolas", 9), bg=INPUT_BG, fg=TEXT,
                                                 insertbackground=TEXT, relief="solid", bd=1)
        self.url_text.pack(fill="x", pady=(0, 6))

        btn_bar = tk.Frame(outer, bg=BG)
        btn_bar.pack(fill="x", pady=(0, 8))

        self.add_urls_btn = tk.Button(
            btn_bar, text="📥  Tambah ke Gudang Konten", font=("Segoe UI", 9, "bold"),
            bg=SUCCESS, fg="white", activebackground=SUCCESS_HOVER, activeforeground="white",
            relief="flat", cursor="hand2", padx=12, pady=6, command=self.submit_urls
        )
        self.add_urls_btn.pack(side="left", padx=(0, 6))

        self.refresh_queue_btn = tk.Button(
            btn_bar, text="🔄  Refresh Tabel", font=("Segoe UI", 9),
            bg=CARD_BG, fg=TEXT, activebackground=CARD_BORDER, activeforeground=TEXT,
            relief="flat", cursor="hand2", padx=12, pady=6, command=self.load_my_videos
        )
        self.refresh_queue_btn.pack(side="left", padx=(0, 6))

        self.clear_queue_btn = tk.Button(
            btn_bar, text="🗑️  Bersihkan Antrean...", font=("Segoe UI", 9),
            bg="#2d1b28", fg=DANGER, activebackground="#3d2235", activeforeground=DANGER,
            relief="flat", cursor="hand2", padx=12, pady=6, command=self.prompt_clear_queue
        )
        self.clear_queue_btn.pack(side="right")

        # Treeview Queue Table
        tk.Label(outer, text="📋 Daftar Antrean Video Akun Lo di Server:", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT).pack(anchor="w", pady=(4, 4))

        tree_frame = tk.Frame(outer, bg=INPUT_BG, bd=1, relief="solid")
        tree_frame.pack(fill="both", expand=True)

        cols = ("id", "status", "title", "date")
        self.queue_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        
        self.queue_tree.heading("id", text="ID")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("title", text="Judul / Link Video")
        self.queue_tree.heading("date", text="Tanggal Input")

        self.queue_tree.column("id", width=55, minwidth=40, anchor="center")
        self.queue_tree.column("status", width=105, minwidth=80, anchor="center")
        self.queue_tree.column("title", width=480, minwidth=250, anchor="w")
        self.queue_tree.column("date", width=140, minwidth=100, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=tree_scroll.set)

        self.queue_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────
    # Tab 3: Pengaturan Akun
    # ─────────────────────────────────────────────────────────────
    def _build_config_tab(self):
        f = self.tab_config
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=BG)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(xscrollcommand=None, yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=8)
        scrollbar.pack(side="right", fill="y", pady=8)

        # 1. Smart Schedule
        s1 = tk.LabelFrame(scroll_frame, text=" ⏰ 1. Smart Schedule & Jam Posting ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s1.pack(fill="x", padx=6, pady=(0, 10))

        tk.Label(s1, text="Jam Posting / Prime-Time Slots (pisahkan dengan koma):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_slots = tk.StringVar(value="12:00, 18:00, 21:00")
        tk.Entry(s1, textvariable=self.sv_slots, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 6))

        p_row = tk.Frame(s1, bg=CARD_BG)
        p_row.pack(fill="x", pady=(0, 6))
        tk.Button(p_row, text="Preset: 3x (12, 18, 21)", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM, relief="flat",
                  command=lambda: self.sv_slots.set("12:00, 18:00, 21:00")).pack(side="left", padx=(0, 4))
        tk.Button(p_row, text="Preset: 4x (09, 13, 17, 21)", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM, relief="flat",
                  command=lambda: self.sv_slots.set("09:00, 13:00, 17:00, 21:00")).pack(side="left", padx=4)
        tk.Button(p_row, text="Preset: 5x (08, 11, 14, 17, 20)", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM, relief="flat",
                  command=lambda: self.sv_slots.set("08:00, 11:00, 14:00, 17:00, 20:00")).pack(side="left", padx=4)

        tk.Label(s1, text="Timezone Acuan:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
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
        tk.Label(r_col2, text="Delay Antar Platform (detik):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_delay = tk.StringVar(value="30")
        tk.Entry(r_col2, textvariable=self.sv_delay, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        # 2. FFmpeg Anti-Hash Filters
        s2 = tk.LabelFrame(scroll_frame, text=" 🛡️ 2. FFmpeg Anti-Hash Filters (Anti-Deteksi Konten Duplikat) ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s2.pack(fill="x", padx=6, pady=(0, 10))

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

        # 3. Watermark Setup
        s3 = tk.LabelFrame(scroll_frame, text=" 🏷️ 3. Video Watermark Otomatis (Sisi Kiri-Tengah) ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s3.pack(fill="x", padx=6, pady=(0, 10))

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
        tk.Label(wm2, text="Opacity (0.1 - 1.0):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_wm_opacity = tk.StringVar(value="0.3")
        tk.Entry(wm2, textvariable=self.sv_wm_opacity, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        wm3 = tk.Frame(wm_grid, bg=CARD_BG)
        wm3.grid(row=0, column=2, sticky="ew", padx=(3, 0))
        tk.Label(wm3, text="Warna:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_wm_color = tk.StringVar(value="white")
        tk.Entry(wm3, textvariable=self.sv_wm_color, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x")

        # 4. Telegram Notification
        s4 = tk.LabelFrame(scroll_frame, text=" 🔔 4. Notifikasi Bot Telegram Pribadi ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s4.pack(fill="x", padx=6, pady=(0, 10))

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

        tk.Button(s4, text="🔔  Test Kirim Notifikasi Telegram", font=("Segoe UI", 8, "bold"), bg=CARD_BORDER, fg=TEXT,
                  activebackground="#3b4b63", activeforeground=TEXT, relief="flat", cursor="hand2", padx=10, pady=5,
                  command=self.test_telegram).pack(anchor="w", pady=(6, 0))

        # 5. Dedicated Proxy Setup
        s5 = tk.LabelFrame(scroll_frame, text=" 🌐 5. Dedicated Proxy Setup (Per-Karyawan) ", font=("Segoe UI", 10, "bold"),
                           bg=CARD_BG, fg=TEXT, bd=1, relief="solid", padx=12, pady=10)
        s5.pack(fill="x", padx=6, pady=(0, 14))

        tk.Label(s5, text="Proxy URL (HTTP/HTTPS/SOCKS5):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_proxy_url = tk.StringVar(value="")
        tk.Entry(s5, textvariable=self.sv_proxy_url, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT,
                 insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 4))
        tk.Label(s5, text="Contoh: http://user:pass@ip:port atau socks5://ip:port. Kosongkan = Direct Mode.",
                 font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")

        p_test_row = tk.Frame(s5, bg=CARD_BG)
        p_test_row.pack(fill="x", pady=(6, 0))

        self.test_proxy_btn = tk.Button(p_test_row, text="🌐  Test Koneksi Proxy", font=("Segoe UI", 8, "bold"),
                                        bg=CARD_BORDER, fg=TEXT, activebackground="#3b4b63", activeforeground=TEXT,
                                        relief="flat", cursor="hand2", padx=10, pady=5, command=self.test_proxy_connection)
        self.test_proxy_btn.pack(side="left", padx=(0, 8))

        self.proxy_status_lbl = tk.Label(p_test_row, text="", font=("Segoe UI", 8, "bold"), bg=CARD_BG, fg=TEXT_DIM)
        self.proxy_status_lbl.pack(side="left")

        # Save Button
        save_btn = tk.Button(scroll_frame, text="💾  SIMPAN SEMUA PENGATURAN AKUN SAYA",
                             font=("Segoe UI", 11, "bold"), bg=ACCENT, fg="white", activebackground=ACCENT_HOVER,
                             relief="flat", cursor="hand2", pady=10, command=self.save_all_settings)
        save_btn.pack(fill="x", padx=6, pady=(0, 20))

    # ─────────────────────────────────────────────────────────────
    # Tab 4: Cookies & Profil
    # ─────────────────────────────────────────────────────────────
    def _build_cookies_tab(self):
        f = self.tab_cookies
        outer = tk.Frame(f, bg=BG, padx=18, pady=14)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="🍪 Kelola Cookies & Sesi Login Sosmed", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Upload file cookie atau sesi browser ke server agar bot dapat mempublikasikan video lo:", font=("Segoe UI", 8), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(1, 10))

        # Platform selector
        sel_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        sel_card.pack(fill="x", pady=(0, 12))

        tk.Label(sel_card, text="Pilih Platform Sasaran:", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_platform_name = tk.StringVar(value="YouTube (Shorts/Studio)")
        self.cb_platform = ttk.Combobox(sel_card, textvariable=self.sv_platform_name, values=[p[1] for p in PLATFORMS], state="readonly", font=("Segoe UI", 9))
        self.cb_platform.pack(fill="x", pady=(4, 8))

        tk.Label(sel_card, text="Target Key (Opsional, kosongkan bila tidak memakai custom card):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_target = tk.StringVar()
        tk.Entry(sel_card, textvariable=self.sv_target, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 4))

        # Upload Methods Card
        up_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        up_card.pack(fill="x", pady=(0, 12))

        tk.Label(up_card, text="Metode 1: Upload File Cookies / Storage State", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        tk.Label(up_card, text="Export cookies dari browser lokal lo memakai ekstensi 'Cookie-Editor' atau 'Get cookies.txt LOCALLY':", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(1, 6))

        tk.Button(up_card, text="📂  Upload File Cookie (.json / .txt)", font=("Segoe UI", 9, "bold"),
                  bg=ACCENT, fg="white", activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=12, pady=7, command=self.upload_cookie_file).pack(fill="x", pady=(0, 8))

        ttk.Separator(up_card).pack(fill="x", pady=8)

        tk.Label(up_card, text="Metode 2: Upload Full Profil Browser (.zip)", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        tk.Label(up_card, text="Upload arsip ZIP folder profil browser yang sudah login (misal youtube.zip):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(1, 6))

        tk.Button(up_card, text="📦  Upload Folder Profil Browser (.zip)", font=("Segoe UI", 9, "bold"),
                  bg="#1e3a5f", fg="white", activebackground="#2a4a75", relief="flat", cursor="hand2",
                  padx=12, pady=7, command=self.upload_profile_zip).pack(fill="x")

        # Local Browser Login
        loc_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        loc_card.pack(fill="x")

        tk.Label(loc_card, text="Metode 3: Login Otomatis via Browser Lokal (Edge / Chrome)", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        tk.Label(loc_card, text="Buka jendela browser Edge/Chrome di PC lokal lo untuk login manual & kirim cookies otomatis ke server:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(1, 6))

        tk.Button(loc_card, text="🖥️  Buka Browser Lokal & Ekstrak Cookie", font=("Segoe UI", 9, "bold"),
                  bg="#0f3460", fg="white", activebackground="#16213e", relief="flat", cursor="hand2",
                  padx=12, pady=7, command=self.do_local_browser_login).pack(fill="x")

    # ─────────────────────────────────────────────────────────────
    # Tab 5: Live Logs
    # ─────────────────────────────────────────────────────────────
    def _build_logs_tab(self):
        f = self.tab_logs
        outer = tk.Frame(f, bg=BG, padx=14, pady=10)
        outer.pack(fill="both", expand=True)

        hdr_log = tk.Frame(outer, bg=BG)
        hdr_log.pack(fill="x", pady=(0, 6))

        tk.Label(hdr_log, text="📜 Live Server Logs (SSE Stream)", font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(side="left")

        self.auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(hdr_log, text="Auto-scroll", variable=self.auto_scroll_var, font=("Segoe UI", 8),
                       bg=BG, fg=TEXT_DIM, selectcolor=CARD_BG, activebackground=BG, activeforeground=TEXT).pack(side="right", padx=(8, 0))

        tk.Button(hdr_log, text="🔄  Hubungkan Ulang", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM,
                  activebackground=CARD_BORDER, activeforeground=TEXT, relief="flat", cursor="hand2",
                  padx=8, pady=3, command=self._start_sse_stream).pack(side="right", padx=(4, 0))

        tk.Button(hdr_log, text="🧹  Bersihkan", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM,
                  activebackground=CARD_BORDER, activeforeground=TEXT, relief="flat", cursor="hand2",
                  padx=8, pady=3, command=self.clear_logs).pack(side="right")

        log_frame = tk.Frame(outer, bg="#080c14", bd=1, relief="solid")
        log_frame.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(log_frame, font=("Consolas", 9), bg="#080c14", fg=TEXT,
                                                 insertbackground=TEXT, state="disabled", relief="flat", bd=6, wrap="word")
        self.log_box.pack(fill="both", expand=True)

    # ─────────────────────────────────────────────────────────────
    # Tab 6: Akun & Server
    # ─────────────────────────────────────────────────────────────
    def _build_login_tab(self):
        f = self.tab_login
        outer = tk.Frame(f, bg=BG, padx=20, pady=14)
        outer.pack(fill="both", expand=True)

        # Server Card
        srv_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        srv_card.pack(fill="x", pady=(0, 12))

        tk.Label(srv_card, text="🌐 URL Server Dedicated Sin'X Automation", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_url = tk.StringVar(value=self.cfg["server_url"])
        tk.Entry(srv_card, textvariable=self.sv_url, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(4, 2))
        tk.Label(srv_card, text="Format: https://server.kntl.cc atau http://ip-vps:8080", font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")

        # Credentials Card
        c_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        c_card.pack(fill="x", pady=(0, 12))

        tk.Label(c_card, text="Username Karyawan:", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_user = tk.StringVar(value=self.cfg["username"])
        tk.Entry(c_card, textvariable=self.sv_user, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 8))

        tk.Label(c_card, text="Password Akun:", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_pass = tk.StringVar()
        tk.Entry(c_card, textvariable=self.sv_pass, show="*", font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(2, 10))

        btn_box = tk.Frame(c_card, bg=CARD_BG)
        btn_box.pack(fill="x")

        self.login_btn = tk.Button(btn_box, text="🔑  Login ke Server", font=("Segoe UI", 9, "bold"), bg=ACCENT, fg="white", activebackground=ACCENT_HOVER, activeforeground="white", relief="flat", cursor="hand2", padx=14, pady=7, command=self.do_login)
        self.login_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.logout_btn = tk.Button(btn_box, text="Keluar / Logout", font=("Segoe UI", 9), bg=CARD_BORDER, fg=TEXT_DIM, activebackground="#3b4b63", activeforeground=TEXT, relief="flat", cursor="hand2", padx=12, pady=7, command=self.do_logout, state="disabled")
        self.logout_btn.pack(side="right")

        # Change Password Card
        pw_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        pw_card.pack(fill="x")

        tk.Label(pw_card, text="🔒 Ganti Password Akun Lo", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 6))
        
        tk.Label(pw_card, text="Password Saat Ini:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_cur_pw = tk.StringVar()
        tk.Entry(pw_card, textvariable=self.sv_cur_pw, show="*", font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x", pady=(1, 6))

        tk.Label(pw_card, text="Password Baru (minimal 6 karakter):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_new_pw = tk.StringVar()
        tk.Entry(pw_card, textvariable=self.sv_new_pw, show="*", font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x", pady=(1, 8))

        tk.Button(pw_card, text="🔒  Simpan Password Baru", font=("Segoe UI", 9, "bold"), bg=CARD_BORDER, fg=TEXT, activebackground="#3b4b63", activeforeground=TEXT, relief="flat", cursor="hand2", pady=6, command=self.change_password).pack(fill="x")

    # ─────────────────────────────────────────────────────────────
    # Logging & Console Feed
    # ─────────────────────────────────────────────────────────────
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
        try:
            self.log_box.configure(state="normal")
            ts = time.strftime("%H:%M:%S")
            tag = f"t_{ts}_{color or 'n'}"
            self.log_box.insert("end", f"[{ts}] {msg}\n", tag)
            if color:
                self.log_box.tag_configure(tag, foreground=color)
            if self.auto_scroll_var.get():
                self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def clear_logs(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ─────────────────────────────────────────────────────────────
    # Status & Auth Session Handlers
    # ─────────────────────────────────────────────────────────────
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
                    self.after(0, lambda: messagebox.showerror("Gagal Login", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"Koneksi gagal: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Koneksi Error", f"Tidak dapat terhubung ke {url}:\n{e}"))
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
        url = normalize_url(self.cfg.get("server_url", ""))
        if not url:
            return
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

    # ─────────────────────────────────────────────────────────────
    # Dashboard & Pipeline Operations
    # ─────────────────────────────────────────────────────────────
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
                    
                    by_st = stats.get("by_status", {})
                    total_val = stats.get("total", 0)
                    ready_val = stats.get("pending") if stats.get("pending") is not None else by_st.get("pending", 0)
                    proc_val = stats.get("processing") if stats.get("processing") is not None else (by_st.get("downloading", 0) + by_st.get("rendering", 0) + by_st.get("uploading", 0))
                    done_val = stats.get("done") if stats.get("done") is not None else (by_st.get("done", 0) + by_st.get("published", 0))
                    failed_val = stats.get("failed") if stats.get("failed") is not None else (by_st.get("failed", 0) + by_st.get("error", 0))

                    self.after(0, lambda: self.stat_total.configure(text=str(total_val)))
                    self.after(0, lambda: self.stat_ready.configure(text=str(ready_val)))
                    self.after(0, lambda: self.stat_proc.configure(text=str(proc_val)))
                    self.after(0, lambda: self.stat_done.configure(text=str(done_val)))
                    self.after(0, lambda: self.stat_failed.configure(text=str(failed_val)))

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

    # ─────────────────────────────────────────────────────────────
    # Gudang Konten Queue Management
    # ─────────────────────────────────────────────────────────────
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
                data, code = api_get(url, "/api/videos?limit=100", token=self.token)
                if code == 200:
                    videos = data.get("videos", [])
                    def _update():
                        for row in self.queue_tree.get_children():
                            self.queue_tree.delete(row)
                        for v in videos:
                            vid_id = f"#{v.get('id', '?')}"
                            st = (v.get("status") or "pending").upper()
                            title = v.get("title") or v.get("url", "-")
                            created = (v.get("created_at") or "")[:16]
                            self.queue_tree.insert("", "end", values=(vid_id, st, title, created))
                    self.after(0, _update)
            except Exception as e:
                self.log(f"Gagal memuat antrean video: {e}", TEXT_DIM)
        threading.Thread(target=_do, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    # Config Akun & Proxy Handlers
    # ─────────────────────────────────────────────────────────────
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
                    self.after(0, lambda: self.log("✓ Semua pengaturan berhasil disimpan ke server!", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Sukses", "Pengaturan akun berhasil disimpan!"))
                    self.after(0, self.refresh_dashboard_data)
                else:
                    err = data.get("detail", "Gagal menyimpan pengaturan")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
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
                is_ok = bool(data.get("reachable") or data.get("success") or data.get("status") == "online")
                if is_ok:
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


    # ─────────────────────────────────────────────────────────────
    # Actions & Handlers
    # ─────────────────────────────────────────────────────────────
    def get_selected_platform_key(self) -> str:
        label = self.sv_platform_name.get()
        for key, name in PLATFORMS:
            if name == label:
                return key
        return "youtube"

    def prompt_publish_now(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login ke server terlebih dahulu.")
            return

        # Modal dialog to choose target
        dlg = tk.Toplevel(self)
        dlg.title("Post Sekarang (On-Demand)")
        dlg.geometry("380x280")
        dlg.minsize(360, 260)
        dlg.configure(bg=CARD_BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="🚀 Publikasikan 1 Video Sekarang", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(dlg, text="Pilih platform tujuan distribusi video lo:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", padx=16, pady=(0, 10))

        choices = [("ALL", "⭐ Semua Platform Aktif Sekaligus")] + PLATFORMS
        sel_var = tk.StringVar(value="youtube")

        opt_frame = tk.Frame(dlg, bg=CARD_BG)
        opt_frame.pack(fill="both", expand=True, padx=16)

        cb = ttk.Combobox(opt_frame, textvariable=sel_var, values=[c[1] for c in choices], state="readonly", font=("Segoe UI", 9))
        cb.set("YouTube (Shorts/Studio)")
        cb.pack(fill="x", pady=6)

        msg_lbl = tk.Label(opt_frame, text="Proses download JIT, render anti-hash & watermark akan langsung berjalan!", font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=ACCENT_CYAN, wraplength=340, justify="left")
        msg_lbl.pack(fill="x", pady=6)

        btn_box = tk.Frame(dlg, bg=CARD_BG, padx=16, pady=12)
        btn_box.pack(fill="x")

        def _do_pub():
            chosen_label = cb.get()
            target_key = "ALL"
            for k, n in choices:
                if n == chosen_label:
                    target_key = k
                    break

            dlg.destroy()
            self._trigger_publish(target_key)

        tk.Button(btn_box, text="Mulai Posting Sekarang", font=("Segoe UI", 9, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", padx=14, pady=6, command=_do_pub).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(btn_box, text="Batal", font=("Segoe UI", 9), bg=CARD_BORDER, fg=TEXT_DIM, relief="flat", cursor="hand2", padx=10, pady=6, command=dlg.destroy).pack(side="right")

    def _trigger_publish(self, target_key: str):
        url = normalize_url(self.sv_url.get().strip())
        self.nb.select(self.tab_logs)

        def _worker():
            try:
                if target_key == "ALL":
                    self.log("🚀 Memulai publikasi On-Demand ke SEMUA target platform aktif...", ACCENT_CYAN)
                    data, code = api_post(url, "/api/pipeline/publish-all", token=self.token)
                else:
                    self.log(f"🚀 Memulai publikasi On-Demand untuk platform '{target_key}'...", ACCENT_CYAN)
                    data, code = api_post(url, f"/api/publish/{target_key}", token=self.token)

                if code == 200:
                    msg = data.get("message", "Publikasi dimulai!")
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, self.refresh_dashboard_data)
                else:
                    err = data.get("detail", "Gagal memicu publikasi")
                    self.after(0, lambda: self.log(f"✗ Gagal: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def prompt_debug_screenshot(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return

        # Modal to pick platform screenshot
        dlg = tk.Toplevel(self)
        dlg.title("Cek Screenshot Debug")
        dlg.geometry("360x220")
        dlg.minsize(340, 200)
        dlg.configure(bg=CARD_BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="📸 Lihat Screenshot Browser Headless", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(dlg, text="Pilih platform untuk melihat tangkapan layar browser terakhir:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", padx=16, pady=(0, 10))

        cb = ttk.Combobox(dlg, values=[p[1] for p in PLATFORMS], state="readonly", font=("Segoe UI", 9))
        cb.set("YouTube (Shorts/Studio)")
        cb.pack(fill="x", padx=16, pady=6)

        btn_box = tk.Frame(dlg, bg=CARD_BG, padx=16, pady=12)
        btn_box.pack(fill="x")

        def _open():
            chosen_label = cb.get()
            target_key = "youtube"
            for k, n in PLATFORMS:
                if n == chosen_label:
                    target_key = k
                    break
            dlg.destroy()
            url = normalize_url(self.sv_url.get().strip())
            full_url = f"{url}/api/debug/screenshot/{target_key}?token={self.token}&t={int(time.time()*1000)}"
            webbrowser.open(full_url)
            self.log(f"Membuka screenshot debug {target_key} di browser...", TEXT_DIM)

        tk.Button(btn_box, text="Buka Screenshot di Browser", font=("Segoe UI", 9, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", padx=12, pady=6, command=_open).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(btn_box, text="Tutup", font=("Segoe UI", 9), bg=CARD_BORDER, fg=TEXT_DIM, relief="flat", cursor="hand2", padx=10, pady=6, command=dlg.destroy).pack(side="right")

    def prompt_clear_queue(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return

        dlg = tk.Toplevel(self)
        dlg.title("Bersihkan Antrean Konten")
        dlg.geometry("380x240")
        dlg.minsize(360, 220)
        dlg.configure(bg=CARD_BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="🗑️ Bersihkan Antrean Gudang Konten", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=DANGER).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(dlg, text="Pilih cakupan pembersihan video lo di server:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", padx=16, pady=(0, 10))

        scopes = [
            ("pending", "1. Hapus Video Pending (Belum diproses saja)"),
            ("failed", "2. Hapus Video Gagal (Yang statusnya error)"),
            ("all", "⚠️ 3. Reset Total (Hapus semua antrean & riwayat)"),
        ]
        sel_scope = tk.StringVar(value="pending")

        for val, desc in scopes:
            tk.Radiobutton(dlg, text=desc, variable=sel_scope, value=val, font=("Segoe UI", 8),
                           bg=CARD_BG, fg=TEXT, selectcolor=ACCENT, activebackground=CARD_BG, activeforeground=TEXT).pack(anchor="w", padx=20, pady=2)

        btn_box = tk.Frame(dlg, bg=CARD_BG, padx=16, pady=12)
        btn_box.pack(fill="x")

        def _do_clear():
            scope = sel_scope.get()
            dlg.destroy()
            url = normalize_url(self.sv_url.get().strip())
            self.log(f"Membersihkan antrean video ({scope})...")
            def _worker():
                try:
                    data, code = api_post(url, "/api/queue/clear", {"scope": scope}, token=self.token)
                    if code == 200:
                        msg = data.get("message", "Antrean berhasil dibersihkan!")
                        self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                        self.after(0, lambda: messagebox.showinfo("Berhasil", msg))
                        self.after(0, self.load_my_videos)
                        self.after(0, self.refresh_dashboard_data)
                    else:
                        err = data.get("detail", "Gagal membersihkan antrean")
                        self.after(0, lambda: self.log(f"✗ Gagal: {err}", DANGER))
                        self.after(0, lambda: messagebox.showerror("Gagal", err))
                except Exception as e:
                    self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", str(e)))
            threading.Thread(target=_worker, daemon=True).start()

        tk.Button(btn_box, text="Bersihkan Sekarang", font=("Segoe UI", 9, "bold"), bg=DANGER, fg="white", relief="flat", cursor="hand2", padx=12, pady=6, command=_do_clear).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(btn_box, text="Batal", font=("Segoe UI", 9), bg=CARD_BORDER, fg=TEXT_DIM, relief="flat", cursor="hand2", padx=10, pady=6, command=dlg.destroy).pack(side="right")

    def upload_profile_zip(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        path = filedialog.askopenfilename(
            title="Pilih File Arsip Profil Browser (.zip)",
            filetypes=[("ZIP Archive", "*.zip"), ("All Files", "*.*")]
        )
        if not path:
            return
        target_key = self.sv_target.get().strip() or self.get_selected_platform_key()
        server_url = normalize_url(self.sv_url.get().strip())
        self.log(f"Mengunggah arsip profil '{target_key}' ({Path(path).name})...")
        def _do():
            try:
                with open(path, "rb") as fh:
                    files = {"file": (Path(path).name, fh, "application/zip")}
                    data, code = api_post(server_url, f"/api/upload-profile/{target_key}", token=self.token, files=files)
                if code == 200:
                    msg = data.get("message", "Profil berhasil diunggah!")
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nSesi login browser '{target_key}' aktif di server."))
                else:
                    err = data.get("detail", "Gagal upload profil zip")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

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
        platform = self.get_selected_platform_key()
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
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nPlatform '{target_key}' siap digunakan."))
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
        platform = self.get_selected_platform_key()
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
                    "Gunakan Upload Cookies / Profil ZIP",
                    "💡 Solusi Paling Cepat & Aman:\n"
                    "1. Buka browser Chrome/Edge biasa, login ke sosmed Anda.\n"
                    "2. Gunakan ekstensi 'Cookie-Editor' atau 'Get cookies.txt LOCALLY'.\n"
                    "3. Klik tombol 'Upload File Cookie' atau 'Upload Profil Browser (.zip)' di atas."
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
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nPlatform '{target_key}' siap digunakan!"))
                else:
                    err = data.get("detail", "Upload cookies gagal")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Gagal Membuka Browser", str(e)))
        threading.Thread(target=_do, daemon=True).start()


if __name__ == "__main__":
    app = SinXLauncher()
    app.mainloop()