# OmniShorts Auto-Publisher (OSAP) v1.0.0

> **Sistem Otomasi Redistribution YouTube Shorts End-to-End** — Download, Modifikasi Anti-Fingerprint FFmpeg, AI Caption Generator, dan Auto-Publish ke 8 Platform Media Sosial dengan Web Dashboard UI & Docker Support.

```
YouTube Shorts URLs ──► Ingestion & Queue ──► Downloader (yt-dlp) ──► FFmpeg Anti-Hash Filter ──► DeepSeek AI ──► Multi-Platform Publisher (Playwright)
```

---

## 📑 Daftar Isi

- [Fitur Utama](#-fitur-utama)
- [Arsitektur Sistem](#-arsitektur-sistem)
- [Persyaratan Sistem](#-persyaratan-sistem)
- [Panduan Instalasi Quick Start](#-panduan-instalasi-quick-start)
- [Menjalankan Web Dashboard UI](#-menjalankan-web-dashboard-ui)
- [Menjalankan dengan Docker & Docker Compose](#-menjalankan-dengan-docker--docker-compose)
- [Panduan Autentikasi Platform (Cookies & Profiles)](#-panduan-autentikasi-platform-cookies--profiles)
- [Referensi Perintah CLI (`manage.py`)](#-referensi-perintah-cli-managepy)
- [Struktur Proyek](#-struktur-proyek)
- [Pengaturan Linux VPS (Headless & Xvfb)](#-pengaturan-linux-vps-headless--xvfb)
- [Lisensi & Ketentuan](#-lisensi--ketentuan)

---

## 🚀 Fitur Utama

- 📊 **Web Dashboard UI (Admin Panel):** Antarmuka web single-page (FastAPI + Vanilla JS/CSS) dengan tema dark glassmorphism modern tanpa ketergantungan Node.js/npm.
- 📥 **Automated Ingestion:** Membaca berkas URL (`.txt` / `.csv`), melakukan deduplikasi otomatis, dan menyimpan pekerjaan ke database queue SQLite WAL.
- ⬇️ **High-speed Downloader:** Pemroses unduhan paralel menggunakan `yt-dlp` hingga kualitas 1080p beserta ekstraksi metadata JSON.
- 🎞️ **FFmpeg Anti-Perceptual Hash:** Filter pemrosesan video single-pass untuk mengubah fingerprint digital (Zoom Crop, Speed 1.05x, Pitch-correct Audio, Color Grading, dan Micro-Noise Injection).
- 🤖 **DeepSeek AI Captions:** Generasi otomatis judul viral, deskripsi, dan tren hashtag menggunakan API DeepSeek AI.
- 📲 **8 Platform Target:** Support YouTube Shorts, Facebook Reels, Instagram Reels, Twitter/X, Twitter 18+ (NSFW), TikTok, Upscrolled, dan Febspot.
- 🛡️ **Bot Detection Evasion:** Integrasi `playwright-stealth`, pengetikan manusia dengan random jitter delay, serta curved mouse movement.
- ⚡ **Akselerasi GPU:** Otomatis mendeteksi GPU NVIDIA (`h264_nvenc`) dan beralih ke `libx264` jika berjalan di CPU.
- ⏱️ **Rate Limiting & Anti-Ban:** Pembatasan jumlah post per jam per platform untuk menjaga keamanan akun.
- 🐳 **Docker Ready:** Siap dijalankan dalam container Docker & Docker Compose dengan dukungan Playwright pre-installed.

---

## 🏗️ Arsitektur Sistem

```
[Web Dashboard / CLI] ──► [SQLite Queue Database (WAL Mode)]
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
1. DownloadWorker         2. VideoProcessor         3. PublisherOrchestrator
(yt-dlp multi-thread)     (FFmpeg NVENC/libx264)      (Playwright Async × 8)
```

---

## 💻 Persyaratan Sistem

- **Python:** 3.11 atau lebih baru (direkomendasikan Python 3.11 / 3.12 / 3.14).
- **FFmpeg:** Terinstal di PATH sistem.
- **Playwright Chromium:** Browser engine untuk otomasi posting.
- **NVIDIA GPU:** (Opsional) Untuk enkoding `h264_nvenc` super cepat.
- **DeepSeek API Key:** Kunci API untuk captioning otomatis.

---

## 🛠️ Panduan Instalasi Quick Start

### 1. Clone & Masuk ke Direktori

```bash
git clone https://github.com/your-repo/sonx-bot.git
cd sonx-bot
```

### 2. Install Dependensi Python & Playwright

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Konfigurasi Berkas Lingkungan (`.env`)

Salin berkas contoh `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Buka `.env` lalu masukkan API Key DeepSeek Anda:

```env
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
DEEPSEEK_MODEL=deepseek-chat
```

---

## 🖥️ Menjalankan Web Dashboard UI

Anda dapat mengelola seluruh aktivitas bot melalui antarmuka Web Dashboard.

Jalankan perintah:

```bash
python manage.py web
```

Buka browser Anda di alamat:
👉 **`http://localhost:8080`**

### Tab pada Web Dashboard:
1. **Dashboard:** Ringkasan statistik queue, status hardware GPU, dan tabel daftar antrean video.
2. **URL Manager:** Form input untuk memasukkan daftar URL YouTube Shorts sekaligus.
3. **Configuration:** Mengatur Rate Limit, Filter FFmpeg Anti-Hash, dan DeepSeek AI secara visual.
4. **Platforms:** Menyalakan/mematikan platform target serta memeriksa status cookie/auth.
5. **Live Logs:** Streaming log aktivitas sistem secara real-time via Server-Sent Events (SSE).

---

## 🐳 Menjalankan dengan Docker & Docker Compose

OSAP sudah dilengkapi berkas `Dockerfile` dan `docker-compose.yml` berbasis Playwright Official Image yang telah menyertakan FFmpeg dan Chromium.

### 1. Build dan Jalankan Container:

```bash
docker-compose up -d --build
```

### 2. Akses Web UI:

Buka **`http://localhost:8080`** di browser.

### 3. Melihat Logs Docker:

```bash
docker-compose logs -f
```

### 4. Menghentikan Container:

```bash
docker-compose down
```

---

## 🔑 Panduan Autentikasi Platform (Cookies & Profiles)

Sebelum melakukan auto-posting, hubungkan akun media sosial Anda terlebih dahulu:

### 1. Persistent Chrome Profile (YouTube, Febspot)
Metode ini menyimpan sesi login Google secara permanen di profil browser.

Jalankan perintah login:
```bash
python manage.py setup-auth --platform youtube
python manage.py setup-auth --platform febspot
```
Browser Chromium akan terbuka. Silakan lakukan login manual hingga masuk ke Studio/Dashboard, kemudian tutup jendela browser.

### 2. Storage State / Netscape Cookies (TikTok, Instagram, Facebook, Twitter, Upscrolled)

Jalankan login otomatis Playwright:
```bash
python manage.py setup-auth --platform tiktok
python manage.py setup-auth --platform instagram
python manage.py setup-auth --platform facebook
python manage.py setup-auth --platform twitter
```
Atau simpan file cookie dari browser Anda ke folder `assets/profiles/`:
- Format Netscape: `assets/profiles/tiktok_cookies.txt`
- Format JSON: `assets/profiles/tiktok_cookies.json`

OSAP akan mendeteksi format cookie secara otomatis.

---

## 📋 Referensi Perintah CLI (`manage.py`)

Selain Web UI, Anda juga bisa mengendalikan OSAP via terminal CLI:

| Perintah CLI | Deskripsi |
|---|---|
| `python manage.py web` | Menjalankan server Web Dashboard UI (`http://0.0.0.0:8080`) |
| `python manage.py run-all` | Menjalankan seluruh pipeline (Downloader, Renderer, Publisher) secara paralel |
| `python manage.py ingest --source FILE` | Membaca URL dari file teks/CSV dan memasukkan ke antrean DB |
| `python manage.py download [--workers N]` | Menjalankan worker pengunduh video (default: 2 worker) |
| `python manage.py render` | Menjalankan worker FFmpeg untuk memodifikasi video |
| `python manage.py publish [--platform NAME]` | Menjalankan worker upload ke semua/satu platform |
| `python manage.py setup-auth --platform NAME` | Membuka browser untuk login manual ke platform |
| `python manage.py cleanup [--dry-run]` | Menghapus berkas mp4 mentah/render untuk menghemat ruang disk |
| `python manage.py status` | Menampilkan tabel statistik antrean database |
| `python manage.py reset-stuck` | Meriset pekerjaan yang terhenti >30 menit akibat kendala jaringan |
| `python manage.py info` | Menampilkan deteksi GPU, OS, versi Python, dan lokasi folder |

---

## 📁 Struktur Proyek

```
sonx-bot/
├── manage.py              # CLI entry point (11 perintah)
├── config.yaml            # Parameter konfigurasi utama
├── .env                   # API Keys & variabel lingkungan
├── Dockerfile             # Container definition (Playwright base)
├── docker-compose.yml     # Orchestration file
├── requirements.txt       # Dependensi Python
│
├── assets/
│   ├── urls.txt           # File daftar URL YouTube Shorts
│   └── profiles/          # Folder tempat penyimpanan sesi login/cookies
│
├── downloads/
│   ├── raw/               # File mp4 mentah hasil unduhan
│   ├── rendered/          # File mp4 hasil render FFmpeg
│   └── meta/              # File metadata JSON
│
├── osap/                  # Core Package Python OSAP
│   ├── config.py          # Dataclass singleton pengelola konfigurasi
│   ├── db/                # Modul SQLite schema & job queue
│   ├── modules/
│   │   ├── ingestion.py   # Downloader (yt-dlp) & URL Parser
│   │   ├── processor.py   # FFmpeg Filter Engine
│   │   ├── caption_ai.py  # DeepSeek AI Caption Generator
│   │   ├── cleanup.py     # Pembersih ruang disk
│   │   └── publisher/     # Script publisher untuk 8 platform
│   └── utils/             # Deteksi hardware GPU, delay manusia, & logging
│
└── web/                   # Web Dashboard UI Package
    ├── server.py          # Server API FastAPI + SSE log streamer
    └── static/
        └── index.html     # Single Page Application (Dark Glassmorphism)
```

---

## 🐧 Pengaturan Linux VPS (Headless & Xvfb)

Saat dijalankan di Linux VPS tanpa antarmuka grafis (GUI), gunakan `Xvfb` (Virtual Framebuffer) agar browser Playwright dapat berjalan secara aman dari deteksi bot:

```bash
# Install Xvfb di Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y xvfb

# Jalankan OSAP di dalam server virtual Xvfb
xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24" \
    python manage.py run-all
```

---

## ⚠️ Lisensi & Ketentuan

Aplikasi ini dikembangkan untuk penggunaan pribadi dan edukasi otomasi konten. Pengunggahan konten secara otomatis harus mematuhi Syarat & Ketentuan masing-masing platform media sosial target.
