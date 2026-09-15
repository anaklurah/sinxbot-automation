"""
OSAP Launcher — Local Windows Client
=====================================
Lightweight local launcher for the OSAP dedicated server.
Build with: pyinstaller --onefile --windowed --name "OSAP-Launcher" --icon osap.ico launcher.py

Features:
- Configure server URL
- Login with username/password  
- Open dashboard in default browser
- Import cookie files for social media platforms
- Local browser login for cookie extraction (Playwright)
- Status/info display
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
# Config file (saved locally)
# ─────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".osap_launcher" / "config.ini"
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

def load_config() -> dict:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH))
    return {
        "server_url": cfg.get("app", "server_url", fallback="http://localhost:8085"),
        "username": cfg.get("app", "username", fallback=""),
        "token": cfg.get("auth", "token", fallback=""),
    }

def save_config(server_url: str, username: str, token: str = ""):
    cfg = configparser.ConfigParser()
    cfg["app"] = {"server_url": server_url, "username": username}
    cfg["auth"] = {"token": token}
    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)


# ─────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────
def api_get(server_url: str, path: str, token: str = "") -> dict:
    headers = {"X-Auth-Token": token} if token else {}
    r = requests.get(f"{server_url.rstrip('/')}{path}", headers=headers, timeout=8)
    return r.json(), r.status_code

def api_post(server_url: str, path: str, data: dict = None, token: str = "", files=None) -> tuple:
    headers = {"X-Auth-Token": token} if token else {}
    if files:
        r = requests.post(f"{server_url.rstrip('/')}{path}", headers=headers, files=files, timeout=30)
    else:
        headers["Content-Type"] = "application/json"
        r = requests.post(f"{server_url.rstrip('/')}{path}", headers=headers, json=data, timeout=8)
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
# Main App
# ─────────────────────────────────────────────
class OSAPLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OSAP Launcher")
        self.geometry("520x680")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.cfg = load_config()
        self.token = self.cfg.get("token", "")
        self.current_user = None
        self._build_ui()
        self._auto_login_if_token()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG, pady=16)
        hdr.pack(fill="x", padx=20)
        tk.Label(hdr, text="OSAP Launcher", font=("Segoe UI", 18, "bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        self.status_dot = tk.Label(hdr, text="●", font=("Segoe UI", 14), bg=BG, fg=DANGER)
        self.status_dot.pack(side="right", padx=(0, 4))
        self.status_lbl = tk.Label(hdr, text="Offline", font=("Segoe UI", 10), bg=BG, fg=TEXT_DIM)
        self.status_lbl.pack(side="right")
        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD_BG, foreground=TEXT_DIM,
                        padding=[16, 8], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("TFrame", background=BG)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_login = ttk.Frame(nb)
        self.tab_cookies = ttk.Frame(nb)
        self.tab_settings = ttk.Frame(nb)
        nb.add(self.tab_login, text="  Login  ")
        nb.add(self.tab_cookies, text="  Cookies Sosmed  ")
        nb.add(self.tab_settings, text="  Settings  ")
        self._build_login_tab()
        self._build_cookies_tab()
        self._build_settings_tab()

        log_frame = tk.Frame(self, bg=CARD_BG, bd=0)
        log_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.log_box = scrolledtext.ScrolledText(log_frame, height=5, font=("Consolas", 9),
                                                  bg="#0d1117", fg=TEXT_DIM,
                                                  insertbackground=TEXT, state="disabled",
                                                  bd=0, relief="flat", wrap="word")
        self.log_box.pack(fill="x", padx=2, pady=2)

    def _build_login_tab(self):
        f = self.tab_login
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Label(outer, text="Server URL", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 4))
        self.sv_url = tk.StringVar(value=self.cfg["server_url"])
        tk.Entry(outer, textvariable=self.sv_url, font=("Segoe UI", 11), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=8).pack(fill="x", pady=(0, 12))
        tk.Label(outer, text="Username", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 4))
        self.sv_user = tk.StringVar(value=self.cfg["username"])
        tk.Entry(outer, textvariable=self.sv_user, font=("Segoe UI", 11), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=8).pack(fill="x", pady=(0, 12))
        tk.Label(outer, text="Password", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 4))
        self.sv_pass = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_pass, show="*", font=("Segoe UI", 11), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=8).pack(fill="x", pady=(0, 16))
        self.login_btn = tk.Button(outer, text="Login ke Server", font=("Segoe UI", 11, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=10, command=self.do_login)
        self.login_btn.pack(fill="x", pady=(0, 8))
        self.dash_btn = tk.Button(outer, text="Buka Dashboard di Browser", font=("Segoe UI", 11, "bold"), bg=SUCCESS, fg="white", relief="flat", cursor="hand2", pady=10, command=self.open_dashboard, state="disabled")
        self.dash_btn.pack(fill="x", pady=(0, 8))
        self.logout_btn = tk.Button(outer, text="Logout", font=("Segoe UI", 9), bg=BORDER, fg=TEXT_DIM, relief="flat", cursor="hand2", pady=6, command=self.do_logout, state="disabled")
        self.logout_btn.pack(fill="x")
        self.user_info_lbl = tk.Label(outer, text="", font=("Segoe UI", 10), bg=BG, fg=SUCCESS)
        self.user_info_lbl.pack(pady=(8, 0))

    def _build_cookies_tab(self):
        f = self.tab_cookies
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)
        tk.Label(outer, text="Upload Cookie File ke Server", font=("Segoe UI", 13, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Export cookies dari browser pakai ekstensi 'Get cookies.txt LOCALLY'\natau 'Cookie-Editor' (JSON), lalu upload di sini.", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM, justify="left").pack(anchor="w", pady=(4, 12))
        tk.Label(outer, text="Platform", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_platform = tk.StringVar(value="youtube")
        plat_frame = tk.Frame(outer, bg=BG)
        plat_frame.pack(fill="x", pady=(4, 12))
        for val, label in PLATFORMS:
            tk.Radiobutton(plat_frame, text=label, variable=self.sv_platform, value=val, bg=BG, fg=TEXT_DIM, selectcolor=ACCENT, activebackground=BG, activeforeground=TEXT, font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        tk.Label(outer, text="Target Key (kosongkan = pakai platform name)", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.sv_target = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_target, font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x", pady=(4, 12))
        tk.Button(outer, text="Pilih & Upload File Cookie", font=("Segoe UI", 11, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=10, command=self.upload_cookie_file).pack(fill="x", pady=(0, 8))
        ttk.Separator(outer).pack(fill="x", pady=12)
        tk.Label(outer, text="Login Manual via Browser Lokal", font=("Segoe UI", 13, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Buka browser lokal untuk login manual, cookies otomatis\ndiekstrak & diupload ke server. Butuh Playwright terinstall lokal.", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM, justify="left").pack(anchor="w", pady=(4, 8))
        tk.Button(outer, text="Login Browser Lokal & Kirim Cookie ke Server", font=("Segoe UI", 11, "bold"), bg="#0f3460", fg="white", relief="flat", cursor="hand2", pady=10, command=self.do_local_browser_login).pack(fill="x")

    def _build_settings_tab(self):
        f = self.tab_settings
        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)
        tk.Label(outer, text="Server Information", font=("Segoe UI", 13, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        self.server_info_text = tk.Text(outer, height=7, font=("Consolas", 9), bg=CARD_BG, fg=TEXT_DIM, relief="flat", bd=6, state="disabled")
        self.server_info_text.pack(fill="x", pady=(8, 12))
        tk.Button(outer, text="Refresh Server Info", font=("Segoe UI", 10, "bold"), bg=CARD_BG, fg=TEXT, relief="flat", cursor="hand2", pady=8, command=self.refresh_server_info).pack(fill="x", pady=(0, 8))
        ttk.Separator(outer).pack(fill="x", pady=12)
        tk.Label(outer, text="Ubah Password", font=("Segoe UI", 13, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="Password Lama", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(8, 2))
        self.sv_old_pass = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_old_pass, show="*", font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x")
        tk.Label(outer, text="Password Baru", font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(8, 2))
        self.sv_new_pass = tk.StringVar()
        tk.Entry(outer, textvariable=self.sv_new_pass, show="*", font=("Segoe UI", 10), bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat", bd=6).pack(fill="x")
        tk.Button(outer, text="Simpan Password Baru", font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white", relief="flat", cursor="hand2", pady=8, command=self.change_password).pack(fill="x", pady=(8, 0))

    def log(self, msg: str, color: str = None):
        self.log_box.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        tag = f"tag_{ts}_{color or 'n'}"
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
        self.user_info_lbl.configure(text=f"Login sebagai: {name}{admin}  (account #{acc})")
        self.set_status(f"Connected ({name})", ok=True)

    def _set_logged_out(self):
        self.current_user = None
        self.token = ""
        self.dash_btn.configure(state="disabled")
        self.logout_btn.configure(state="disabled")
        self.login_btn.configure(state="normal")
        self.user_info_lbl.configure(text="")
        self.set_status("Not logged in", ok=False)

    def do_login(self):
        url = self.sv_url.get().strip()
        user = self.sv_user.get().strip()
        pw = self.sv_pass.get()
        if not url or not user or not pw:
            messagebox.showerror("Error", "Server URL, username, dan password wajib diisi.")
            return
        self.log(f"Login ke {url} sebagai '{user}'...")
        self.login_btn.configure(state="disabled", text="Memverifikasi...")
        def _do():
            try:
                data, code = api_post(url, "/api/auth/login", {"username": user, "password": pw})
                if code == 200 and data.get("token"):
                    self.token = data["token"]
                    save_config(url, user, self.token)
                    self.after(0, lambda: self._set_logged_in(data))
                    self.after(0, lambda: self.log(f"Login berhasil! Selamat datang, {data['username']}", SUCCESS))
                else:
                    err = data.get("detail", "Login gagal")
                    self.after(0, lambda: self.log(f"Login gagal: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Login Gagal", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Koneksi Error", str(e)))
            finally:
                self.after(0, lambda: self.login_btn.configure(state="normal", text="Login ke Server"))
        threading.Thread(target=_do, daemon=True).start()

    def do_logout(self):
        url = self.sv_url.get().strip()
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
        url = self.cfg["server_url"]
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
        url = self.sv_url.get().strip()
        if not url:
            messagebox.showerror("Error", "Server URL belum dikonfigurasi.")
            return
        full_url = f"{url.rstrip('/')}/?token={self.token}" if self.token else url
        webbrowser.open(full_url)
        self.log(f"Membuka dashboard: {url}", TEXT_DIM)

    def upload_cookie_file(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        platform = self.sv_platform.get()
        target_key = self.sv_target.get().strip() or platform
        url = self.sv_url.get().strip()
        file_path = filedialog.askopenfilename(
            title="Pilih file cookie",
            filetypes=[("Cookie files", "*.txt *.json"), ("All files", "*.*")]
        )
        if not file_path:
            return
        self.log(f"Mengupload cookies untuk '{target_key}' dari {Path(file_path).name}...")
        def _do():
            try:
                with open(file_path, "rb") as fh:
                    files = {"file": (Path(file_path).name, fh, "application/octet-stream")}
                    data, code = api_post(url, f"/api/upload-cookies/{target_key}", token=self.token, files=files)
                if code == 200:
                    msg = data.get("message", "Upload berhasil!")
                    self.after(0, lambda: self.log(f"OK: {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Sukses", msg))
                else:
                    err = data.get("detail", "Upload gagal")
                    self.after(0, lambda: self.log(f"Error: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: self.log(f"Error: {e}", DANGER))
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
                    self.after(0, lambda: self.log("Browser terbuka. Login manual, lalu TUTUP browser jika sudah.", TEXT_DIM))
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
                self.after(0, lambda: self.log(f"{len(cookies)} cookies diekstrak. Mengupload...", SUCCESS))
                server_url = self.sv_url.get().strip()
                tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
                _json.dump(cookies, tmp)
                tmp.close()
                with open(tmp.name, "rb") as fh:
                    files = {"file": (f"{target_key}_cookies.json", fh, "application/json")}
                    data, code = api_post(server_url, f"/api/upload-cookies/{target_key}", token=self.token, files=files)
                os.unlink(tmp.name)
                if code == 200:
                    msg = data.get("message", "Cookies berhasil diupload!")
                    self.after(0, lambda: self.log(f"OK: {msg}", SUCCESS))
                    self.after(0, lambda: messagebox.showinfo("Berhasil!", msg))
                else:
                    err = data.get("detail", "Upload cookies gagal")
                    self.after(0, lambda: self.log(f"Error: {err}", DANGER))
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except ImportError:
                self.after(0, lambda: messagebox.showerror("Playwright tidak ditemukan", "Install: pip install playwright && playwright install chromium"))
            except Exception as e:
                self.after(0, lambda: self.log(f"Error: {e}", DANGER))
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def refresh_server_info(self):
        if not self.token:
            messagebox.showinfo("Info", "Login terlebih dahulu.")
            return
        url = self.sv_url.get().strip()
        def _do():
            try:
                data, code = api_get(url, "/api/status", self.token)
                if code == 200:
                    hw = data.get("hardware", {})
                    stats = data.get("queue_stats", {})
                    by_status = stats.get("by_status", {})
                    u = data.get("current_user", {})
                    info = (f"OS      : {hw.get('os','-')}\n"
                            f"Python  : {hw.get('python_version','-')}\n"
                            f"Encoder : {hw.get('encoder','-')}\n"
                            f"User    : {u.get('username','-')} (account #{u.get('account_id','-')})\n"
                            f"Total   : {stats.get('total',0)} videos\n"
                            f"Pending : {by_status.get('pending',0)}  Done: {by_status.get('done',0)}  Failed: {by_status.get('failed',0)}\n")
                    self.after(0, lambda: self._set_server_info(info))
                else:
                    self.after(0, lambda: self._set_server_info(f"Error {code}"))
            except Exception as e:
                self.after(0, lambda: self._set_server_info(f"Error: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def _set_server_info(self, text: str):
        self.server_info_text.configure(state="normal")
        self.server_info_text.delete("1.0", "end")
        self.server_info_text.insert("end", text)
        self.server_info_text.configure(state="disabled")

    def change_password(self):
        if not self.token:
            messagebox.showerror("Error", "Silakan login terlebih dahulu.")
            return
        old_pw = self.sv_old_pass.get()
        new_pw = self.sv_new_pass.get()
        if not old_pw or not new_pw:
            messagebox.showerror("Error", "Isi semua field password.")
            return
        url = self.sv_url.get().strip()
        def _do():
            try:
                data, code = api_post(url, "/api/auth/change-password",
                                       {"current_password": old_pw, "new_password": new_pw}, token=self.token)
                if code == 200:
                    self.after(0, lambda: messagebox.showinfo("Berhasil", data.get("message","Password diubah!")))
                    self.after(0, self._set_logged_out)
                    save_config(url, self.sv_user.get(), "")
                else:
                    err = data.get("detail", "Gagal")
                    self.after(0, lambda: messagebox.showerror("Error", err))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()


if __name__ == "__main__":
    app = OSAPLauncher()
    app.mainloop()
