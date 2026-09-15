"""
OSAP Launcher — Local Windows Client
=====================================
Lightweight local launcher for OSAP dedicated server.
Features:
- Fixed server URL normalization (auto-fixes https://https://...)
- Per-user Smart Schedule & Jam Posting setup
- Per-user FFmpeg Anti-Hash Filters setup
- Per-user Video Watermark (Middle-Left) setup
- Per-user Telegram Bot Notification setup
- Gudang Konten: input URLs & monitor queue per-account
- Cookie export & upload / local browser login
- Account & password management
"""

import json
import os
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import configparser

try:
    import requests
except ImportError:
    pass

# ─────────────────────────────────────────────
# URL Normalizer (Fixes double https://)
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# Config file (saved locally)
# ─────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".osap_launcher" / "config.ini"
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

def load_config() -> dict:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH))
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
    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)

# ─────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────
def api_get(server_url: str, path: str, token: str = "") -> tuple:
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    r = requests.get(f"{base}{path}", headers=headers, timeout=10)
    return r.json(), r.status_code

def api_post(server_url: str, path: str, data: dict = None, token: str = "", files=None) -> tuple:
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    if files:
        r = requests.post(f"{base}{path}", headers=headers, files=files, timeout=35)
    else:
        headers["Content-Type"] = "application/json"
        r = requests.post(f"{base}{path}", headers=headers, json=data, timeout=12)
    return r.json(), r.status_code

# ─────────────────────────────────────────────
# Colors & Style
# ─────────────────────────────────────────────
BG = "#1a1a2e"
CARD_BG = "#16213e"
ACCENT = "#6c63ff"
ACCENT2 = "#a855f7"
SUCCESS = "#10b981"
DANGER = "#ef4444"
TEXT = "#f1f5f9"
TEXT_DIM = "#94a3b8"
BORDER = "#2d3748"

PLATFORMS = [
    ("youtube", "YouTube"),
    ("instagram", "Instagram"),
    ("tiktok", "TikTok"),
    ("facebook", "Facebook"),
    ("twitter", "Twitter/X"),
    ("twitter_nsfw", "Twitter NSF"),
    ("upscrolled", "Upscrolled"),
    ("febspot", "Febspot"),
]

