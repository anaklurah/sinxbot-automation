"""
OSAP Configuration Module
==========================
Loads configuration from ``config.yaml`` (project root) and ``.env`` (python-dotenv).
Exposes a single :class:`Config` dataclass singleton via :func:`get_config`.

Usage::

    from osap.config import get_config

    cfg = get_config()
    cfg.ensure_dirs()
    print(cfg.enabled_platforms)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: All supported platform keys in canonical order.
PLATFORMS: list[str] = [
    "youtube",
    "facebook",
    "instagram",
    "twitter",
    "twitter_nsfw",
    "tiktok",
    "upscrolled",
    "febspot",
]

#: Default AI caption system prompt used when not overridden in config.yaml.
_DEFAULT_CAPTION_SYSTEM_PROMPT: str = (
    "You are a creative social-media copywriter specialising in short-form video content. "
    "Given a video title and description, produce an engaging caption with relevant hashtags. "
    "Return a JSON object with keys: title (str), description (str), tags (list[str])."
)


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """
    Centralised configuration for the OmniShorts Auto-Publisher.

    All attributes are populated once at startup from environment variables
    (highest priority) and ``config.yaml`` (lower priority).  Use
    :func:`get_config` to obtain the process-wide singleton instead of
    constructing this class directly.
    """

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    #: Filesystem path to the SQLite database file.
    DB_PATH: str = "./osap.db"

    #: Root directory for all downloaded files (raw + rendered + meta).
    DOWNLOAD_DIR: Path = field(default_factory=lambda: Path("./downloads"))

    #: Directory for static assets (overlays, fonts, watermarks…).
    ASSETS_DIR: Path = field(default_factory=lambda: Path("./assets"))

    #: Directory for per-platform browser profiles (Playwright persistent contexts).
    PROFILES_DIR: Path = field(default_factory=lambda: Path("./assets/profiles"))

    # ------------------------------------------------------------------
    # AI / DeepSeek
    # ------------------------------------------------------------------

    #: DeepSeek API key.  Required when CAPTION_MODE == "ai".
    DEEPSEEK_API_KEY: str = ""

    #: DeepSeek model identifier.
    DEEPSEEK_MODEL: str = "deepseek-chat"

    #: Optional proxy URL (e.g. socks5://localhost:1080)
    PROXY_URL: Optional[str] = None

    #: Caption generation mode.  Currently always "ai" (DeepSeek).
    CAPTION_MODE: str = "ai"

    #: System prompt sent to the AI for caption generation.
    CAPTION_SYSTEM_PROMPT: str = _DEFAULT_CAPTION_SYSTEM_PROMPT

    # ------------------------------------------------------------------
    # Platform toggles
    # ------------------------------------------------------------------

    PLATFORM_YOUTUBE: bool = True
    PLATFORM_FACEBOOK: bool = True
    PLATFORM_INSTAGRAM: bool = True
    PLATFORM_TWITTER: bool = True
    PLATFORM_TWITTER_NSF: bool = False  # NSFW Twitter account (opt-in)
    PLATFORM_TIKTOK: bool = True
    PLATFORM_UPSCROLLED: bool = False
    PLATFORM_FEBSPOT: bool = False

    # ------------------------------------------------------------------
    # Rate limits
    # ------------------------------------------------------------------

    #: Maximum number of posts per hour per platform.
    POSTS_PER_HOUR: int = 2

    #: Seconds to wait between consecutive platform uploads for the same video.
    DELAY_BETWEEN_PLATFORMS: int = 30

    #: Number of parallel downloader workers.
    WORKERS_DOWNLOADER: int = 2

    #: Run Playwright browser in headless mode (True) or visible GUI mode (False).
    HEADLESS: bool = False

    # ------------------------------------------------------------------
    # FFmpeg processing parameters
    # ------------------------------------------------------------------

    #: Zoom-in factor applied via ``zoompan`` filter (1.0 = no zoom).
    FFMPEG_ZOOM: float = 1.04

    #: Playback speed multiplier (1.0 = original speed).
    FFMPEG_SPEED: float = 1.0

    #: Noise level added for subtle grain effect (0 = off).
    FFMPEG_NOISE: int = 2

    #: Contrast adjustment passed to ``eq`` filter (1.0 = neutral).
    FFMPEG_CONTRAST: float = 1.05

    #: Saturation adjustment passed to ``eq`` filter (1.0 = neutral).
    FFMPEG_SATURATION: float = 1.1

    # ------------------------------------------------------------------
    # Derived / computed properties
    # ------------------------------------------------------------------

    @property
    def enabled_platforms(self) -> list[str]:
        """
        Return the list of platform names that are currently enabled.

        The mapping from platform key to :class:`Config` attribute is::

            youtube      -> PLATFORM_YOUTUBE
            facebook     -> PLATFORM_FACEBOOK
            instagram    -> PLATFORM_INSTAGRAM
            twitter      -> PLATFORM_TWITTER
            twitter_nsfw -> PLATFORM_TWITTER_NSF
            tiktok       -> PLATFORM_TIKTOK
            upscrolled   -> PLATFORM_UPSCROLLED
            febspot      -> PLATFORM_FEBSPOT
        """
        toggle_map: dict[str, bool] = {
            "youtube": self.PLATFORM_YOUTUBE,
            "facebook": self.PLATFORM_FACEBOOK,
            "instagram": self.PLATFORM_INSTAGRAM,
            "twitter": self.PLATFORM_TWITTER,
            "twitter_nsfw": self.PLATFORM_TWITTER_NSF,
            "tiktok": self.PLATFORM_TIKTOK,
            "upscrolled": self.PLATFORM_UPSCROLLED,
            "febspot": self.PLATFORM_FEBSPOT,
        }
        return [p for p, enabled in toggle_map.items() if enabled]

    @property
    def raw_dir(self) -> Path:
        """Sub-directory inside DOWNLOAD_DIR for freshly downloaded source videos."""
        return self.DOWNLOAD_DIR / "raw"

    @property
    def rendered_dir(self) -> Path:
        """Sub-directory inside DOWNLOAD_DIR for FFmpeg-processed videos."""
        return self.DOWNLOAD_DIR / "rendered"

    @property
    def meta_dir(self) -> Path:
        """Sub-directory inside DOWNLOAD_DIR for JSON metadata files."""
        return self.DOWNLOAD_DIR / "meta"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """
        Create all required directories if they do not already exist.

        Directories created:

        * ``DOWNLOAD_DIR``
        * ``DOWNLOAD_DIR/raw``
        * ``DOWNLOAD_DIR/rendered``
        * ``DOWNLOAD_DIR/meta``
        * ``ASSETS_DIR``
        * ``PROFILES_DIR``
        * Parent of ``DB_PATH``
        """
        dirs: list[Path] = [
            self.DOWNLOAD_DIR,
            self.raw_dir,
            self.rendered_dir,
            self.meta_dir,
            self.ASSETS_DIR,
            self.PROFILES_DIR,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Ensure the database parent directory also exists
        db_parent = Path(self.DB_PATH).parent
        if str(db_parent) != ".":
            db_parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """
    Parse an environment-variable string as a boolean.

    Truthy strings (case-insensitive): ``"1"``, ``"true"``, ``"yes"``, ``"on"``.
    Everything else (including ``None``) returns *default*.
    """
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _nested_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Safely traverse a nested dictionary.

    Example::

        _nested_get(yaml_data, "rate_limits", "posts_per_hour_per_platform", default=2)
    """
    node: Any = data
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key, default)
    return node


