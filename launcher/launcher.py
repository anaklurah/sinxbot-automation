"""
Sin'X Automation — Client Desktop Karyawan (Enterprise PyWebView Edition)
========================================================================
Next-generation standalone desktop client for Sin'X Automation.
Renders 100% identical Claymorphism 3D theme, Lucide icons, and responsive layout
as the Web Dashboard using Microsoft Edge Chromium WebView2 engine.
"""

from __future__ import annotations

import os
import sys
import json
import time
import ctypes
import tempfile
import webbrowser
import configparser
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

import socket
import struct
import base64
import random
import subprocess
import threading
import urllib.parse
import urllib.request

import webview


# ---------------------------------------------------------------------------
# Native CDP WebSocket client — zero external dependencies
# ---------------------------------------------------------------------------

class NativeCDPClient:
    """
    Minimalist Chrome DevTools Protocol client using only Python stdlib.
    Connects to a running Chrome/Edge browser via WebSocket and can
    extract cookies (Storage.getCookies) without Playwright or Selenium.
    """

    def __init__(self, ws_url: str, timeout: float = 10.0):
        self._ws_url = ws_url
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._msg_id = 1
        self._lock = threading.Lock()

    def connect(self):
        url = self._ws_url.replace("ws://", "")
        host_port, path = url.split("/", 1)
        host, port = host_port.split(":")
        self._host = host
        self._port = int(port)
        self._path = path

        self._sock = socket.create_connection((host, self._port), timeout=self._timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        headers = (
            f"GET /{self._path} HTTP/1.1\r\n"
            f"Host: {host}:{self._port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(headers.encode("utf-8"))
        resp = self._sock.recv(4096)
        if b"101" not in resp:
            raise ConnectionError(f"WebSocket handshake gagal: {resp[:200]}")

    def close(self):
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None

    def _send_frame(self, payload: bytes):
        """Send a masked WebSocket text frame."""
        frame = bytearray([0x81])  # FIN + opcode text
        length = len(payload)
        mask = os.urandom(4)
        if length <= 125:
            frame.append(0x80 | length)
        elif length <= 65535:
            frame.extend([0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack(">Q", length))
        frame.extend(mask)
        frame.extend(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        self._sock.sendall(frame)

    def _recv_frame(self) -> bytes:
        """Read one WebSocket frame and return the unmasked payload."""
        header = self._recv_exact(2)
        b1 = header[1]
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        is_masked = (b1 & 0x80) != 0
        mask = self._recv_exact(4) if is_masked else b""
        data = self._recv_exact(length)
        if is_masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return data

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise EOFError("Koneksi CDP terputus.")
            buf += chunk
        return buf

    def send_command(self, method: str, params: dict | None = None, wait_for_result: bool = True) -> dict:
        with self._lock:
            msg_id = self._msg_id
            self._msg_id += 1
        payload = json.dumps({"id": msg_id, "method": method, "params": params or {}}).encode("utf-8")
        self._send_frame(payload)
        if not wait_for_result:
            return {}
        deadline = time.time() + self._timeout
        while time.time() < deadline:
            self._sock.settimeout(max(0.5, deadline - time.time()))
            try:
                raw = self._recv_frame()
                msg = json.loads(raw.decode("utf-8", errors="ignore"))
                if msg.get("id") == msg_id:
                    return msg.get("result", {})
            except socket.timeout:
                break
            except Exception:
                break
        return {}


def _find_edge_or_chrome() -> str | None:
    """Returns the path to Edge or Chrome executable on the current machine."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # fallback: try PATH
    for name in ("msedge", "msedge.exe", "chrome", "chrome.exe"):
        import shutil
        p = shutil.which(name)
        if p:
            return p
    return None


def _get_cdp_page(port: int, timeout: float = 10.0) -> dict | None:
    """Polls the CDP /json/list endpoint and returns first page entry."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as resp:
                pages = json.loads(resp.read().decode("utf-8"))
                pages = [p for p in pages if p.get("type") == "page"]
                if pages:
                    return pages[0]
        except Exception:
            pass
        time.sleep(0.4)
    return None

APP_VERSION = "1.3.0"

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

CONFIG_DIR = Path.home() / ".osap_launcher"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.ini"


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


def load_config() -> dict:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH), encoding="utf-8")
    raw_url = cfg.get("app", "server_url", fallback="https://auto.kntl.cc")
    return {
        "server_url": normalize_url(raw_url),
        "username": cfg.get("app", "username", fallback=""),
        "token": cfg.get("auth", "token", fallback=""),
        "proxy_enabled": cfg.getboolean("proxy", "enabled", fallback=False),
        "proxy_url": cfg.get("proxy", "url", fallback=""),
    }


def save_config(server_url: str, username: str, token: str = ""):
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH), encoding="utf-8")
    if "app" not in cfg:
        cfg["app"] = {}
    cfg["app"]["server_url"] = normalize_url(server_url)
    cfg["app"]["username"] = username
    if "auth" not in cfg:
        cfg["auth"] = {}
    cfg["auth"]["token"] = token
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)


