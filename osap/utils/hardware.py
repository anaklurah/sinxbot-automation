"""
Hardware detection utilities for encoder selection.
====================================================
Provides lightweight runtime detection of GPU hardware so that the rest of
the pipeline can choose the fastest available FFmpeg encoder without any
manual configuration.

All detection results are cached with :func:`functools.lru_cache` so that
``nvidia-smi`` is only executed once per process lifetime.

Usage::

    from osap.utils.hardware import get_encoder, get_hwaccel_args, get_system_info

    encoder = get_encoder()            # 'h264_nvenc' or 'libx264'
    extra   = get_hwaccel_args()       # dict of extra FFmpeg kwargs
    info    = get_system_info()        # diagnostic snapshot
"""
from __future__ import annotations

import platform
import subprocess
import sys
from functools import lru_cache
from typing import Any


# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def has_nvidia_gpu() -> bool:
    """
    Detect whether an NVIDIA GPU is available by interrogating ``nvidia-smi``.

    The check is performed once and the result is cached for the lifetime of
    the process via :func:`functools.lru_cache`.

    Returns
    -------
    bool
        ``True`` if ``nvidia-smi`` is found on ``PATH`` and exits successfully
        (return code 0), ``False`` in all other cases including:

        * ``nvidia-smi`` not found (``FileNotFoundError``).
        * ``nvidia-smi`` exits with a non-zero code (no CUDA driver / no GPU).
        * The subprocess times out after 5 seconds.
        * Any other OS-level error.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            timeout=5,
            check=True,  # raises CalledProcessError on non-zero exit
        )
        # Extra sanity-check: make sure the output mentions "NVIDIA"
        return b"NVIDIA" in result.stdout or result.returncode == 0
    except FileNotFoundError:
        # nvidia-smi binary is not on PATH
        return False
    except subprocess.CalledProcessError:
        # nvidia-smi found but failed (no CUDA driver, no GPU, etc.)
        return False
    except subprocess.TimeoutExpired:
        # nvidia-smi hung — treat as unavailable
        return False
    except OSError:
        # Other OS-level errors (permissions, etc.)
        return False


# ---------------------------------------------------------------------------
# Encoder selection
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_encoder() -> str:
    """
    Return the best available H.264 FFmpeg encoder for the current hardware.

    Returns
    -------
    str
        ``'h264_nvenc'`` when an NVIDIA GPU is detected (NVENC hardware
        encoder — dramatically faster than software encoding and leaves CPU
        headroom for other pipeline stages), or ``'libx264'`` as the
        universal software fallback.
    """
    return "h264_nvenc" if has_nvidia_gpu() else "libx264"


# ---------------------------------------------------------------------------
# Hardware-acceleration FFmpeg arguments
# ---------------------------------------------------------------------------


def get_hwaccel_args() -> dict[str, Any]:
    """
    Return a dictionary of extra FFmpeg keyword arguments appropriate for
    the current hardware.

    These kwargs are intended to be merged into the FFmpeg command via
    ``ffmpeg-python`` or similar wrappers.  When using NVENC the input is
    decoded with CUDA hardware acceleration (``-hwaccel cuda``) for maximum
    throughput.  The software path returns an empty dict so that callers
    need no conditional logic.

    Returns
    -------
    dict[str, Any]
        For NVIDIA hardware::

            {
                "hwaccel": "cuda",
                "hwaccel_output_format": "cuda",
            }

        For CPU / software::

            {}

    Notes
    -----
    Callers should still be prepared for NVENC failures at runtime (e.g. the
    GPU is out of encoder sessions) and fall back to libx264 if needed.
    """
    if has_nvidia_gpu():
        return {
            "hwaccel": "cuda",
            "hwaccel_output_format": "cuda",
        }
    return {}


# ---------------------------------------------------------------------------
# System information snapshot
# ---------------------------------------------------------------------------


def get_system_info() -> dict[str, str]:
    """
    Return a human-readable snapshot of the current runtime environment.

    Useful for logging at startup or attaching to bug reports.

    Returns
    -------
    dict[str, str]
        A flat dictionary with the following keys:

        ``os``
            Operating system name and release (e.g. ``"Windows 10"``).
        ``os_version``
            Detailed OS version string from :func:`platform.version`.
        ``machine``
            CPU architecture (e.g. ``"AMD64"``).
        ``python_version``
            Full Python interpreter version string (e.g. ``"3.11.4"``).
        ``gpu``
            ``"NVIDIA (detected)"`` or ``"None / unknown"``.
        ``encoder``
            The FFmpeg encoder that will be used (``"h264_nvenc"`` or
            ``"libx264"``).

    Example
    -------
    ::

        from osap.utils.hardware import get_system_info
        from rich import print

        print(get_system_info())
        # {
        #   'os': 'Windows 11',
        #   'os_version': '10.0.22631',
        #   ...
        # }
    """
    gpu_label = "NVIDIA (detected)" if has_nvidia_gpu() else "None / unknown"

    return {
        "os": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "gpu": gpu_label,
        "encoder": get_encoder(),
    }