# ---------------------------------------------------------------------------
# Singleton machinery
# ---------------------------------------------------------------------------

_config_singleton: Config | None = None


def get_config(*, reload: bool = False) -> Config:
    """
    Return the process-wide :class:`Config` singleton.

    On the first call (or when *reload* is ``True``) the configuration is
    built from:

    1. ``.env`` file at the project root (loaded via :mod:`python-dotenv`).
    2. ``config.yaml`` at the project root (loaded via :mod:`yaml`).
    3. Environment variables (always take priority over the YAML file).

    Parameters
    ----------
    reload:
        If ``True``, discard any previously cached singleton and re-read all
        sources.  Useful in tests or after a config file is updated at runtime.

    Returns
    -------
    Config
        The singleton :class:`Config` instance.
    """
    global _config_singleton

    if _config_singleton is not None and not reload:
        return _config_singleton

    # ------------------------------------------------------------------
    # 1. Load .env (does NOT override already-set environment variables)
    # ------------------------------------------------------------------
    _project_root = Path(__file__).resolve().parent.parent
    _env_file = _project_root / ".env"
    load_dotenv(dotenv_path=_env_file, override=False)

    # ------------------------------------------------------------------
    # 2. Load config.yaml
    # ------------------------------------------------------------------
    _yaml_file = _project_root / "config.yaml"
    yaml_data: dict[str, Any] = {}
    if _yaml_file.exists():
        with _yaml_file.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
            if isinstance(loaded, dict):
                yaml_data = loaded

    # ------------------------------------------------------------------
    # 3. Build the Config object
    # ------------------------------------------------------------------
    cfg = Config(
        # Paths
        DB_PATH=os.environ.get("OSAP_DB_PATH", "./osap.db"),
        DOWNLOAD_DIR=Path(os.environ.get("DOWNLOAD_DIR", "./downloads")),
        ASSETS_DIR=Path(os.environ.get("ASSETS_DIR", "./assets")),
        PROFILES_DIR=Path(os.environ.get("PROFILES_DIR", "./assets/profiles")),
        # AI
        DEEPSEEK_API_KEY=os.environ.get("DEEPSEEK_API_KEY", ""),
        DEEPSEEK_MODEL=os.environ.get(
            "DEEPSEEK_MODEL",
            _nested_get(yaml_data, "ai_caption", "model", default="deepseek-chat"),
        ),
        PROXY_URL=os.environ.get("PROXY_URL") or _nested_get(yaml_data, "proxy", "url", default=None),
        CAPTION_MODE="ai",
        CAPTION_SYSTEM_PROMPT=_nested_get(
            yaml_data, "ai", "caption_system_prompt",
            default=_DEFAULT_CAPTION_SYSTEM_PROMPT,
        ),
        # Platform toggles
        PLATFORM_YOUTUBE=_parse_bool(
            os.environ.get("PLATFORM_YOUTUBE"),
            default=bool(_nested_get(yaml_data, "platforms", "youtube", default=True)),
        ),
        PLATFORM_FACEBOOK=_parse_bool(
            os.environ.get("PLATFORM_FACEBOOK"),
            default=bool(_nested_get(yaml_data, "platforms", "facebook", default=True)),
        ),
        PLATFORM_INSTAGRAM=_parse_bool(
            os.environ.get("PLATFORM_INSTAGRAM"),
            default=bool(_nested_get(yaml_data, "platforms", "instagram", default=True)),
        ),
        PLATFORM_TWITTER=_parse_bool(
            os.environ.get("PLATFORM_TWITTER"),
            default=bool(_nested_get(yaml_data, "platforms", "twitter", default=True)),
        ),
        PLATFORM_TWITTER_NSF=_parse_bool(
            os.environ.get("PLATFORM_TWITTER_NSF"),
            default=bool(_nested_get(yaml_data, "platforms", "twitter_nsfw", default=False)),
        ),
        PLATFORM_TIKTOK=_parse_bool(
            os.environ.get("PLATFORM_TIKTOK"),
            default=bool(_nested_get(yaml_data, "platforms", "tiktok", default=True)),
        ),
        PLATFORM_UPSCROLLED=_parse_bool(
            os.environ.get("PLATFORM_UPSCROLLED"),
            default=bool(_nested_get(yaml_data, "platforms", "upscrolled", default=False)),
        ),
        PLATFORM_FEBSPOT=_parse_bool(
            os.environ.get("PLATFORM_FEBSPOT"),
            default=bool(_nested_get(yaml_data, "platforms", "febspot", default=False)),
        ),
        # Rate limits (YAML takes precedence over hardcoded defaults; env could override if desired)
        POSTS_PER_HOUR=int(
            os.environ.get(
                "POSTS_PER_HOUR",
                _nested_get(yaml_data, "rate_limits", "posts_per_hour_per_platform", default=2),
            )
        ),
        DELAY_BETWEEN_PLATFORMS=int(
            os.environ.get(
                "DELAY_BETWEEN_PLATFORMS",
                _nested_get(yaml_data, "rate_limits", "delay_between_platforms_sec", default=30),
            )
        ),
        WORKERS_DOWNLOADER=int(
            os.environ.get(
                "WORKERS_DOWNLOADER",
                _nested_get(yaml_data, "rate_limits", "workers_downloader", default=2),
            )
        ),
        HEADLESS=_parse_bool(
            os.environ.get("HEADLESS"),
            default=bool(_nested_get(yaml_data, "browser", "headless", default=False)),
        ),

        # FFmpeg — keys aligned with config.yaml naming convention
        FFMPEG_ZOOM=float(
            os.environ.get(
                "FFMPEG_ZOOM",
                _nested_get(yaml_data, "ffmpeg", "zoom_factor", default=1.04),
            )
        ),
        FFMPEG_SPEED=float(
            os.environ.get(
                "FFMPEG_SPEED",
                _nested_get(yaml_data, "ffmpeg", "speed_factor", default=1.0),
            )
        ),
        FFMPEG_NOISE=int(
            os.environ.get(
                "FFMPEG_NOISE",
                _nested_get(yaml_data, "ffmpeg", "noise_amount", default=2),
            )
        ),
        FFMPEG_CONTRAST=float(
            os.environ.get(
                "FFMPEG_CONTRAST",
                _nested_get(yaml_data, "ffmpeg", "contrast", default=1.05),
            )
        ),
        FFMPEG_SATURATION=float(
            os.environ.get(
                "FFMPEG_SATURATION",
                _nested_get(yaml_data, "ffmpeg", "saturation", default=1.1),
            )
        ),
    )

    _config_singleton = cfg
    return _config_singleton