# ─────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────
class OSAPLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OSAP Launcher — Client Lokal")
        self.geometry("640x760")
        self.minsize(600, 680)
        self.configure(bg=BG)

        self.cfg = load_config()
        self.token = self.cfg.get("token", "")
        self.current_user = None
        self.user_settings = {}

        self._build_ui()
        self._auto_login_if_token()

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=12)
        hdr.pack(fill="x", padx=16)

        tk.Label(hdr, text="OSAP Launcher", font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=TEXT).pack(side="left")

        self.status_dot = tk.Label(hdr, text="●", font=("Segoe UI", 14), bg=BG, fg=DANGER)
        self.status_dot.pack(side="right", padx=(0, 4))
        self.status_lbl = tk.Label(hdr, text="Belum Login", font=("Segoe UI", 10), bg=BG, fg=TEXT_DIM)
        self.status_lbl.pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        # Style
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD_BG, foreground=TEXT_DIM,
                        padding=[12, 6], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("TFrame", background=BG)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)

        # Create Tabs
        self.tab_login = ttk.Frame(self.nb)
        self.tab_queue = ttk.Frame(self.nb)
        self.tab_schedule = ttk.Frame(self.nb)
        self.tab_antihash = ttk.Frame(self.nb)
        self.tab_watermark = ttk.Frame(self.nb)
        self.tab_telegram = ttk.Frame(self.nb)
        self.tab_cookies = ttk.Frame(self.nb)

        self.nb.add(self.tab_login, text=" Login ")
        self.nb.add(self.tab_queue, text=" Antrean Video ")
        self.nb.add(self.tab_schedule, text=" Jadwal Posting ")
        self.nb.add(self.tab_antihash, text=" Anti-Hash ")
        self.nb.add(self.tab_watermark, text=" Watermark ")
        self.nb.add(self.tab_telegram, text=" Telegram ")
        self.nb.add(self.tab_cookies, text=" Cookies ")

        self._build_login_tab()
        self._build_queue_tab()
        self._build_schedule_tab()
        self._build_antihash_tab()
        self._build_watermark_tab()
        self._build_telegram_tab()
        self._build_cookies_tab()

        # Log box at bottom
        log_frame = tk.Frame(self, bg=CARD_BG, bd=0)
        log_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.log_box = scrolledtext.ScrolledText(log_frame, height=4, font=("Consolas", 8),
                                                  bg="#0d1117", fg=TEXT_DIM,
                                                  insertbackground=TEXT, state="disabled",
                                                  bd=0, relief="flat", wrap="word")
        self.log_box.pack(fill="x", padx=2, pady=2)

    # ─────────────────────────────────────────────
    # TAB 1: LOGIN
    # ─────────────────────────────────────────────
    def _build_login_tab(self):
        f = self.tab_login
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="Server URL", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_url = tk.StringVar(value=self.cfg["server_url"])
        tk.Entry(outer, textvariable=self.sv_url, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Username Karyawan", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_user = tk.StringVar(value=self.cfg["username"])
        tk.Entry(outer, textvariable=self.sv_user, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Password", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_pass = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_pass, show="*", font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 14))

        self.login_btn = tk.Button(outer, text="🔑  Login ke Server", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.do_login)
        self.login_btn.pack(fill="x", pady=(0, 6))

        self.dash_btn = tk.Button(outer, text="🌐  Buka Dashboard Web (Opsional)", font=("Segoe UI", 10, "bold"), bg="#0f3460", fg="white", relief="flat", cursor="hand2", pady=8, command=self.open_dashboard, state="disabled")
        self.dash_btn.pack(fill="x", pady=(0, 6))

        self.logout_btn = tk.Button(outer, text="Logout", font=("Segoe UI", 9), bg=BORDER, fg=TEXT_DIM, relief="flat", cursor="hand2", pady=5, command=self.do_logout, state="disabled")
        self.logout_btn.pack(fill="x", pady=(0, 6))

        self.user_info_lbl = tk.Label(outer, text="", font=("Segoe UI", 10), bg=BG, fg=SUCCESS)
        self.user_info_lbl.pack(pady=(4, 0))

    # ─────────────────────────────────────────────
    # TAB 2: ANTREAN VIDEO (GUDANG KONTEN)
    # ─────────────────────────────────────────────
    def _build_queue_tab(self):
        f = self.tab_queue
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        tk.Label(outer, text="Gudang Konten (Antrean Video Lo)", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Masukkan link video (YouTube Shorts, TikTok, IG Reels) 1 URL per baris:", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 6))

        self.url_text = scrolledtext.ScrolledText(outer, height=4, font=("Consolas", 9), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=4)
        self.url_text.pack(fill="x", pady=(0, 8))

        btn_box = tk.Frame(outer, bg=BG)
        btn_box.pack(fill="x", pady=(0, 10))

        self.add_urls_btn = tk.Button(btn_box, text="📥  Tambah ke Gudang Konten", font=("Segoe UI", 9, "bold"), bg=SUCCESS, fg="white", relief="flat", cursor="hand2", pady=6, command=self.submit_urls)
        self.add_urls_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.refresh_queue_btn = tk.Button(btn_box, text="🔄  Refresh Status", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT, relief="flat", cursor="hand2", pady=6, command=self.load_my_videos)
        self.refresh_queue_btn.pack(side="right", padx=(4, 0))

        # Queue List Box
        tk.Label(outer, text="Daftar Status Video Lo:", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(4, 2))

        q_list_frame = tk.Frame(outer, bg=CARD_BG)
        q_list_frame.pack(fill="both", expand=True)

        self.queue_box = scrolledtext.ScrolledText(q_list_frame, font=("Consolas", 9), bg=CARD_BG, fg=TEXT, state="disabled", relief="flat", bd=4)
        self.queue_box.pack(fill="both", expand=True)

    # ─────────────────────────────────────────────
    # TAB 3: SMART SCHEDULE & JAM POSTING
    # ─────────────────────────────────────────────
    def _build_schedule_tab(self):
        f = self.tab_schedule
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="Smart Schedule & Jam Posting Pribadi", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Atur jam posting khusus untuk akun lo sendiri:", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 12))

        tk.Label(outer, text="Jam Posting / Prime-Time Slots (pisahkan koma)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_slots = tk.StringVar(value="12:00, 18:00, 21:00")
        tk.Entry(outer, textvariable=self.sv_slots, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Timezone", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_tz = tk.StringVar(value="Asia/Jakarta")
        tk.Entry(outer, textvariable=self.sv_tz, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Maksimal Post per Jam", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_pph = tk.StringVar(value="2")
        tk.Entry(outer, textvariable=self.sv_pph, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Delay Antar Platform (detik)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_delay = tk.StringVar(value="30")
        tk.Entry(outer, textvariable=self.sv_delay, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 16))

        tk.Button(outer, text="💾  Simpan Pengaturan Jadwal", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.save_schedule_settings).pack(fill="x")

    # ─────────────────────────────────────────────
    # TAB 4: FFMPEG ANTI-HASH FILTERS
    # ─────────────────────────────────────────────
    def _build_antihash_tab(self):
        f = self.tab_antihash
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="FFmpeg Anti-Hash Filters Pribadi", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Modifikasi parameter render video agar lolos deteksi copyright/reupload:", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 12))

        tk.Label(outer, text="Zoom & Crop Factor (contoh: 1.05 = zoom 5%)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_zoom = tk.StringVar(value="1.05")
        tk.Entry(outer, textvariable=self.sv_zoom, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Video Speed Factor (contoh: 1.05 = 5% lebih cepat)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_speed = tk.StringVar(value="1.05")
        tk.Entry(outer, textvariable=self.sv_speed, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Noise Amount Injection (1 - 3)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_noise = tk.StringVar(value="3")
        tk.Entry(outer, textvariable=self.sv_noise, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Contrast Multiplier (contoh: 1.05)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_contrast = tk.StringVar(value="1.05")
        tk.Entry(outer, textvariable=self.sv_contrast, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Saturation Multiplier (contoh: 1.08)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_saturation = tk.StringVar(value="1.08")
        tk.Entry(outer, textvariable=self.sv_saturation, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 16))

        tk.Button(outer, text="💾  Simpan Filter Anti-Hash", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.save_antihash_settings).pack(fill="x")

    # ─────────────────────────────────────────────
    # TAB 5: VIDEO WATERMARK (MIDDLE-LEFT)
    # ─────────────────────────────────────────────
    def _build_watermark_tab(self):
        f = self.tab_watermark
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="Video Watermark (Middle-Left) Pribadi", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Teks watermark otomatis dirender di sisi Kiri-Tengah video:", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 12))

        self.sv_wm_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(outer, text="Aktifkan Watermark pada Video Lo", variable=self.sv_wm_enabled, font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT, selectcolor=ACCENT, activebackground=BG, activeforeground=TEXT).pack(anchor="w", pady=(0, 10))

        tk.Label(outer, text="Teks Watermark (contoh: @channel_lo)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_wm_text = tk.StringVar(value="")
        tk.Entry(outer, textvariable=self.sv_wm_text, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Ukuran Font (contoh: 15 atau 20)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_wm_size = tk.StringVar(value="15")
        tk.Entry(outer, textvariable=self.sv_wm_size, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Opacity / Transparansi (0.1 - 1.0, contoh: 0.3)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_wm_opacity = tk.StringVar(value="0.3")
        tk.Entry(outer, textvariable=self.sv_wm_opacity, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Warna Teks (contoh: white, yellow, cyan)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_wm_color = tk.StringVar(value="white")
        tk.Entry(outer, textvariable=self.sv_wm_color, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 16))

        tk.Button(outer, text="💾  Simpan Pengaturan Watermark", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.save_watermark_settings).pack(fill="x")

    # ─────────────────────────────────────────────
    # TAB 6: NOTIFIKASI BOT TELEGRAM
    # ─────────────────────────────────────────────
    def _build_telegram_tab(self):
        f = self.tab_telegram
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="Notifikasi Bot Telegram Pribadi", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Dapatkan laporan langsung ke Telegram saat video lo selesai diposting:", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 12))

        self.sv_tg_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(outer, text="Aktifkan Notifikasi Telegram untuk Akun Lo", variable=self.sv_tg_enabled, font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT, selectcolor=ACCENT, activebackground=BG, activeforeground=TEXT).pack(anchor="w", pady=(0, 10))

        tk.Label(outer, text="Telegram Bot Token (dari @BotFather)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_tg_token = tk.StringVar(value="")
        tk.Entry(outer, textvariable=self.sv_tg_token, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 10))

        tk.Label(outer, text="Telegram Chat ID (dari @userinfobot)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 2))
        self.sv_tg_chatid = tk.StringVar(value="")
        tk.Entry(outer, textvariable=self.sv_tg_chatid, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(0, 14))

        tk.Button(outer, text="🔔  Test Kirim Notifikasi ke Telegram", font=("Segoe UI", 10, "bold"), bg="#0f3460", fg="white", relief="flat", cursor="hand2", pady=8, command=self.test_telegram).pack(fill="x", pady=(0, 8))

        tk.Button(outer, text="💾  Simpan Pengaturan Telegram", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.save_telegram_settings).pack(fill="x")

    # ─────────────────────────────────────────────
    # TAB 7: COOKIES SOSMED
    # ─────────────────────────────────────────────
    def _build_cookies_tab(self):
        f = self.tab_cookies
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(outer, text="Upload Cookie Akun Sosmed Lo", font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Export cookies dari browser lo (Get cookies.txt LOCALLY / Cookie-Editor):", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 10))

        tk.Label(outer, text="Pilih Platform", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_platform = tk.StringVar(value="youtube")
        plat_frame = tk.Frame(outer, bg=BG)
        plat_frame.pack(fill="x", pady=(4, 10))
        for val, label in PLATFORMS:
            tk.Radiobutton(plat_frame, text=label, variable=self.sv_platform, value=val, bg=BG, fg=TEXT_DIM, selectcolor=ACCENT, activebackground=BG, activeforeground=TEXT, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))

        tk.Label(outer, text="Target Key (opsional, kosongkan = platform bawaan)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_target = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_target, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(2, 10))

        tk.Button(outer, text="📂  Pilih & Upload File Cookie ke Server", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.upload_cookie_file).pack(fill="x", pady=(0, 10))

        ttk.Separator(outer).pack(fill="x", pady=10)

        tk.Label(outer, text="Login Manual via Browser Lokal", font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Buka browser Chromium lokal untuk login manual & kirim cookies otomatis:", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(2, 6))

        tk.Button(outer, text="🖥️  Login Browser Lokal & Kirim Cookie", font=("Segoe UI", 10, "bold"), bg="#0f3460", fg="white", relief="flat", cursor="hand2", pady=8, command=self.do_local_browser_login).pack(fill="x")

    # ─────────────────────────────────────────────
    # Logic & Handlers
    # ─────────────────────────────────────────────
    def log(self, msg: str, color: str = None):
        self.log_box.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        tag = f"t_{ts}_{color or 'n'}"
        self.log_box.insert("end", f"[{ts}] {msg}\n", tag)
        if color:
            self.log_box.tag_configure(tag, foreground=color)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_status(self, text: str, ok: bool = False):
        self.status_dot.configure(fg=SUCCESS if ok else DANGER)
        self.status_lbl.configure(fg=SUCCESS if ok else TEXT_DIM, text=text)

    def _set_logged_in(self, user: dict):
        self.current_user = user
        self.dash_btn.configure(state="normal")
        self.logout_btn.configure(state="normal")
        self.login_btn.configure(state="disabled")
        name = user.get("username", "?")
        acc = user.get("account_id", "?")
        admin = " [ADMIN]" if user.get("is_admin") else ""
        self.user_info_lbl.configure(text=f"✓ Login sebagai: {name}{admin}  (account #{acc})")
        self.set_status(f"Connected: {name}", ok=True)
        # Load personal settings and queue
        self.load_user_settings()
        self.load_my_videos()

    def _set_logged_out(self):
        self.current_user = None
        self.token = ""
        self.dash_btn.configure(state="disabled")
        self.logout_btn.configure(state="disabled")
        self.login_btn.configure(state="normal")
        self.user_info_lbl.configure(text="")
        self.set_status("Belum Login", ok=False)

    def do_login(self):
        url = normalize_url(self.sv_url.get().strip())
        user = self.sv_user.get().strip()
        pw = self.sv_pass.get()
        if not url or not user or not pw:
            messagebox.showerror("Error", "Server URL, username, dan password wajib diisi.")
            return

        self.sv_url.set(url)
        self.log(f"Login ke {url} sebagai '{user}'...")
        self.login_btn.configure(state="disabled", text="Memverifikasi...")

        def _do():
            try:
                data, code = api_post(url, "/api/auth/login", {"username": user, "password": pw})
                if code == 200 and data.get("token"):
                    self.token = data["token"]
                    save_config(url, user, self.token)
                    self.after(0, lambda: self._set_logged_in(data))
                    self.after(0, lambda: self.log(f"Login berhasil! Halo {data['username']} 🎉", SUCCESS))
                else:
                    err = data.get("detail", "Login gagal")
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

    def _auto_login_if_token(self):
        if not self.token:
            return
        url = normalize_url(self.cfg["server_url"])
        self.log("Memverifikasi sesi tersimpan...")
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

    def open_dashboard(self):
        url = normalize_url(self.sv_url.get().strip())
        if not url:
            return
        full_url = f"{url}/?token={self.token}" if self.token else url
        webbrowser.open(full_url)
        self.log(f"Membuka browser: {url}", TEXT_DIM)

    # ─────────────────────────────────────────────
    # Load & Save User Settings
    # ─────────────────────────────────────────────
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
                    # Populate GUI fields
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

                    self.after(0, lambda: self.log("Pengaturan akun pribadi berhasil dimuat dari server.", SUCCESS))
            except Exception as e:
                self.after(0, lambda: self.log(f"Gagal memuat pengaturan akun: {e}", TEXT_DIM))
        threading.Thread(target=_do, daemon=True).start()

    def _save_settings(self, payload: dict, label: str):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        url = normalize_url(self.sv_url.get().strip())
        self.log(f"Menyimpan {label}...")
        def _do():
            try:
                data, code = api_post(url, "/api/user/settings", payload, token=self.token)
                if code == 200:
                    self.after(0, lambda: self.log(f"✓ {label} berhasil disimpan!", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Sukses", f"{label} berhasil disimpan ke akun lo!"))
                else:
                    err = data.get("detail", "Gagal menyimpan")
                    self.after(0, lambda: self.log(f"✗ Gagal: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def save_schedule_settings(self):
        raw_slots = [s.strip() for s in self.sv_slots.get().split(",") if s.strip()]
        payload = {
            "schedule_slots": raw_slots,
            "timezone": self.sv_tz.get().strip() or "Asia/Jakarta",
            "posts_per_hour": int(self.sv_pph.get() or 2),
            "delay_between_platforms_sec": int(self.sv_delay.get() or 30),
        }
        self._save_settings(payload, "Jadwal Posting")

    def save_antihash_settings(self):
        payload = {
            "ffmpeg_zoom": float(self.sv_zoom.get() or 1.05),
            "ffmpeg_speed": float(self.sv_speed.get() or 1.05),
            "ffmpeg_noise": int(self.sv_noise.get() or 3),
            "ffmpeg_contrast": float(self.sv_contrast.get() or 1.05),
            "ffmpeg_saturation": float(self.sv_saturation.get() or 1.08),
        }
        self._save_settings(payload, "Pengaturan Anti-Hash")

    def save_watermark_settings(self):
        payload = {
            "watermark_enabled": bool(self.sv_wm_enabled.get()),
            "watermark_text": self.sv_wm_text.get().strip(),
            "watermark_font_size": int(self.sv_wm_size.get() or 15),
            "watermark_opacity": float(self.sv_wm_opacity.get() or 0.3),
            "watermark_color": self.sv_wm_color.get().strip() or "white",
        }
        self._save_settings(payload, "Pengaturan Watermark")

    def save_telegram_settings(self):
        payload = {
            "telegram_enabled": bool(self.sv_tg_enabled.get()),
            "telegram_bot_token": self.sv_tg_token.get().strip(),
            "telegram_chat_id": self.sv_tg_chatid.get().strip(),
        }
        self._save_settings(payload, "Pengaturan Telegram")

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
                    self.after(0, lambda: messagebox.showinfo("Berhasil", "Pesan test Telegram berhasil dikirim ke chat lo! Cek aplikasi Telegram."))
                else:
                    err = data.get("detail", "Gagal mengirim Telegram")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    # ─────────────────────────────────────────────
    # Queue Management
    # ─────────────────────────────────────────────
    def submit_urls(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        raw = self.url_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showerror("Error", "Masukkan minimal 1 link video.")
            return
        url = normalize_url(self.sv_url.get().strip())
        self.log("Mengirim URL ke Gudang Konten...")
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
                data, code = api_get(url, "/api/videos?limit=30", token=self.token)
                if code == 200:
                    videos = data.get("videos", [])
                    total = data.get("total", 0)
                    lines = [f"Total Video Lo: {total}\n" + "─" * 45]
                    if not videos:
                        lines.append("Belum ada video di antrean lo.")
                    else:
                        for v in videos:
                            status = v.get("status", "-").upper()
                            vid_title = v.get("title") or v.get("ai_title") or v.get("video_id") or v.get("url", "")
                            lines.append(f"• [#{v['id']}] [{status}] {vid_title[:45]}")
                    text = "\n".join(lines)
                    self.after(0, lambda: self._set_queue_text(text))
            except Exception as e:
                self.after(0, lambda: self._set_queue_text(f"Error memuat antrean: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def _set_queue_text(self, text: str):
        self.queue_box.configure(state="normal")
        self.queue_box.delete("1.0", "end")
        self.queue_box.insert("end", text)
        self.queue_box.configure(state="disabled")

    # ─────────────────────────────────────────────
    # Cookies & Local Browser Login
    # ─────────────────────────────────────────────
    def upload_cookie_file(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        platform = self.sv_platform.get()
        target_key = self.sv_target.get().strip() or platform
        url = normalize_url(self.sv_url.get().strip())

        file_path = filedialog.askopenfilename(
            title="Pilih file cookie",
            filetypes=[("Cookie files", "*.txt *.json"), ("All files", "*.*")]
        )
        if not file_path:
            return
        self.log(f"Mengupload cookies '{target_key}'...")
        def _do():
            try:
                with open(file_path, "rb") as fh:
                    files = {"file": (Path(file_path).name, fh, "application/octet-stream")}
                    data, code = api_post(url, f"/api/upload-cookies/{target_key}", token=self.token, files=files)
                if code == 200:
                    msg = data.get("message", "Upload berhasil!")
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Sukses", msg))
                else:
                    err = data.get("detail", "Upload gagal")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def do_local_browser_login(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        platform = self.sv_platform.get()
        target_key = self.sv_target.get().strip() or platform
        url_map = {
            "youtube": "https://accounts.google.com",
            "instagram": "https://www.instagram.com/accounts/login",
            "tiktok": "https://www.tiktok.com/login",
            "facebook": "https://www.facebook.com/login",
            "twitter": "https://x.com/i/flow/login",
            "twitter_nsfw": "https://x.com/i/flow/login",
            "upscrolled": "https://upscrolled.com",
            "febspot": "https://febspot.com",
        }
        login_url = url_map.get(platform, f"https://{platform}.com")
        self.log(f"Membuka browser lokal untuk login {platform}...", TEXT_DIM)
        def _do():
            try:
                from playwright.sync_api import sync_playwright
                import tempfile, json as _json
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
                    context = browser.new_context(viewport={"width": 1280, "height": 720})
                    page = context.new_page()
                    page.goto(login_url)
                    self.after(0, lambda: self.log("Browser terbuka. Selesaikan login, lalu TUTUP browser saat selesai.", TEXT_DIM))
                    try:
                        page.wait_for_event("close", timeout=300_000)
                    except Exception:
                        pass
                    cookies = context.cookies()
                    context.close()
                    browser.close()
                if not cookies:
                    self.after(0, lambda: self.log("Tidak ada cookies ditemukan.", DANGER))
                    return
                self.after(0, lambda: self.log(f"✓ {len(cookies)} cookies diekstrak. Mengupload ke server...", SUCCESS))
                server_url = normalize_url(self.sv_url.get().strip())
                tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
                _json.dump(cookies, tmp)
                tmp.close()
                with open(tmp.name, "rb") as fh:
                    files = {"file": (f"{target_key}_cookies.json", fh, "application/json")}
                    data, code = api_post(server_url, f"/api/upload-cookies/{target_key}", token=self.token, files=files)
                os.unlink(tmp.name)
                if code == 200:
                    msg = data.get("message", "Cookies berhasil diupload!")
                    self.after(0, lambda: self.log(f"✓ {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", msg))
                else:
                    err = data.get("detail", "Upload cookies gagal")
                    self.after(0, lambda: self.log(f"✗ {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except ImportError:
                self.after(0, lambda: messagebox.showerror("Playwright tidak ditemukan", "Install: pip install playwright && playwright install chromium"))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

if __name__ == "__main__":
    app = OSAPLauncher()
    app.mainloop()
