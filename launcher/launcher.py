"""
Sin'X Automation — Client Desktop Karyawan (Modern Enterprise UI)
=================================================================
Desktop client for Sin'X Automation (OmniShorts Auto-Publisher).
Features modern Windows 11 rounded corners, native dark title bar,
sleek segmented pill navigation, rounded action buttons, and elevated cards.
"""

from __future__ import annotations

import os
import sys
import json
import time
import queue
import ctypes
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
# Theme Colors (Modern Slate & Indigo Enterprise Palette)
# ─────────────────────────────────────────────────────────────
BG = "#0b0f19"              # Deep Midnight Slate
CARD_BG = "#131b2e"         # Elevated Slate Card
CARD_BORDER = "#1f2d44"     # Subtle Border
CARD_HOVER = "#18233c"      # Hover state for card
HEADER_BG = "#0f172a"       # Slate 900
INPUT_BG = "#080c14"        # Inset dark input
INPUT_BORDER = "#223147"    # Input outline

ACCENT = "#6366f1"          # Modern Indigo 500
ACCENT_HOVER = "#4f46e5"    # Indigo 600
ACCENT_ACTIVE = "#4338ca"   # Indigo 700
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


def apply_windows_dark_mode(window: tk.Tk | tk.Toplevel):
    """Enables native Windows 10/11 dark title bar, rounded window corners, and matching caption color."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 20H1+ & Windows 11)
        dark_mode = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))

        # DWMWA_WINDOW_CORNER_PREFERENCE = 33 (2 = DWMWCP_ROUND)
        corner_pref = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))

        # DWMWA_CAPTION_COLOR = 35 (hex #0b0f19 in BGR: 0x00190F0B)
        caption_color = ctypes.c_int(0x00190F0B)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
    except Exception:
        pass


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


# ─────────────────────────────────────────────────────────────
# Modern UI Component: Rounded Canvas Button
# ─────────────────────────────────────────────────────────────
class RoundedButton(tk.Canvas):
    """
    Sleek anti-aliased pill / rounded rectangle button with smooth hover,
    active press feedback, clean typography, and hand cursor.
    """
    def __init__(
        self, parent, text: str = "", command=None,
        bg_color: str = ACCENT, fg_color: str = "#ffffff",
        hover_color: str = ACCENT_HOVER, active_color: str = ACCENT_ACTIVE,
        radius: int = 10, font: tuple = ("Segoe UI", 9, "bold"),
        height: int = 36, width: int = 120, state: str = "normal",
        outline: str = "", **kwargs
    ):
        parent_bg = kwargs.pop("parent_bg", parent.cget("bg") if hasattr(parent, "cget") else BG)
        super().__init__(parent, height=height, width=width, bg=parent_bg, highlightthickness=0, bd=0, **kwargs)
        self.text = text
        self.command = command
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_color = hover_color
        self.active_color = active_color
        self.radius = radius
        self.font = font
        self.state_val = state
        self.outline = outline
        self.is_pressed = False

        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.configure(cursor="hand2" if state != "disabled" else "")

    def _draw(self, w: int, h: int, fill_color: str):
        self.delete("all")
        if w < 4 or h < 4:
            return
        r = min(self.radius, w // 2, h // 2)
        pts = [
            2 + r, 2,  2 + r, 2,  w - 2 - r, 2,  w - 2 - r, 2,  w - 2, 2,
            w - 2, 2 + r,  w - 2, 2 + r,  w - 2, h - 2 - r,  w - 2, h - 2 - r,  w - 2, h - 2,
            w - 2 - r, h - 2,  w - 2 - r, h - 2,  2 + r, h - 2,  2 + r, h - 2,  2, h - 2,
            2, h - 2 - r,  2, h - 2 - r,  2, 2 + r,  2, 2 + r,  2, 2
        ]
        self.create_polygon(pts, smooth=True, fill=fill_color, outline=self.outline)
        fg = self.fg_color if self.state_val != "disabled" else "#64748b"
        self.create_text(w // 2, h // 2, text=self.text, fill=fg, font=self.font)

    def _on_resize(self, event):
        self._draw(event.width, event.height, self.bg_color)

    def _on_enter(self, _e):
        if self.state_val != "disabled" and not self.is_pressed:
            self._draw(self.winfo_width(), self.winfo_height(), self.hover_color)

    def _on_leave(self, _e):
        self.is_pressed = False
        if self.state_val != "disabled":
            self._draw(self.winfo_width(), self.winfo_height(), self.bg_color)

    def _on_click(self, _e):
        if self.state_val != "disabled":
            self.is_pressed = True
            self._draw(self.winfo_width(), self.winfo_height(), self.active_color)

    def _on_release(self, _e):
        if self.state_val != "disabled":
            self.is_pressed = False
            self._draw(self.winfo_width(), self.winfo_height(), self.hover_color)
            if self.command:
                self.command()

    def set_text(self, text: str):
        self.text = text
        self._draw(self.winfo_width(), self.winfo_height(), self.bg_color)

    def set_state(self, state: str):
        self.state_val = state
        self.configure(cursor="hand2" if state != "disabled" else "")
        self._draw(self.winfo_width(), self.winfo_height(), self.bg_color)


# ─────────────────────────────────────────────────────────────
# Modern UI Component: Elevated Card Container
# ─────────────────────────────────────────────────────────────
def create_modern_card(parent, padx: int = 16, pady: int = 14, **kwargs) -> tuple[tk.Frame, tk.Frame]:
    """Creates a modern elevated slate card with a subtle border and generous padding."""
    outer = tk.Frame(parent, bg=CARD_BORDER, padx=1, pady=1, **kwargs)
    inner = tk.Frame(outer, bg=CARD_BG, padx=padx, pady=pady)
    inner.pack(fill="both", expand=True)
    return outer, inner


def create_modern_entry(parent, textvariable=None, show=None, font=("Segoe UI", 9), **kwargs):
    """Creates an inset dark entry field that smoothly highlights its border on focus."""
    wrapper = tk.Frame(parent, bg=INPUT_BORDER, padx=1, pady=1)
    inner = tk.Frame(wrapper, bg=INPUT_BG, padx=10, pady=7)
    inner.pack(fill="both", expand=True)
    entry = tk.Entry(
        inner, textvariable=textvariable, show=show, font=font,
        bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, **kwargs
    )
    entry.pack(fill="both", expand=True)

    def on_focus_in(_e):
        wrapper.configure(bg=ACCENT)

    def on_focus_out(_e):
        wrapper.configure(bg=INPUT_BORDER)

    entry.bind("<FocusIn>", on_focus_in)
    entry.bind("<FocusOut>", on_focus_out)
    return wrapper, entry


# ─────────────────────────────────────────────────────────────
# Modern UI Component: Segmented Nav Bar (Top Pill Tabs)
# ─────────────────────────────────────────────────────────────
class ModernSegmentedNav(tk.Frame):
    """Horizontal segmented pill tab bar replacing boxy standard notebook tabs."""
    def __init__(self, parent, tabs: list[tuple[str, str]], on_select, bg=HEADER_BG, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.tabs = tabs
        self.on_select = on_select
        self.buttons: list[RoundedButton] = []
        self.active_idx = 0

        border_box = tk.Frame(self, bg=CARD_BORDER, padx=1, pady=1)
        border_box.pack(fill="x")
        self.container = tk.Frame(border_box, bg="#0d1424", padx=5, pady=5)
        self.container.pack(fill="x")

        for idx, (icon, title) in enumerate(tabs):
            btn = RoundedButton(
                self.container,
                text=f"{icon}  {title}",
                command=lambda i=idx: self.select(i),
                bg_color=ACCENT if idx == 0 else "#0d1424",
                fg_color="#ffffff" if idx == 0 else TEXT_DIM,
                hover_color=ACCENT_HOVER if idx == 0 else "#19243b",
                radius=8,
                height=34,
                width=170,
                parent_bg="#0d1424",
                font=("Segoe UI", 9, "bold" if idx == 0 else "normal"),
            )
            btn.pack(side="left", padx=3, fill="x", expand=True)
            self.buttons.append(btn)

    def select(self, idx: int):
        self.active_idx = idx
        for i, b in enumerate(self.buttons):
            if i == idx:
                b.bg_color = ACCENT
                b.fg_color = "#ffffff"
                b.hover_color = ACCENT_HOVER
                b.font = ("Segoe UI", 9, "bold")
            else:
                b.bg_color = "#0d1424"
                b.fg_color = TEXT_DIM
                b.hover_color = "#19243b"
                b.font = ("Segoe UI", 9, "normal")
            b._draw(b.winfo_width(), b.winfo_height(), b.bg_color)
        self.on_select(idx)


# ─────────────────────────────────────────────────────────────
# Notebook Compatibility Adapter
# ─────────────────────────────────────────────────────────────
class NotebookAdapter:
    """Provides a `.select(tab_frame)` interface for backward compatibility."""
    def __init__(self, launcher: 'SinXLauncher'):
        self.launcher = launcher

    def select(self, target_tab):
        if target_tab == self.launcher.tab_dash:
            self.launcher.nav_bar.select(0)
        elif target_tab == self.launcher.tab_cookies:
            self.launcher.nav_bar.select(1)
        elif target_tab == self.launcher.tab_logs:
            self.launcher.nav_bar.select(2)
        elif target_tab == self.launcher.tab_login:
            self.launcher.nav_bar.select(3)


# ─────────────────────────────────────────────────────────────
# Main Application Window
# ─────────────────────────────────────────────────────────────
class SinXLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sin'X Automation — Desktop Client")
        self.geometry("900x710")
        self.minsize(860, 600)
        self.configure(bg=BG)

        # Apply native Windows 11 rounded corners & dark title bar
        apply_windows_dark_mode(self)
        self._set_app_icon()

        self.cfg = load_config()
        self.token = self.cfg.get("token", "")
        self.current_user = None
        self.user_settings = {}
        self.sse_active = False
        self.log_queue = queue.Queue()

        self._setup_ttk_styles()
        self._build_header()
        self._build_tabs()

        self.nb = NotebookAdapter(self)
        self._start_log_consumer()
        self._auto_login_if_token()
        self.after(1500, lambda: self.check_for_updates(manual=False))

    def _set_app_icon(self):
        try:
            exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
            bundle_dir = getattr(sys, "_MEIPASS", None)
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

    def _setup_ttk_styles(self):
        style = ttk.Style(self)
        style.theme_use("default")

        # Combobox styling
        style.configure(
            "TCombobox",
            background=INPUT_BG,
            foreground=TEXT,
            fieldbackground=INPUT_BG,
            darkcolor=INPUT_BORDER,
            lightcolor=INPUT_BORDER,
            arrowcolor=TEXT,
            bordercolor=INPUT_BORDER,
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", INPUT_BG)],
            foreground=[("readonly", TEXT)],
        )

        # Separator
        style.configure("TSeparator", background=CARD_BORDER)

    def _build_header(self):
        hdr = tk.Frame(self, bg=HEADER_BG, pady=12, padx=20)
        hdr.pack(fill="x")

        # Left branding
        left_box = tk.Frame(hdr, bg=HEADER_BG)
        left_box.pack(side="left")

        brand_row = tk.Frame(left_box, bg=HEADER_BG)
        brand_row.pack(anchor="w")

        tk.Label(brand_row, text="⚡", font=("Segoe UI", 13), bg=HEADER_BG, fg=ACCENT_CYAN).pack(side="left", padx=(0, 4))
        tk.Label(brand_row, text="SIN'X AUTOMATION", font=("Segoe UI", 13, "bold"), bg=HEADER_BG, fg=TEXT).pack(side="left")

        tk.Label(
            left_box,
            text=f"Enterprise Multi-Platform Cloud Publisher • Client Karyawan v{APP_VERSION}",
            font=("Segoe UI", 8), bg=HEADER_BG, fg=TEXT_DIM
        ).pack(anchor="w", pady=(1, 0))

        # Right status badge pill
        pill_border = tk.Frame(hdr, bg=CARD_BORDER, padx=1, pady=1)
        pill_border.pack(side="right")
        self.right_pill = tk.Frame(pill_border, bg=CARD_BG, padx=12, pady=5)
        self.right_pill.pack()

        self.status_dot = tk.Label(self.right_pill, text="●", font=("Segoe UI", 11), bg=CARD_BG, fg=DANGER)
        self.status_dot.pack(side="left", padx=(0, 6))

        self.status_lbl = tk.Label(self.right_pill, text="Offline / Belum Login", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT_DIM)
        self.status_lbl.pack(side="left")

    def _build_tabs(self):
        tab_specs = [
            ("📊", "Dashboard"),
            ("🍪", "Cookies & Profil"),
            ("📜", "Live Logs"),
            ("⚙️", "Akun & Server"),
        ]

        nav_frame = tk.Frame(self, bg=BG)
        nav_frame.pack(fill="x", padx=16, pady=(10, 4))

        self.nav_bar = ModernSegmentedNav(nav_frame, tab_specs, on_select=self._switch_tab, bg=BG)
        self.nav_bar.pack(fill="x")

        # Pages container
        self.page_container = tk.Frame(self, bg=BG)
        self.page_container.pack(fill="both", expand=True, padx=16, pady=(6, 12))

        self.tab_dash = tk.Frame(self.page_container, bg=BG)
        self.tab_cookies = tk.Frame(self.page_container, bg=BG)
        self.tab_logs = tk.Frame(self.page_container, bg=BG)
        self.tab_login = tk.Frame(self.page_container, bg=BG)

        self.pages = [self.tab_dash, self.tab_cookies, self.tab_logs, self.tab_login]

        self._build_dashboard_tab()
        self._build_cookies_tab()
        self._build_logs_tab()
        self._build_login_tab()

        self._switch_tab(0)

    def _switch_tab(self, idx: int):
        for p in self.pages:
            p.pack_forget()
        self.pages[idx].pack(fill="both", expand=True)

    # ─────────────────────────────────────────────────────────────
    # Tab 1: Dashboard
    # ─────────────────────────────────────────────────────────────
    def _build_dashboard_tab(self):
        f = self.tab_dash

        # User Card
        _u_border, u_card = create_modern_card(f, padx=16, pady=10)
        _u_border.pack(fill="x", pady=(0, 10))

        left_user = tk.Frame(u_card, bg=CARD_BG)
        left_user.pack(side="left")

        self.dash_user_lbl = tk.Label(left_user, text="Akun: Belum Terhubung", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT)
        self.dash_user_lbl.pack(anchor="w")

        self.dash_server_lbl = tk.Label(left_user, text=f"Endpoint: {self.cfg['server_url']}", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_server_lbl.pack(anchor="w", pady=(1, 0))

        badge_box = tk.Frame(u_card, bg="#1e293b", padx=10, pady=4)
        badge_box.pack(side="right")
        self.dash_acc_badge = tk.Label(badge_box, text="Account ID: -", font=("Segoe UI", 8, "bold"), bg="#1e293b", fg=ACCENT_CYAN)
        self.dash_acc_badge.pack()

        # 5 Modern Stat KPI Cards Row
        stats_box = tk.Frame(f, bg=BG)
        stats_box.pack(fill="x", pady=(0, 10))

        self.stat_total  = self._create_modern_stat_card(stats_box, "TOTAL VIDEO", "0", ACCENT, 0)
        self.stat_ready  = self._create_modern_stat_card(stats_box, "SIAP POST", "0", SUCCESS, 1)
        self.stat_proc   = self._create_modern_stat_card(stats_box, "DIPROSES", "0", WARNING, 2)
        self.stat_done   = self._create_modern_stat_card(stats_box, "SELESAI", "0", ACCENT_CYAN, 3)
        self.stat_failed = self._create_modern_stat_card(stats_box, "GAGAL", "0", DANGER, 4)

        # Scheduler Monitor Card
        _sch_border, sch_card = create_modern_card(f, padx=16, pady=12)
        _sch_border.pack(fill="x", pady=(0, 10))

        sch_hdr = tk.Frame(sch_card, bg=CARD_BG)
        sch_hdr.pack(fill="x", pady=(0, 6))

        tk.Label(sch_hdr, text="⏰", font=("Segoe UI", 10), bg=CARD_BG, fg=WARNING).pack(side="left", padx=(0, 5))
        tk.Label(sch_hdr, text="Status Smart Prime-Time Scheduler", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(side="left")

        self.dash_sch_next = tk.Label(sch_card, text="Jadwal Berikutnya: Memuat status...", font=("Segoe UI", 9), bg=CARD_BG, fg=TEXT_MUTED)
        self.dash_sch_next.pack(anchor="w", pady=1)

        self.dash_sch_slots = tk.Label(sch_card, text="Jam Tayang Aktif: -", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_slots.pack(anchor="w", pady=1)

        self.dash_sch_tz = tk.Label(sch_card, text="Timezone Acuan: -", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM)
        self.dash_sch_tz.pack(anchor="w", pady=1)

        # Quick Operational Actions Card
        _act_border, act_card = create_modern_card(f, padx=16, pady=12)
        _act_border.pack(fill="x")

        act_hdr = tk.Frame(act_card, bg=CARD_BG)
        act_hdr.pack(fill="x", pady=(0, 8))

        tk.Label(act_hdr, text="🚀", font=("Segoe UI", 10), bg=CARD_BG, fg=ACCENT).pack(side="left", padx=(0, 5))
        tk.Label(act_hdr, text="Tombol Operasional Cepat", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(side="left")

        btn_row = tk.Frame(act_card, bg=CARD_BG)
        btn_row.pack(fill="x")

        # 1. On-Demand Publish
        self.btn_publish = RoundedButton(
            btn_row, text="🚀  Post Sekarang", command=self.prompt_publish_now,
            bg_color=ACCENT, hover_color=ACCENT_HOVER, height=36, width=170, parent_bg=CARD_BG
        )
        self.btn_publish.pack(side="left", padx=(0, 8), fill="x", expand=True)

        # 2. Debug Screenshot
        self.btn_screenshot = RoundedButton(
            btn_row, text="📸  Cek Screenshot", command=self.prompt_debug_screenshot,
            bg_color="#1e3a8a", hover_color="#2563eb", height=36, width=150, parent_bg=CARD_BG
        )
        self.btn_screenshot.pack(side="left", padx=(0, 8), fill="x", expand=True)

        # 3. Refresh Stats
        self.btn_refresh = RoundedButton(
            btn_row, text="🔄  Refresh Data", command=self.refresh_dashboard_data,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=36, width=140, parent_bg=CARD_BG
        )
        self.btn_refresh.pack(side="left", padx=(0, 8), fill="x", expand=True)

        # 4. Open Web Dashboard
        self.btn_web = RoundedButton(
            btn_row, text="🌐  Buka Web UI", command=self.open_dashboard,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=36, width=140, parent_bg=CARD_BG
        )
        self.btn_web.pack(side="left", fill="x", expand=True)

    def _create_modern_stat_card(self, parent, title: str, value: str, color: str, col_idx: int) -> tk.Label:
        parent.columnconfigure(col_idx, weight=1)
        border_card = tk.Frame(parent, bg=CARD_BORDER, padx=1, pady=1)
        border_card.grid(row=0, column=col_idx, padx=3, sticky="ew")

        card = tk.Frame(border_card, bg=CARD_BG, padx=8, pady=10)
        card.pack(fill="both", expand=True)

        # Top Accent Stripe
        stripe = tk.Frame(card, bg=color, height=3)
        stripe.pack(fill="x", pady=(0, 6))

        val_lbl = tk.Label(card, text=value, font=("Segoe UI", 18, "bold"), bg=CARD_BG, fg=color)
        val_lbl.pack()

        tk.Label(card, text=title, font=("Segoe UI", 8, "bold"), bg=CARD_BG, fg=TEXT_DIM).pack()
        return val_lbl

    # ─────────────────────────────────────────────────────────────
    # Tab 2: Cookies & Profil
    # ─────────────────────────────────────────────────────────────
    def _build_cookies_tab(self):
        f = self.tab_cookies

        # Platform selector card
        _sel_border, sel_card = create_modern_card(f, padx=16, pady=12)
        _sel_border.pack(fill="x", pady=(0, 10))

        tk.Label(sel_card, text="Pilih Platform Sasaran:", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_platform_name = tk.StringVar(value="YouTube (Shorts/Studio)")
        self.cb_platform = ttk.Combobox(
            sel_card, textvariable=self.sv_platform_name,
            values=[p[1] for p in PLATFORMS], state="readonly", font=("Segoe UI", 9)
        )
        self.cb_platform.pack(fill="x", pady=(4, 8))

        tk.Label(
            sel_card,
            text="Target Key Khusus (Opsional, kosongkan bila tidak memakai custom card ID):",
            font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM
        ).pack(anchor="w")

        self.sv_target = tk.StringVar()
        _t_wrap, _t_entry = create_modern_entry(sel_card, textvariable=self.sv_target)
        _t_wrap.pack(fill="x", pady=(2, 0))

        # Upload Methods Card
        _up_border, up_card = create_modern_card(f, padx=16, pady=12)
        _up_border.pack(fill="x", pady=(0, 10))

        # Method 1
        m1_row = tk.Frame(up_card, bg=CARD_BG)
        m1_row.pack(fill="x", pady=(0, 4))
        tk.Label(m1_row, text="①", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=ACCENT).pack(side="left", padx=(0, 4))
        tk.Label(m1_row, text="Metode 1: Upload File Cookies (.json / .txt)", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(side="left")

        tk.Label(
            up_card,
            text="Export cookies dari browser lokal Anda memakai ekstensi Cookie-Editor atau Get cookies.txt LOCALLY:",
            font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM
        ).pack(anchor="w", pady=(0, 6))

        RoundedButton(
            up_card, text="📂  Pilih & Upload File Cookie (.json / .txt)", command=self.upload_cookie_file,
            bg_color=ACCENT, hover_color=ACCENT_HOVER, height=34, parent_bg=CARD_BG
        ).pack(fill="x", pady=(0, 10))

        ttk.Separator(up_card).pack(fill="x", pady=6)

        # Method 2
        m2_row = tk.Frame(up_card, bg=CARD_BG)
        m2_row.pack(fill="x", pady=(0, 4))
        tk.Label(m2_row, text="②", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=ACCENT_CYAN).pack(side="left", padx=(0, 4))
        tk.Label(m2_row, text="Metode 2: Upload Full Profil Browser (.zip)", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(side="left")

        tk.Label(
            up_card,
            text="Upload arsip ZIP folder profil browser yang sudah login (misal youtube.zip):",
            font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM
        ).pack(anchor="w", pady=(0, 6))

        RoundedButton(
            up_card, text="📦  Pilih & Upload Profil Browser (.zip)", command=self.upload_profile_zip,
            bg_color="#1e3a8a", hover_color="#2563eb", height=34, parent_bg=CARD_BG
        ).pack(fill="x")

        # Local Browser Login Card
        _loc_border, loc_card = create_modern_card(f, padx=16, pady=12)
        _loc_border.pack(fill="x")

        m3_row = tk.Frame(loc_card, bg=CARD_BG)
        m3_row.pack(fill="x", pady=(0, 4))
        tk.Label(m3_row, text="③", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=SUCCESS).pack(side="left", padx=(0, 4))
        tk.Label(m3_row, text="Metode 3: Login Otomatis Browser Lokal (Edge / Chrome)", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(side="left")

        tk.Label(
            loc_card,
            text="Buka jendela browser Edge/Chrome di PC lokal Anda untuk login manual & kirim cookies otomatis ke server:",
            font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM
        ).pack(anchor="w", pady=(0, 6))

        RoundedButton(
            loc_card, text="🖥️  Buka Browser Lokal & Ekstrak Sesi Otomatis", command=self.do_local_browser_login,
            bg_color="#047857", hover_color=SUCCESS_HOVER, height=34, parent_bg=CARD_BG
        ).pack(fill="x")

    # ─────────────────────────────────────────────────────────────
    # Tab 3: Live Logs
    # ─────────────────────────────────────────────────────────────
    def _build_logs_tab(self):
        f = self.tab_logs

        hdr_log = tk.Frame(f, bg=BG)
        hdr_log.pack(fill="x", pady=(0, 6))

        tk.Label(hdr_log, text="📜 Live Server Logs (SSE Stream)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT).pack(side="left")

        self.auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            hdr_log, text="Auto-scroll", variable=self.auto_scroll_var, font=("Segoe UI", 8),
            bg=BG, fg=TEXT_DIM, selectcolor=CARD_BG, activebackground=BG, activeforeground=TEXT
        ).pack(side="right", padx=(8, 0))

        RoundedButton(
            hdr_log, text="🔄 Hubungkan Ulang", command=self._start_sse_stream,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=28, width=130, radius=6, font=("Segoe UI", 8, "bold"), parent_bg=BG
        ).pack(side="right", padx=(4, 0))

        RoundedButton(
            hdr_log, text="🧹 Bersihkan", command=self.clear_logs,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=28, width=90, radius=6, font=("Segoe UI", 8, "bold"), parent_bg=BG
        ).pack(side="right")

        log_border = tk.Frame(f, bg=CARD_BORDER, padx=1, pady=1)
        log_border.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(
            log_border, font=("Consolas", 9), bg="#06090f", fg=TEXT,
            insertbackground=TEXT, state="disabled", relief="flat", bd=8, wrap="word"
        )
        self.log_box.pack(fill="both", expand=True)

    # ─────────────────────────────────────────────────────────────
    # Tab 4: Akun & Server
    # ─────────────────────────────────────────────────────────────
    def _build_login_tab(self):
        f = self.tab_login

        # Server Card
        _srv_border, srv_card = create_modern_card(f, padx=16, pady=12)
        _srv_border.pack(fill="x", pady=(0, 10))

        tk.Label(srv_card, text="🌐 URL Server Dedicated Sin'X Automation", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_url = tk.StringVar(value=self.cfg["server_url"])
        _u_wrap, _u_entry = create_modern_entry(srv_card, textvariable=self.sv_url)
        _u_wrap.pack(fill="x", pady=(4, 2))
        tk.Label(srv_card, text="Format: https://auto.kntl.cc atau http://ip-vps:8085", font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")

        # Credentials Card
        _c_border, c_card = create_modern_card(f, padx=16, pady=12)
        _c_border.pack(fill="x", pady=(0, 10))

        tk.Label(c_card, text="Username Karyawan:", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_user = tk.StringVar(value=self.cfg["username"])
        _usr_wrap, _usr_entry = create_modern_entry(c_card, textvariable=self.sv_user)
        _usr_wrap.pack(fill="x", pady=(2, 8))

        tk.Label(c_card, text="Password Akun:", font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w")
        self.sv_pass = tk.StringVar()
        _pw_wrap, _pw_entry = create_modern_entry(c_card, textvariable=self.sv_pass, show="*")
        _pw_wrap.pack(fill="x", pady=(2, 10))

        btn_box = tk.Frame(c_card, bg=CARD_BG)
        btn_box.pack(fill="x")

        self.login_btn = RoundedButton(
            btn_box, text="🔑  Login ke Server", command=self.do_login,
            bg_color=ACCENT, hover_color=ACCENT_HOVER, height=36, parent_bg=CARD_BG
        )
        self.login_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.logout_btn = RoundedButton(
            btn_box, text="Keluar / Logout", command=self.do_logout,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_DIM, state="disabled", height=36, width=130, parent_bg=CARD_BG
        )
        self.logout_btn.pack(side="right")

        # Change Password Card
        _pw_card_border, pw_card = create_modern_card(f, padx=16, pady=12)
        _pw_card_border.pack(fill="x", pady=(0, 10))

        tk.Label(pw_card, text="🔒 Ganti Password Akun Anda", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 6))

        tk.Label(pw_card, text="Password Saat Ini:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_cur_pw = tk.StringVar()
        _cp_wrap, _cp_entry = create_modern_entry(pw_card, textvariable=self.sv_cur_pw, show="*")
        _cp_wrap.pack(fill="x", pady=(1, 6))

        tk.Label(pw_card, text="Password Baru (minimal 6 karakter):", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_new_pw = tk.StringVar()
        _np_wrap, _np_entry = create_modern_entry(pw_card, textvariable=self.sv_new_pw, show="*")
        _np_wrap.pack(fill="x", pady=(1, 8))

        RoundedButton(
            pw_card, text="Simpan Password Baru", command=self.change_password,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=34, parent_bg=CARD_BG
        ).pack(fill="x")

        # Update & Distribution Card
        _upd_border, upd_card = create_modern_card(f, padx=16, pady=12)
        _upd_border.pack(fill="x")

        tk.Label(upd_card, text=f"🚀 Versi Aplikasi & Distribusi Client (v{APP_VERSION})", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 2))
        tk.Label(upd_card, text="Client Karyawan Sin'X Automation • Auto-Update Terintegrasi", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 8))

        upd_btn_box = tk.Frame(upd_card, bg=CARD_BG)
        upd_btn_box.pack(fill="x")

        RoundedButton(
            upd_btn_box, text="🔄  Periksa Update Server", command=lambda: self.check_for_updates(manual=True),
            bg_color=ACCENT, hover_color=ACCENT_HOVER, height=34, parent_bg=CARD_BG
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        RoundedButton(
            upd_btn_box, text="⬇️  Unduh Exe Terbaru", command=self.download_latest_exe,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=34, width=170, parent_bg=CARD_BG
        ).pack(side="right")

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

    def _clear_local_box(self):
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def clear_logs(self):
        self._clear_local_box()
        url = normalize_url(self.sv_url.get().strip())
        if self.token and url:
            def _do():
                try:
                    api_post(url, "/api/logs/clear", token=self.token)
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    # Status & Auth Session Handlers
    # ─────────────────────────────────────────────────────────────
    def set_status(self, text: str, ok: bool = False):
        self.status_dot.configure(fg=SUCCESS if ok else DANGER)
        self.status_lbl.configure(fg=SUCCESS if ok else TEXT_DIM, text=text)

    def _set_logged_in(self, user: dict):
        self.current_user = user
        self.logout_btn.set_state("normal")
        self.login_btn.set_state("disabled")
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
        self.logout_btn.set_state("disabled")
        self.login_btn.set_state("normal")
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
        self.login_btn.set_state("disabled")
        self.login_btn.set_text("Memverifikasi...")

        def _do():
            try:
                data, code = api_post(url, "/api/auth/login", {"username": user, "password": pw})
                if code == 200 and data.get("token"):
                    self.token = data["token"]
                    save_config(url, user, self.token)
                    self.after(0, lambda: self._set_logged_in(data))
                    self.after(0, lambda: self.log(f"Login sukses! Selamat datang, {data['username']}.", SUCCESS))
                    self.after(0, lambda: self.nav_bar.select(0))
                else:
                    err = data.get("detail", "Username atau password salah")
                    self.after(0, lambda: self.log(f"Login gagal: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Gagal Login", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"Koneksi gagal: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Koneksi Error", f"Tidak dapat terhubung ke {url}:\n{e}"))
            finally:
                self.after(0, lambda: self.login_btn.set_state("normal"))
                self.after(0, lambda: self.login_btn.set_text("🔑  Login ke Server"))

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
        self.nav_bar.select(3)

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
                    tz_str = f"{sch.get('timezone', 'Asia/Jakarta')} ({sch.get('timezone_abbr', 'WIB')}) — Jam Server: {sch.get('current_time', '')}"

                    self.after(0, lambda: self.dash_sch_next.configure(text=f"Jadwal Berikutnya: {next_slot}{rem_str}"))
                    self.after(0, lambda: self.dash_sch_slots.configure(text=f"Jam Tayang Aktif: {slots_str}"))
                    self.after(0, lambda: self.dash_sch_tz.configure(text=f"Timezone Acuan: {tz_str}"))
            except Exception as e:
                self.log(f"Gagal memuat statistik dashboard: {e}", TEXT_DIM)
        threading.Thread(target=_do, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    # On-Demand Publish & Debug Screenshot Modals
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
        dlg.geometry("400x290")
        dlg.minsize(380, 270)
        dlg.configure(bg=BG)
        apply_windows_dark_mode(dlg)
        dlg.transient(self)
        dlg.grab_set()

        _c_border, c_box = create_modern_card(dlg, padx=16, pady=16)
        _c_border.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(c_box, text="🚀 Publikasikan 1 Video Sekarang", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 2))
        tk.Label(c_box, text="Pilih platform tujuan distribusi video Anda:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 10))

        choices = [("ALL", "⭐ Semua Platform Aktif Sekaligus")] + PLATFORMS
        sel_var = tk.StringVar(value="youtube")

        cb = ttk.Combobox(c_box, textvariable=sel_var, values=[c[1] for c in choices], state="readonly", font=("Segoe UI", 9))
        cb.set("YouTube (Shorts/Studio)")
        cb.pack(fill="x", pady=(0, 8))

        tk.Label(
            c_box,
            text="Proses download JIT, render anti-hash & watermark akan langsung berjalan otomatis di antrian worker server.",
            font=("Segoe UI", 8, "italic"), bg=CARD_BG, fg=ACCENT_CYAN, wraplength=330, justify="left"
        ).pack(fill="x", pady=(0, 14))

        btn_box = tk.Frame(c_box, bg=CARD_BG)
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

        RoundedButton(
            btn_box, text="Mulai Posting Sekarang", command=_do_pub,
            bg_color=ACCENT, hover_color=ACCENT_HOVER, height=34, parent_bg=CARD_BG
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        RoundedButton(
            btn_box, text="Batal", command=dlg.destroy,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=34, width=80, parent_bg=CARD_BG
        ).pack(side="right")

    def _trigger_publish(self, target_key: str):
        url = normalize_url(self.sv_url.get().strip())
        self.nav_bar.select(2)

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

        dlg = tk.Toplevel(self)
        dlg.title("Cek Screenshot Debug")
        dlg.geometry("380x230")
        dlg.minsize(360, 210)
        dlg.configure(bg=BG)
        apply_windows_dark_mode(dlg)
        dlg.transient(self)
        dlg.grab_set()

        _c_border, c_box = create_modern_card(dlg, padx=16, pady=16)
        _c_border.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(c_box, text="📸 Screenshot Browser Headless", font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT).pack(anchor="w", pady=(0, 2))
        tk.Label(c_box, text="Pilih platform untuk melihat tangkapan layar browser server:", font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 10))

        cb = ttk.Combobox(c_box, values=[p[1] for p in PLATFORMS], state="readonly", font=("Segoe UI", 9))
        cb.set("YouTube (Shorts/Studio)")
        cb.pack(fill="x", pady=(0, 14))

        btn_box = tk.Frame(c_box, bg=CARD_BG)
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

        RoundedButton(
            btn_box, text="Buka Screenshot", command=_open,
            bg_color=ACCENT, hover_color=ACCENT_HOVER, height=34, parent_bg=CARD_BG
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        RoundedButton(
            btn_box, text="Tutup", command=dlg.destroy,
            bg_color="#1e293b", hover_color="#334155", fg_color=TEXT_MUTED, height=34, width=80, parent_bg=CARD_BG
        ).pack(side="right")

    # ─────────────────────────────────────────────────────────────
    # Cookies & Profile Upload Operations
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
                            browser = p.chromium.launch(
                                channel=ch, headless=False,
                                args=["--disable-blink-features=AutomationControlled"]
                            ) if ch else p.chromium.launch(
                                headless=False,
                                args=["--disable-blink-features=AutomationControlled"]
                            )
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
                                    if item.get("action") == "clear":
                                        self.after(0, self._clear_local_box)
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