def save_proxy_config(enabled: bool, proxy_url: str):
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH), encoding="utf-8")
    if "proxy" not in cfg:
        cfg["proxy"] = {}
    cfg["proxy"]["enabled"] = "true" if enabled else "false"
    cfg["proxy"]["url"] = proxy_url.strip()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)


def format_playwright_proxy(proxy_url: str | None) -> dict | None:
    """Format proxy URL into Playwright-compatible dictionary."""
    if not proxy_url:
        return None
    try:
        import urllib.parse
        parsed = urllib.parse.urlsplit(proxy_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname
        if not host:
            return None
        port = parsed.port
        server = f"{scheme}://{host}"
        if port:
            server += f":{port}"
        p_dict = {"server": server}
        if parsed.username:
            p_dict["username"] = urllib.parse.unquote(parsed.username)
        if parsed.password:
            p_dict["password"] = urllib.parse.unquote(parsed.password)
        return p_dict
    except Exception:
        return {"server": proxy_url}


def api_get(server_url: str, path: str, token: str = "", timeout: int = 15) -> tuple[dict, int]:
    if requests is None:
        raise RuntimeError("Modul 'requests' belum terinstall.")
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    r = requests.get(f"{base}{path}", headers=headers, timeout=timeout)
    try:
        return r.json(), r.status_code
    except Exception:
        return {"detail": r.text}, r.status_code


def api_post(server_url: str, path: str, data: dict = None, token: str = "", files=None, timeout: int = 30) -> tuple[dict, int]:
    if requests is None:
        raise RuntimeError("Modul 'requests' belum terinstall.")
    base = normalize_url(server_url)
    headers = {"X-Auth-Token": token} if token else {}
    if files:
        r = requests.post(f"{base}{path}", headers=headers, files=files, timeout=60)
    else:
        headers["Content-Type"] = "application/json"
        r = requests.post(f"{base}{path}", headers=headers, json=data or {}, timeout=timeout)
    try:
        return r.json(), r.status_code
    except Exception:
        return {"detail": r.text}, r.status_code


class LauncherApi:
    """
    Python bridge exposed to JavaScript inside WebView2 via window.pywebview.api.
    NOTE: All internal fields MUST begin with an underscore ('_') so pywebview's
    get_functions() does not recursively introspect them.
    """

    def __init__(self):
        self._window: webview.Window | None = None
        self._cfg = load_config()

    def set_window(self, window: webview.Window):
        self._window = window

    def get_initial_state(self) -> dict:
        """Returns the saved server configuration and checks token validity."""
        self._cfg = load_config()
        server_url = self._cfg.get("server_url", "https://auto.kntl.cc")
        username = self._cfg.get("username", "")
        token = self._cfg.get("token", "")

        is_auth = False
        if server_url and token:
            try:
                data, code = api_get(server_url, "/api/status", token=token, timeout=3)
                if code == 200:
                    is_auth = True
            except Exception:
                is_auth = False

        return {
            "server_url": server_url,
            "username": username,
            "token": token if is_auth else "",
            "is_authenticated": is_auth,
            "app_version": APP_VERSION,
            "proxy_enabled": self._cfg.get("proxy_enabled", False),
            "proxy_url": self._cfg.get("proxy_url", ""),
        }

    def login(self, server_url: str, username: str, password: str) -> dict:
        """Authenticates user with OSAP server."""
        server_url = normalize_url(server_url)
        try:
            data, code = api_post(
                server_url,
                "/api/auth/login",
                data={"username": username, "password": password},
                timeout=15
            )
            if code == 200:
                token = data.get("token") or data.get("access_token", "")
                if token:
                    save_config(server_url, username, token)
                    self._cfg = load_config()
                    return {"success": True, "token": token, "message": "Login berhasil!"}
                else:
                    return {"success": False, "error": "Server tidak mengembalikan token autentikasi."}
            else:
                err_msg = data.get("detail") or data.get("message") or f"Login gagal (HTTP {code})"
                return {"success": False, "error": err_msg}
        except Exception as e:
            return {"success": False, "error": f"Gagal menghubungi server: {str(e)}"}

    def logout(self) -> dict:
        """Clears local session token."""
        save_config(self._cfg.get("server_url", "https://auto.kntl.cc"), self._cfg.get("username", ""), "")
        self._cfg = load_config()
        return {"success": True}

    def open_web_dashboard(self) -> dict:
        """Opens server web dashboard in default browser with active auth token."""
        url = self._cfg.get("server_url", "https://auto.kntl.cc").rstrip("/")
        token = self._cfg.get("token", "")
        if not url:
            url = "https://auto.kntl.cc"
        target_url = f"{url}/?token={token}" if token else url
        webbrowser.open(target_url)
        return {"success": True, "url": target_url}

    def save_server_url(self, server_url: str) -> dict:
        """Saves updated server URL."""
        url = normalize_url(server_url)
        save_config(url, self._cfg.get("username", ""), self._cfg.get("token", ""))
        self._cfg = load_config()
        return {"success": True, "server_url": url}

    def save_proxy(self, enabled: bool, proxy_url: str) -> dict:
        """Saves employee personal proxy configuration."""
        save_proxy_config(enabled, proxy_url)
        self._cfg = load_config()
        return {"success": True, "message": "Pengaturan proxy pribadi berhasil disimpan!"}

    def test_proxy(self, proxy_url: str) -> dict:
        """Tests connectivity and latency to external IP echo service via specified proxy."""
        proxy_url = proxy_url.strip()
        if not proxy_url:
            return {"success": False, "error": "URL proxy tidak boleh kosong."}

        try:
            proxies = {"http": proxy_url, "https": proxy_url}
            start_t = time.time()
            r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)
            latency = int((time.time() - start_t) * 1000)
            if r.status_code == 200:
                ip = r.json().get("ip", "Terdeteksi")
                return {"success": True, "ip": ip, "latency": latency, "message": f"Proxy aktif! IP: {ip} ({latency}ms)"}
            return {"success": False, "error": f"Proxy merespon HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": f"Gagal terhubung ke proxy: {str(e)}"}

    def get_telegram_settings(self) -> dict:
        """Fetches personal Telegram settings from server."""
        token = self._cfg.get("token", "")
        url = self._cfg.get("server_url", "https://auto.kntl.cc")
        if not token:
            return {"success": False, "error": "Belum login"}
        try:
            data, code = api_get(url, "/api/user/settings", token=token, timeout=10)
            if code == 200:
                s = data.get("settings", {})
                return {
                    "success": True,
                    "enabled": bool(s.get("telegram_enabled", False)),
                    "bot_token": s.get("telegram_bot_token", "") or "",
                    "chat_id": str(s.get("telegram_chat_id", "") or ""),
                }
            return {"success": False, "error": data.get("detail", f"HTTP {code}")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_telegram_settings(self, enabled: bool, bot_token: str, chat_id: str) -> dict:
        """Saves personal Telegram settings to server."""
        token = self._cfg.get("token", "")
        url = self._cfg.get("server_url", "https://auto.kntl.cc")
        if not token:
            return {"success": False, "error": "Belum login"}
        try:
            data, code = api_post(
                url,
                "/api/user/settings",
                token=token,
                data={
                    "telegram_enabled": bool(enabled),
                    "telegram_bot_token": bot_token.strip(),
                    "telegram_chat_id": str(chat_id).strip(),
                },
                timeout=10,
            )
            if code == 200 and data.get("success"):
                return {"success": True, "message": "Pengaturan bot Telegram pribadi berhasil disimpan!"}
            return {"success": False, "error": data.get("detail", data.get("message", f"HTTP {code}"))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def test_telegram_connection(self, bot_token: str, chat_id: str) -> dict:
        """Tests personal Telegram bot connectivity via server."""
        token = self._cfg.get("token", "")
        url = self._cfg.get("server_url", "https://auto.kntl.cc")
        if not token:
            return {"success": False, "error": "Belum login"}
        try:
            data, code = api_post(
                url,
                "/api/user/telegram/test",
                token=token,
                data={
                    "bot_token": bot_token.strip(),
                    "chat_id": str(chat_id).strip(),
                },
                timeout=15,
            )
            if code == 200 and data.get("success"):
                return {"success": True, "message": data.get("message", "Test Telegram berhasil!")}
            return {"success": False, "error": data.get("detail", data.get("message", f"HTTP {code}"))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_dashboard_stats(self) -> dict:
        """Fetches status and queue statistics from the server."""
        url = self._cfg.get("server_url", "")
        token = self._cfg.get("token", "")
        if not url or not token:
            return {"error": "Sesi tidak aktif"}
        try:
            data, code = api_get(url, "/api/status", token=token, timeout=10)
            if code == 200:
                return data
            return {"error": data.get("detail", f"HTTP {code}")}
        except Exception as e:
            return {"error": str(e)}

    def trigger_publish(self, target_key: str) -> dict:
        """Triggers on-demand video publication."""
        url = self._cfg.get("server_url", "")
        token = self._cfg.get("token", "")
        if not url or not token:
            return {"success": False, "error": "Silakan login terlebih dahulu."}

        try:
            if target_key == "ALL":
                data, code = api_post(url, "/api/pipeline/publish-all", token=token)
            else:
                data, code = api_post(url, f"/api/publish/{target_key}", token=token)

            if code == 200:
                return {"success": True, "message": data.get("message", "Publikasi dimulai!")}
            else:
                return {"success": False, "error": data.get("detail", "Gagal memicu publikasi")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_debug_screenshot(self, platform: str) -> dict:
        """Opens server browser debug screenshot in default web browser."""
        url = self._cfg.get("server_url", "")
        token = self._cfg.get("token", "")
        if not url or not token:
            return {"success": False, "error": "Silakan login terlebih dahulu."}

        full_url = f"{url}/api/debug/screenshot/{platform}?token={token}&t={int(time.time()*1000)}"
        webbrowser.open(full_url)
        return {"success": True}

    def clear_logs(self) -> dict:
        """Truncates server log file and broadcasts clear event."""
        url = self._cfg.get("server_url", "")
        token = self._cfg.get("token", "")
        if not url or not token:
            return {"success": False, "error": "Silakan login terlebih dahulu."}

        try:
            data, code = api_post(url, "/api/logs/clear", token=token)
            if code == 200:
                return {"success": True, "message": "Log server berhasil dibersihkan!"}
            return {"success": False, "error": data.get("detail", "Gagal membersihkan log.")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pick_and_upload_cookie(self, platform: str, target_key: str) -> dict:
        """Opens Windows file picker for cookie file (.json / .txt) and uploads to server."""
        if not self._window:
            return {"success": False, "error": "Window tidak tersedia"}

        url = self._cfg.get("server_url", "")
        token = self._cfg.get("token", "")
        if not url or not token:
            return {"success": False, "error": "Silakan login terlebih dahulu."}

        target = target_key.strip() or platform.strip() or "youtube"

        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=('Cookie Files (*.json;*.txt)', 'All files (*.*)')
        )
        if not result:
            return {"cancelled": True}

        file_path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            path_obj = Path(file_path)
            with open(path_obj, "rb") as fh:
                files = {"file": (path_obj.name, fh, "application/octet-stream")}
                data, code = api_post(url, f"/api/upload-cookies/{target}", token=token, files=files)

            if code == 200:
                return {"success": True, "message": data.get("message", f"Cookies '{target}' berhasil diunggah!")}
            return {"success": False, "error": data.get("detail", "Upload cookie gagal.")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pick_and_upload_zip(self, platform: str, target_key: str) -> dict:
        """Opens Windows file picker for profile archive (.zip) and uploads to server."""
        if not self._window:
            return {"success": False, "error": "Window tidak tersedia"}

        url = self._cfg.get("server_url", "")
        token = self._cfg.get("token", "")
        if not url or not token:
            return {"success": False, "error": "Silakan login terlebih dahulu."}

        target = target_key.strip() or platform.strip() or "youtube"

        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=('ZIP Archives (*.zip)', 'All files (*.*)')
        )
        if not result:
            return {"cancelled": True}

        file_path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            path_obj = Path(file_path)
            with open(path_obj, "rb") as fh:
                files = {"file": (path_obj.name, fh, "application/zip")}
                data, code = api_post(url, f"/api/upload-profile/{target}", token=token, files=files)

            if code == 200:
                return {"success": True, "message": data.get("message", f"Profil browser '{target}' aktif di server!")}
            return {"success": False, "error": data.get("detail", "Upload profil zip gagal.")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def launch_local_browser(self, platform: str, target_key: str) -> dict:
        """
        Opens Edge/Chrome natively with CDP remote-debugging, waits for the user
        to complete login, then extracts all cookies via CDP Storage.getCookies and
        uploads them to the server. Zero third-party dependencies.
        """
        url = self._cfg.get("server_url", "")
        token = self._cfg.get("token", "")
        if not url or not token:
            return {"success": False, "error": "Silakan login terlebih dahulu."}

        browser_path = _find_edge_or_chrome()
        if not browser_path:
            return {
                "success": False,
                "error": (
                    "Browser tidak ditemukan. Pastikan Microsoft Edge atau Google Chrome "
                    "terinstall, atau gunakan opsi 'Upload File Cookie' / 'Upload Profil (.zip)'."
                )
            }

        target = target_key.strip() or platform.strip() or "youtube"
        url_map = {
            "youtube":      "https://accounts.google.com",
            "instagram":    "https://www.instagram.com/accounts/login/",
            "tiktok":       "https://www.tiktok.com/login",
            "facebook":     "https://www.facebook.com/login",
            "twitter":      "https://twitter.com/i/flow/login",
            "twitter_nsfw": "https://twitter.com/i/flow/login",
            "upscrolled":   "https://upscrolled.com/login",
            "febspot":      "https://www.febspot.com/login",
        }
        login_url = url_map.get(platform, f"https://{platform}.com")

        # Pick a random free port for remote debugging
        dbg_port = random.randint(9222, 9399)
        temp_dir = tempfile.mkdtemp(prefix="sinx_browser_")

        cmd = [
            browser_path,
            f"--remote-debugging-port={dbg_port}",
            f"--user-data-dir={temp_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            f"--window-size=1280,800",
        ]

        # Inject proxy if configured
        if self._cfg.get("proxy_enabled") and self._cfg.get("proxy_url"):
            p_url = self._cfg.get("proxy_url", "").strip()
            if p_url:
                cmd.append(f"--proxy-server={p_url}")

        cmd.append(login_url)

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return {"success": False, "error": f"Gagal membuka browser: {e}"}

        try:
            # Wait for CDP endpoint to be ready
            page_info = _get_cdp_page(dbg_port, timeout=15.0)
            if not page_info:
                proc.terminate()
                return {"success": False, "error": "Browser gagal start (CDP endpoint tidak tersedia)."}

            # Poll cookies every 3 seconds while browser is alive
            # Once the user closes the browser window, we capture all cookies.
            last_cookies: list = []
            while True:
                if proc.poll() is not None:
                    # Browser was closed by user
                    break

                try:
                    page_info = _get_cdp_page(dbg_port, timeout=3.0)
                    if page_info and page_info.get("webSocketDebuggerUrl"):
                        cdp = NativeCDPClient(page_info["webSocketDebuggerUrl"], timeout=5.0)
                        cdp.connect()
                        result = cdp.send_command("Storage.getCookies")
                        cdp.close()
                        cookies = result.get("cookies", [])
                        if cookies:
                            last_cookies = cookies
                except Exception:
                    pass

                time.sleep(3)

            # Clean up temp dir (best effort)
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

            if not last_cookies:
                return {"success": False, "error": "Tidak ada cookies yang berhasil diekstrak. Pastikan Anda sudah login sebelum menutup browser."}

            # Upload cookies to server
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
            json.dump(last_cookies, tmp)
            tmp.close()

            with open(tmp.name, "rb") as fh:
                files = {"file": (f"{target}_cookies.json", fh, "application/json")}
                data, code = api_post(url, f"/api/upload-cookies/{target}", token=token, files=files)
            os.unlink(tmp.name)

            if code == 200:
                return {"success": True, "message": f"{len(last_cookies)} cookies berhasil diunggah! Target '{target}' siap digunakan."}
            return {"success": False, "error": data.get("detail", "Gagal mengunggah cookies ke server.")}

        except Exception as e:
            try:
                proc.terminate()
            except Exception:
                pass
            return {"success": False, "error": f"Error browser login: {str(e)}"}


    def check_updates(self, manual: bool = False) -> dict:
        """Checks for newer version on the server."""
        url = self._cfg.get("server_url", "")
        if not url:
            return {"has_update": False, "error": "Server URL kosong"}

        try:
            data, code = api_get(url, "/api/launcher/version", timeout=8)
            if code == 200 and data.get("version"):
                remote_ver = str(data["version"]).strip()
                current_ver = APP_VERSION.strip()

                def _parse_v(v_str):
                    clean = v_str.lstrip("vV")
                    return [int(x) for x in clean.split(".") if x.isdigit()]

                try:
                    is_newer = _parse_v(remote_ver) > _parse_v(current_ver)
                except Exception:
                    is_newer = (remote_ver != current_ver)

                return {
                    "has_update": is_newer,
                    "remote_version": remote_ver,
                    "current_version": current_ver,
                    "changelog": data.get("changelog", "Pembaruan stabilitas dan performa sistem.")
                }
            return {"has_update": False}
        except Exception as e:
            return {"has_update": False, "error": str(e)}

    def download_latest_exe(self) -> dict:
        """Opens download URL in external browser."""
        url = self._cfg.get("server_url", "")
        if url:
            webbrowser.open(f"{url}/api/launcher/download")
        return {"success": True}


def main():
    api = LauncherApi()

    # Determine base path (standalone EXE vs development script)
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent

    html_path = base_dir / "ui" / "index.html"
    icon_path = base_dir / "icon.ico"

    # Create PyWebView window
    window = webview.create_window(
        title="Sin'X Automation — Desktop Client",
        url=str(html_path.resolve()),
        js_api=api,
        width=980,
        height=720,
        min_size=(880, 620),
        text_select=True
    )
    api.set_window(window)

    icon_arg = str(icon_path.resolve()) if icon_path.exists() else None
    webview.start(gui="edgechromium", debug=False, icon=icon_arg)


if __name__ == "__main__":
    main()
