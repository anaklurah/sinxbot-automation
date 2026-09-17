"""
Sin'X Automation — Client Desktop Karyawan
==========================================
Desktop client for Sin'X Automation (OmniShorts Auto-Publisher).
Tabs: Dashboard, Cookies & Profil, Live Logs, Akun & Server.
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

APP_VERSION = "1.3.0"

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
    raw_url = cfg.get("app", "server_url", fallback="https://auto.kntl.cc")
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
        self.geometry("860x680")
        self.minsize(800, 560)
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
        self.after(1500, lambda: self.check_for_updates(manual=False))

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

        # Scrollbar
        style.configure("Vertical.TScrollbar", background=CARD_BG, troughcolor=BG, borderwidth=0, arrowcolor=TEXT_DIM)

    def _build_header(self):
        hdr = tk.Frame(self, bg=HEADER_BG, pady=10, padx=16, bd=0)
        hdr.pack(fill="x")

        # Left branding
        left_box = tk.Frame(hdr, bg=HEADER_BG)
        left_box.pack(side="left")

        tk.Label(left_box, text="\u26a1 SIN'X AUTOMATION", font=("Segoe UI", 14, "bold"), bg=HEADER_BG, fg=TEXT).pack(anchor="w")
        tk.Label(left_box, text=f"Multi-Platform Cloud Publishing \u2022 Client Karyawan v{APP_VERSION}", font=("Segoe UI", 8), bg=HEADER_BG, fg=TEXT_DIM).pack(anchor="w")

        # Right status badge pill
        self.right_pill = tk.Frame(hdr, bg=CARD_BG, bd=1, relief="solid", padx=10, pady=4)
        self.right_pill.pack(side="right")

        self.status_dot = tk.Label(self.right_pill, text="\u25cf", font=("Segoe UI", 12), bg=CARD_BG, fg=DANGER)
        self.status_dot.pack(side="left", padx=(0, 5))

        self.status_lbl = tk.Label(self.right_pill, text="Offline / Belum Login", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT_DIM)
        self.status_lbl.pack(side="left")

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self.tab_dash = tk.Frame(self.nb, bg=BG)
        self.tab_cookies = tk.Frame(self.nb, bg=BG)
        self.tab_logs = tk.Frame(self.nb, bg=BG)
        self.tab_login = tk.Frame(self.nb, bg=BG)

        self.nb.add(self.tab_dash,    text="  \U0001f4ca Dashboard  ")
        self.nb.add(self.tab_cookies, text="  \U0001f36a Cookies & Profil  ")
        self.nb.add(self.tab_logs,    text="  \U0001f4dc Live Logs  ")
        self.nb.add(self.tab_login,   text="  \U0001f511 Akun & Server  ")

        self._build_dashboard_tab()
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

        self.stat_total  = self._create_stat_card(stats_box, "Total Video", "0", ACCENT, 0)
        self.stat_ready  = self._create_stat_card(stats_box, "Siap Post", "0", SUCCESS, 1)
        self.stat_proc   = self._create_stat_card(stats_box, "Diproses", "0", WARNING, 2)
        self.stat_done   = self._create_stat_card(stats_box, "Selesai", "0", ACCENT_CYAN, 3)
        self.stat_failed = self._create_stat_card(stats_box, "Gagal", "0", DANGER, 4)

        # Scheduler Monitor Card
        sch_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=10)
        sch_card.pack(fill="x", pady=(0, 10))

        tk.Label(sch_card, text="\u23f0 Status Smart Prime-Time Scheduler", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 4))

        self.dash_sch_next = tk.Label(sch_card, text="Jadwal Berikutnya: Memuat status...", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_next.pack(anchor="w", pady=1)

        self.dash_sch_slots = tk.Label(sch_card, text="Jam Tayang Aktif: -", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_slots.pack(anchor="w", pady=1)

        self.dash_sch_tz = tk.Label(sch_card, text="Timezone Acuan: -", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_tz.pack(anchor="w", pady=1)

        # Action Buttons Section
        act_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        act_card.pack(fill="x", pady=(0, 6))

        tk.Label(act_card, text="\U0001f680 Tombol Operasional Cepat", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 8))

        btn_row = tk.Frame(act_card, bg=CARD_BG)
        btn_row.pack(fill="x")

        # 1. On-Demand Publish
        self.btn_publish = tk.Button(
            btn_row, text="\U0001f680  Post Sekarang (On-Demand)", font=("Segoe UI", 9, "bold"),
            bg=ACCENT, fg="white", activebackground=ACCENT_HOVER, activeforeground="white",
            relief="flat", cursor="hand2", padx=12, pady=7, command=self.prompt_publish_now
        )
        self.btn_publish.pack(side="left", padx=(0, 6))

        # 2. Debug Screenshot
        self.btn_screenshot = tk.Button(
            btn_row, text="\U0001f4f8  Cek Screenshot Browser", font=("Segoe UI", 9, "bold"),
            bg="#0f3460", fg="white", activebackground="#16213e", activeforeground="white",
            relief="flat", cursor="hand2", padx=12, pady=7, command=self.prompt_debug_screenshot
        )
        self.btn_screenshot.pack(side="left", padx=(0, 6))

        # 3. Refresh Stats
        self.btn_refresh = tk.Button(
            btn_row, text="\U0001f504  Refresh Data", font=("Segoe UI", 9),
            bg=CARD_BORDER, fg=TEXT, activebackground="#3b4b63", activeforeground=TEXT,
            relief="flat", cursor="hand2", padx=12, pady=7, command=self.refresh_dashboard_data
        )
        self.btn_refresh.pack(side="left", padx=(0, 6))

        # 4. Open Web Dashboard
        self.btn_web = tk.Button(
            btn_row, text="\U0001f310  Buka Web Dashboard", font=("Segoe UI", 9),
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
    # Tab 2: Cookies & Profil
    # ─────────────────────────────────────────────────────────────
    def _build_cookies_tab(self):
        f = self.tab_cookies
        outer = tk.Frame(f, bg=BG, padx=18, pady=14)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="\U0001f36a Kelola Cookies & Sesi Login Sosmed", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
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

        tk.Button(up_card, text="\U0001f4c2  Upload File Cookie (.json / .txt)", font=("Segoe UI", 9, "bold"),
                  bg=ACCENT, fg="white", activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=12, pady=7, command=self.upload_cookie_file).pack(fill="x", pady=(0, 8))

        ttk.Separator(up_card).pack(fill="x", pady=8)

        tk.Label(up_card, text="Metode 2: Upload Full Profil Browser (.zip)", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        tk.Label(up_card, text="Upload arsip ZIP folder profil browser yang sudah login (misal youtube.zip):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(1, 6))

        tk.Button(up_card, text="\U0001f4e6  Upload Folder Profil Browser (.zip)", font=("Segoe UI", 9, "bold"),
                  bg="#1e3a5f", fg="white", activebackground="#2a4a75", relief="flat", cursor="hand2",
                  padx=12, pady=7, command=self.upload_profile_zip).pack(fill="x")

        # Local Browser Login
        loc_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        loc_card.pack(fill="x")

        tk.Label(loc_card, text="Metode 3: Login Otomatis via Browser Lokal (Edge / Chrome)", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        tk.Label(loc_card, text="Buka jendela browser Edge/Chrome di PC lokal lo untuk login manual & kirim cookies otomatis ke server:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(1, 6))

        tk.Button(loc_card, text="\U0001f5a5\ufe0f  Buka Browser Lokal & Ekstrak Cookie", font=("Segoe UI", 9, "bold"),
                  bg="#0f3460", fg="white", activebackground="#16213e", relief="flat", cursor="hand2",
                  padx=12, pady=7, command=self.do_local_browser_login).pack(fill="x")

    # ─────────────────────────────────────────────────────────────
    # Tab 3: Live Logs
    # ─────────────────────────────────────────────────────────────
    def _build_logs_tab(self):
        f = self.tab_logs
        outer = tk.Frame(f, bg=BG, padx=14, pady=10)
        outer.pack(fill="both", expand=True)

        hdr_log = tk.Frame(outer, bg=BG)
        hdr_log.pack(fill="x", pady=(0, 6))

        tk.Label(hdr_log, text="\U0001f4dc Live Server Logs (SSE Stream)", font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(side="left")

        self.auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(hdr_log, text="Auto-scroll", variable=self.auto_scroll_var, font=("Segoe UI", 8),
                       bg=BG, fg=TEXT_DIM, selectcolor=CARD_BG, activebackground=BG, activeforeground=TEXT).pack(side="right", padx=(8, 0))

        tk.Button(hdr_log, text="\U0001f504  Hubungkan Ulang", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM,
                  activebackground=CARD_BORDER, activeforeground=TEXT, relief="flat", cursor="hand2",
                  padx=8, pady=3, command=self._start_sse_stream).pack(side="right", padx=(4, 0))

        tk.Button(hdr_log, text="\U0001f9f9  Bersihkan", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM,
                  activebackground=CARD_BORDER, activeforeground=TEXT, relief="flat", cursor="hand2",
                  padx=8, pady=3, command=self.clear_logs).pack(side="right")

        log_frame = tk.Frame(outer, bg="#080c14", bd=1, relief="solid")
        log_frame.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(log_frame, font=("Consolas", 9), bg="#080c14", fg=TEXT,
                                                 insertbackground=TEXT, state="disabled", relief="flat", bd=6, wrap="word")
        self.log_box.pack(fill="both", expand=True)

    # ─────────────────────────────────────────────────────────────
    # Tab 4: Akun & Server
    # ─────────────────────────────────────────────────────────────
    def _build_login_tab(self):
        f = self.tab_login
        outer = tk.Frame(f, bg=BG, padx=20, pady=14)
        outer.pack(fill="both", expand=True)

        # Server Card
        srv_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        srv_card.pack(fill="x", pady=(0, 12))

        tk.Label(srv_card, text="\U0001f310 URL Server Dedicated Sin'X Automation", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_url = tk.StringVar(value=self.cfg["server_url"])
        tk.Entry(srv_card, textvariable=self.sv_url, font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="solid", bd=1).pack(fill="x", pady=(4, 2))
        tk.Label(srv_card, text="Format: https://auto.kntl.cc atau http://ip-vps:8080", font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")

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

        self.login_btn = tk.Button(btn_box, text="\U0001f511  Login ke Server", font=("Segoe UI", 9, "bold"), bg=ACCENT, fg="white", activebackground=ACCENT_HOVER, activeforeground="white", relief="flat", cursor="hand2", padx=14, pady=7, command=self.do_login)
        self.login_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.logout_btn = tk.Button(btn_box, text="Keluar / Logout", font=("Segoe UI", 9), bg=CARD_BORDER, fg=TEXT_DIM, activebackground="#3b4b63", activeforeground=TEXT, relief="flat", cursor="hand2", padx=12, pady=7, command=self.do_logout, state="disabled")
        self.logout_btn.pack(side="right")

        # Change Password Card
        pw_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        pw_card.pack(fill="x")

        tk.Label(pw_card, text="\U0001f512 Ganti Password Akun Lo", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 6))

        tk.Label(pw_card, text="Password Saat Ini:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_cur_pw = tk.StringVar()
        tk.Entry(pw_card, textvariable=self.sv_cur_pw, show="*", font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x", pady=(1, 6))

        tk.Label(pw_card, text="Password Baru (minimal 6 karakter):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_new_pw = tk.StringVar()
        tk.Entry(pw_card, textvariable=self.sv_new_pw, show="*", font=("Segoe UI", 9), bg=INPUT_BG, fg=TEXT, relief="solid", bd=1).pack(fill="x", pady=(1, 8))

        tk.Button(pw_card, text="🔒  Simpan Password Baru", font=("Segoe UI", 9, "bold"), bg=CARD_BORDER, fg=TEXT, activebackground="#3b4b63", activeforeground=TEXT, relief="flat", cursor="hand2", pady=6, command=self.change_password).pack(fill="x")

        # Update & App Info Card
        upd_card = tk.Frame(outer, bg=CARD_BG, bd=1, relief="solid", padx=14, pady=12)
        upd_card.pack(fill="x", pady=(10, 0))

        tk.Label(upd_card, text=f"🚀 Versi Aplikasi & Pembaruan (v{APP_VERSION})", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 4))
        tk.Label(upd_card, text="Client Karyawan Sin'X Automation • Auto-Update Terintegrasi", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 8))

        upd_btn_box = tk.Frame(upd_card, bg=CARD_BG)
        upd_btn_box.pack(fill="x")

        tk.Button(upd_btn_box, text="🔄  Periksa Update Server", font=("Segoe UI", 9, "bold"), bg=ACCENT, fg="white", activebackground=ACCENT_HOVER, activeforeground="white", relief="flat", cursor="hand2", padx=12, pady=6, command=lambda: self.check_for_updates(manual=True)).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(upd_btn_box, text="⬇️  Unduh Exe Terbaru", font=("Segoe UI", 9), bg=CARD_BORDER, fg=TEXT_DIM, activebackground="#3b4b63", activeforeground=TEXT, relief="flat", cursor="hand2", padx=12, pady=6, command=self.download_latest_exe).pack(side="right")

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
                self.after(0, lambda: self.login_btn.configure(state="normal", text="\U0001f511  Login ke Server"))

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
                    total_val  = stats.get("total", 0)
                    ready_val  = stats.get("pending")  if stats.get("pending")  is not None else by_st.get("pending", 0)
                    proc_val   = stats.get("processing") if stats.get("processing") is not None else (by_st.get("downloading", 0) + by_st.get("rendering", 0) + by_st.get("uploading", 0))
                    done_val   = stats.get("done")    if stats.get("done")    is not None else (by_st.get("done", 0) + by_st.get("published", 0))
                    failed_val = stats.get("failed")  if stats.get("failed")  is not None else (by_st.get("failed", 0) + by_st.get("error", 0))

                    self.after(0, lambda: self.stat_total.configure(text=str(total_val)))
                    self.after(0, lambda: self.stat_ready.configure(text=str(ready_val)))
                    self.after(0, lambda: self.stat_proc.configure(text=str(proc_val)))
                    self.after(0, lambda: self.stat_done.configure(text=str(done_val)))
                    self.after(0, lambda: self.stat_failed.configure(text=str(failed_val)))

                    next_slot = sch.get("next_slot", "-")
                    rem = sch.get("remaining_seconds", 0)
                    rem_str = f" ({rem // 3600}j {(rem % 3600) // 60}m lagi)" if rem > 0 else ""
                    slots_str = ", ".join(sch.get("slots", []))
                    tz_str = f"{sch.get('timezone', 'Asia/Jakarta')} ({sch.get('timezone_abbr', 'WIB')}) \u2014 Jam Server: {sch.get('current_time', '')}"

                    self.after(0, lambda: self.dash_sch_next.configure(text=f"Jadwal Berikutnya: {next_slot}{rem_str}"))
                    self.after(0, lambda: self.dash_sch_slots.configure(text=f"Jam Tayang Aktif: {slots_str}"))
                    self.after(0, lambda: self.dash_sch_tz.configure(text=f"Timezone Acuan: {tz_str}"))
            except Exception as e:
                self.log(f"Gagal memuat statistik dashboard: {e}", TEXT_DIM)
        threading.Thread(target=_do, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    # On-Demand Publish & Debug Screenshot
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

        dlg = tk.Toplevel(self)
        dlg.title("Post Sekarang (On-Demand)")
        dlg.geometry("380x280")
        dlg.minsize(360, 260)
        dlg.configure(bg=CARD_BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="\U0001f680 Publikasikan 1 Video Sekarang", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(dlg, text="Pilih platform tujuan distribusi video lo:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", padx=16, pady=(0, 10))

        choices = [("ALL", "\u2b50 Semua Platform Aktif Sekaligus")] + PLATFORMS
        sel_var = tk.StringVar(value="youtube")

        opt_frame = tk.Frame(dlg, bg=CARD_BG)
        opt_frame.pack(fill="both", expand=True, padx=16)

        cb = ttk.Combobox(opt_frame, textvariable=sel_var, values=[c[1] for c in choices], state="readonly", font=("Segoe UI", 9))
        cb.set("YouTube (Shorts/Studio)")
        cb.pack(fill="x", pady=6)

        tk.Label(opt_frame, text="Proses download JIT, render anti-hash & watermark akan langsung berjalan!", font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=ACCENT_CYAN, wraplength=340, justify="left").pack(fill="x", pady=6)

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
                    self.log("\U0001f680 Memulai publikasi On-Demand ke SEMUA target platform aktif...", ACCENT_CYAN)
                    data, code = api_post(url, "/api/pipeline/publish-all", token=self.token)
                else:
                    self.log(f"\U0001f680 Memulai publikasi On-Demand untuk platform '{target_key}'...", ACCENT_CYAN)
                    data, code = api_post(url, f"/api/publish/{target_key}", token=self.token)

                if code == 200:
                    msg = data.get("message", "Publikasi dimulai!")
                    self.after(0, lambda: self.log(f"\u2713 {msg}", SUCCESS))
                    self.after(0, self.refresh_dashboard_data)
                else:
                    err = data.get("detail", "Gagal memicu publikasi")
                    self.after(0, lambda: self.log(f"\u2717 Gagal: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"\u2717 Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def prompt_debug_screenshot(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return

        dlg = tk.Toplevel(self)
        dlg.title("Cek Screenshot Debug")
        dlg.geometry("360x220")
        dlg.minsize(340, 200)
        dlg.configure(bg=CARD_BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="\U0001f4f8 Lihat Screenshot Browser Headless", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", padx=16, pady=(16, 4))
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

    # ─────────────────────────────────────────────────────────────
    # Cookies & Profile Upload
    # ─────────────────────────────────────────────────────────────
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
                    self.after(0, lambda: self.log(f"\u2713 {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nSesi login browser '{target_key}' aktif di server."))
                else:
                    err = data.get("detail", "Gagal upload profil zip")
                    self.after(0, lambda: self.log(f"\u2717 {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"\u2717 Error: {e}", DANGER))
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
                    self.after(0, lambda: self.log(f"\u2713 {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nPlatform '{target_key}' siap digunakan."))
                else:
                    err = data.get("detail", "Upload gagal")
                    self.after(0, lambda: self.log(f"\u2717 {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"\u2717 Error: {e}", DANGER))
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
                    "\U0001f4a1 Solusi Paling Cepat & Aman:\n"
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

                self.after(0, lambda: self.log(f"\u2713 {len(cookies)} cookies diekstrak. Mengupload ke server...", SUCCESS))
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
                    self.after(0, lambda: self.log(f"\u2713 {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", f"{msg}\nPlatform '{target_key}' siap digunakan!"))
                else:
                    err = data.get("detail", "Upload cookies gagal")
                    self.after(0, lambda: self.log(f"\u2717 {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"\u2717 Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Gagal Membuka Browser", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    # SSE Live Log Stream
    # ─────────────────────────────────────────────────────────────
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
    # Auto-Update & Client Distribution
    # ─────────────────────────────────────────────────────────────
    def check_for_updates(self, manual: bool = False):
        url = normalize_url(self.sv_url.get().strip())
        if not url:
            if manual:
                messagebox.showwarning("Update", "Isi Server URL terlebih dahulu.")
            return

        def _check():
            try:
                data, code = api_get(url, "/api/launcher/version")
                if code == 200 and data.get("version"):
                    remote_ver = str(data["version"]).strip()
                    current_ver = APP_VERSION.strip()

                    def _parse_v(v_str):
                        clean = v_str.lstrip("vV")
                        return [int(x) for x in clean.split(".") if x.isdigit()]

                    is_newer = False
                    try:
                        is_newer = _parse_v(remote_ver) > _parse_v(current_ver)
                    except Exception:
                        is_newer = (remote_ver != current_ver)

                    if is_newer:
                        chg = data.get("changelog", "Pembaruan stabilitas sistem dan fitur baru.")
                        msg = (
                            f"Update Baru Sin'X Launcher Tersedia!\n\n"
                            f"Versi Anda saat ini : v{current_ver}\n"
                            f"Versi terbaru server : v{remote_ver}\n\n"
                            f"Catatan Pembaruan:\n{chg}\n\n"
                            f"Apakah Anda ingin membuka link unduhan untuk memperbarui sekarang?"
                        )
                        def _prompt():
                            if messagebox.askyesno("Update Sin'X Launcher", msg):
                                dl_path = data.get("download_url") or "/api/launcher/download"
                                full_dl = dl_path if dl_path.startswith("http") else f"{url}{dl_path}"
                                webbrowser.open(full_dl)
                        self.after(0, _prompt)
                    else:
                        if manual:
                            self.after(0, lambda: messagebox.showinfo("Update", f"Aplikasi Sin'X Launcher sudah versi terbaru (v{current_ver})!"))
                else:
                    if manual:
                        self.after(0, lambda: messagebox.showwarning("Update", f"Tidak dapat mengambil info versi dari server (HTTP {code})."))
            except Exception as e:
                if manual:
                    self.after(0, lambda: messagebox.showerror("Error Update", f"Gagal menghubungi server untuk cek update:\n{e}"))

        threading.Thread(target=_check, daemon=True).start()

    def download_latest_exe(self):
        url = normalize_url(self.sv_url.get().strip())
        if not url:
            messagebox.showwarning("Download", "Isi Server URL terlebih dahulu.")
            return
        webbrowser.open(f"{url}/api/launcher/download")


if __name__ == "__main__":
    app = SinXLauncher()
    app.mainloop()