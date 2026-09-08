"""
osap/modules/processor.py
─────────────────────────
FFmpeg video processing engine for the OmniShorts Auto-Publisher pipeline.

Applies a deterministic filter graph to every downloaded video:
  • Zoom + centre-crop   (anti-fingerprint reframe)
  • Speed-up             (setpts / atempo)
  • Colour grading       (eq filter)
  • Micro-noise          (noise filter)

Encoder is selected automatically:
  • NVIDIA GPU detected → h264_nvenc  (preset p4, cq 20)
  • CPU fallback        → libx264     (preset fast, crf 20)
"""

from __future__ import annotations

from pathlib import Path

import ffmpeg

from osap.config import get_config
from osap.db.queue import claim_next, log_error, update_video
from osap.utils.hardware import get_encoder
from osap.utils.logger import get_logger

logger = get_logger(__name__)


class VideoProcessor:
    """Claim *downloaded* DB jobs and render them through the FFmpeg pipeline.

    Parameters
    ----------
    db_path:
        Override path to the SQLite database.  Defaults to ``cfg.DB_PATH``.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.cfg = get_config()
        self.db_path = db_path or self.cfg.DB_PATH
        self._encoder: str = get_encoder()
        logger.info("VideoProcessor initialised with encoder=%s", self._encoder)

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Drain the *downloaded* queue until no more jobs remain."""
        logger.info("VideoProcessor started.")
        processed = 0
        while True:
            did_work = self._process_one()
            if not did_work:
                break
            processed += 1
        logger.info("VideoProcessor finished. Rendered %d video(s).", processed)

    # ------------------------------------------------------------------ #
    def _process_one(self) -> bool:
        """Claim one *downloaded* job and render it.

        Returns
        -------
        bool
            ``True`` if a job was claimed; ``False`` if the queue is empty.
        """
        video = claim_next("downloaded", "rendering")
        if video is None:
            logger.debug("No downloaded videos pending rendering.")
            return False

        vid_id: int = video["id"]
        logger.info("Rendering video id=%d  video_id=%s", vid_id, video.get("video_id"))

        rendered_path = self._render_video(video)

        if rendered_path is not None:
            update_video(vid_id, {"status": "rendered", "rendered_path": rendered_path})
            logger.info("Rendered video id=%d → %s", vid_id, rendered_path)
        else:
            # Errors already logged inside _render_video.
            update_video(vid_id, {"status": "failed"})

        return True

    # ------------------------------------------------------------------ #
    def _render_video(self, video: dict) -> str | None:
        """Apply the full FFmpeg filter graph and produce the output file.

        Filter graph
        ────────────
        Video chain:
          scale → crop → setpts → eq → noise

        Audio chain:
          aresample → atempo

        Parameters
        ----------
        video:
            DB row dict; must contain ``raw_path`` and ``video_id``.

        Returns
        -------
        str | None
            Absolute path of the rendered file on success, ``None`` on failure.
        """
        cfg = self.cfg
        raw_path_str: str | None = video.get("raw_path")
        video_uid: str = video.get("video_id") or str(video["id"])
        vid_id: int = video["id"]

        if not raw_path_str:
            msg = "raw_path is NULL – cannot render."
            logger.error("Video id=%d: %s", vid_id, msg)
            log_error(vid_id, "processor", msg)
            return None

        raw_path = Path(raw_path_str)
        if not raw_path.exists():
            msg = f"Raw file not found: {raw_path}"
            logger.error("Video id=%d: %s", vid_id, msg)
            log_error(vid_id, "processor", msg)
            return None

        # ── Output path ────────────────────────────────────────────────── #
        cfg.rendered_dir.mkdir(parents=True, exist_ok=True)
        out_path = cfg.rendered_dir / f"{video_uid}_rendered.mp4"

        # ── Config values ──────────────────────────────────────────────── #
        zoom: float = float(cfg.FFMPEG_ZOOM)          # e.g. 1.10
        speed: float = float(cfg.FFMPEG_SPEED)        # e.g. 1.05
        noise: int = int(cfg.FFMPEG_NOISE)            # e.g. 3
        contrast: float = float(cfg.FFMPEG_CONTRAST)  # e.g. 1.05
        saturation: float = float(cfg.FFMPEG_SATURATION)  # e.g. 1.08

        # ── Build filter graph ─────────────────────────────────────────── #
        try:
            input_node = ffmpeg.input(str(raw_path))

            # ── Video chain ─────────────────────────────────────────── #
            video_stream = input_node.video

            # 1. Scale up by zoom factor (keeps full frame).
            video_stream = ffmpeg.filter(
                video_stream,
                "scale",
                w=f"iw*{zoom}",
                h=f"ih*{zoom}",
            )

            # 2. Centre-crop back to original dimensions.
            video_stream = ffmpeg.filter(
                video_stream,
                "crop",
                w=f"iw/{zoom}",
                h=f"ih/{zoom}",
                x=f"(iw-iw/{zoom})/2",
                y=f"(ih-ih/{zoom})/2",
            )

            # 3. Speed-up via PTS manipulation.
            video_stream = ffmpeg.filter(
                video_stream,
                "setpts",
                f"PTS/{speed}",
            )

            # 4. Colour grading.
            video_stream = ffmpeg.filter(
                video_stream,
                "eq",
                contrast=contrast,
                saturation=saturation,
                brightness=0.02,
            )

            # 5. Micro noise injection (anti-duplicate fingerprint).
            video_stream = ffmpeg.filter(
                video_stream,
                "noise",
                alls=noise,
                allf="t+u",
            )

            # 6. Watermark text overlay (middle-left position).
            if getattr(cfg, "WATERMARK_ENABLED", True) and getattr(cfg, "WATERMARK_TEXT", ""):
                font_rel = getattr(cfg, "WATERMARK_FONT", "font/KOMIKAX_.ttf")
                font_file = Path(font_rel)
                if not font_file.is_absolute():
                    font_file = (Path(__file__).resolve().parents[2] / font_file).resolve()

                drawtext_kwargs: dict = {
                    "text": str(cfg.WATERMARK_TEXT),
                    "fontsize": int(getattr(cfg, "WATERMARK_FONT_SIZE", 32)),
                    "fontcolor": f"{getattr(cfg, 'WATERMARK_COLOR', 'white')}@{getattr(cfg, 'WATERMARK_OPACITY', 0.85)}",
                    "shadowcolor": "black@0.6",
                    "shadowx": 2,
                    "shadowy": 2,
                    "borderw": 2,
                    "bordercolor": "black@0.7",
                    "x": str(getattr(cfg, "WATERMARK_X", "40")),
                    "y": str(getattr(cfg, "WATERMARK_Y", "(h-text_h)/2")),
                }
                if font_file.exists():
                    drawtext_kwargs["fontfile"] = font_file.as_posix()

                video_stream = ffmpeg.filter(
                    video_stream,
                    "drawtext",
                    **drawtext_kwargs,
                )
                logger.info(
                    "Applied watermark text=%r with font=%s at x=%s, y=%s",
                    cfg.WATERMARK_TEXT,
                    font_file.name if font_file.exists() else "default",
                    drawtext_kwargs["x"],
                    drawtext_kwargs["y"],
                )

            # ── Audio chain ─────────────────────────────────────────── #
            audio_stream = input_node.audio

            # 1. Normalise sample rate.
            audio_stream = ffmpeg.filter(audio_stream, "aresample", 44100)

            # 2. Match video speed (atempo is safe between 0.5–2.0).
            audio_stream = ffmpeg.filter(audio_stream, "atempo", speed)

            # ── Encoder settings ─────────────────────────────────────── #
            encoder = self._encoder
            output_kwargs: dict = {
                "acodec": "aac",
                "audio_bitrate": "128k",
            }

            if encoder == "h264_nvenc":
                output_kwargs.update(
                    {
                        "vcodec": "h264_nvenc",
                        "preset": "p4",
                        "cq": "20",
                    }
                )
            else:
                output_kwargs.update(
                    {
                        "vcodec": "libx264",
                        "crf": 20,
                        "preset": "fast",
                    }
                )

            # ── Assemble output ──────────────────────────────────────── #
            out = ffmpeg.output(
                video_stream,
                audio_stream,
                str(out_path),
                **output_kwargs,
            )

            logger.debug(
                "FFmpeg command: %s",
                " ".join(ffmpeg.compile(out.overwrite_output())),
            )

            out.overwrite_output().run(quiet=True, capture_stderr=True)

        except ffmpeg.Error as exc:
            stderr_text = ""
            if exc.stderr:
                try:
                    stderr_text = exc.stderr.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    stderr_text = repr(exc.stderr)
            msg = f"ffmpeg.Error during rendering: {exc} | stderr: {stderr_text[:500]}"
            logger.error("Video id=%d: %s", vid_id, msg)
            log_error(vid_id, "processor", msg)
            return None

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error during rendering: {exc}"
            logger.exception("Video id=%d: %s", vid_id, msg)
            log_error(vid_id, "processor", msg)
            return None

        return str(out_path)


__all__ = ["VideoProcessor"]
