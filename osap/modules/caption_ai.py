"""
osap/modules/caption_ai.py
──────────────────────────
DeepSeek AI caption generator for the OmniShorts Auto-Publisher pipeline.

Uses the OpenAI-compatible DeepSeek API to produce viral, platform-optimised
captions (title, description, hashtags) from original video metadata.

Retry behaviour
───────────────
• One automatic retry after a 5-second delay on transient errors
  (rate-limits, timeouts, connection errors).
• All other exceptions cause an immediate fallback to sanitised original data.
"""

from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, RateLimitError

from osap.utils.logger import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = """You are a viral social media content expert specializing in short-form video captions.
Your task is to generate highly engaging captions for social media videos.

Given a video title and description, generate:
1. A catchy, engaging title (max 100 characters)
2. An engaging description (max 300 characters)
3. A list of 10-15 relevant trending hashtags

Respond ONLY with a valid JSON object in this exact format:
{
  "title": "...",
  "description": "...",
  "hashtags": ["#tag1", "#tag2", ...]
}

Do not include any other text, markdown, or explanation."""

# Transient error types that warrant a single retry.
_TRANSIENT_EXCEPTIONS = (
    APIConnectionError,
    RateLimitError,
    asyncio.TimeoutError,
)


# ──────────────────────────────────────────────────────────────────────────────
# CaptionAI
# ──────────────────────────────────────────────────────────────────────────────

class CaptionAI:
    """Generate AI-powered social media captions via the DeepSeek API.

    Parameters
    ----------
    api_key:
        DeepSeek API key.
    model:
        Model name to use (default ``'deepseek-chat'``).
    system_prompt:
        System prompt override.  Defaults to :data:`DEFAULT_SYSTEM_PROMPT`.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )
        self.model = model
        self.system_prompt = system_prompt

    # ------------------------------------------------------------------ #
    async def generate(
        self,
        title: str,
        description: str,
        tags: list[str] | None = None,
    ) -> dict:
        """Generate an AI caption asynchronously.

        Parameters
        ----------
        title:
            Original video title.
        description:
            Original video description.
        tags:
            Original video tags (optional).

        Returns
        -------
        dict
            ``{'title': str, 'description': str, 'hashtags': list[str]}``

            Falls back to a sanitised version of the original metadata if the
            API call fails after one retry.
        """
        user_message = (
            f"Video title: {title}\n"
            f"Original description: {description}\n"
            f"Original tags: {', '.join(tags or [])}"
        )

        attempt = 0
        last_exc: Exception | None = None

        while attempt < 2:
            attempt += 1
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.7,
                    max_tokens=500,
                    response_format={"type": "json_object"},
                )

                raw_content: str = response.choices[0].message.content or "{}"
                data: dict = json.loads(raw_content)

                # Validate required keys.
                for key in ("title", "description", "hashtags"):
                    if key not in data:
                        raise KeyError(f"Missing required key '{key}' in AI response.")

                # Coerce types for safety.
                result = {
                    "title": str(data["title"])[:100],
                    "description": str(data["description"])[:300],
                    "hashtags": [str(h) for h in data["hashtags"]],
                }

                logger.info(
                    "AI caption generated (attempt %d): title='%s'",
                    attempt,
                    result["title"],
                )
                return result

            except _TRANSIENT_EXCEPTIONS as exc:
                last_exc = exc
                if attempt == 1:
                    logger.warning(
                        "Transient API error (attempt %d/%d): %s – retrying in 5s…",
                        attempt,
                        2,
                        exc,
                    )
                    await asyncio.sleep(5)
                    continue
                # Second attempt also failed – fall through to fallback.
                logger.warning(
                    "Transient API error on retry (attempt %d/%d): %s – using fallback.",
                    attempt,
                    2,
                    exc,
                )
                break

            except APIStatusError as exc:
                # Non-transient HTTP errors (4xx except 429) – no retry.
                last_exc = exc
                logger.warning(
                    "API status error (HTTP %d): %s – using fallback.",
                    exc.status_code,
                    exc.message,
                )
                break

            except json.JSONDecodeError as exc:
                last_exc = exc
                logger.warning(
                    "Failed to parse AI JSON response (attempt %d): %s – using fallback.",
                    attempt,
                    exc,
                )
                break

            except KeyError as exc:
                last_exc = exc
                logger.warning(
                    "AI response missing expected key (attempt %d): %s – using fallback.",
                    attempt,
                    exc,
                )
                break

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Unexpected error during caption generation (attempt %d): %s – using fallback.",
                    attempt,
                    exc,
                )
                break

        # ── Fallback ──────────────────────────────────────────────────── #
        fallback = self._build_fallback(title, description, tags)
        logger.info("Returning fallback caption for title='%s'.", title[:60])
        return fallback

    # ------------------------------------------------------------------ #
    def generate_sync(
        self,
        title: str,
        description: str,
        tags: list[str] | None = None,
    ) -> dict:
        """Synchronous wrapper around :meth:`generate`.

        Safe to call from non-async contexts.  Creates a new event loop if
        none is running (avoids ``RuntimeError: no current event loop``).

        Parameters
        ----------
        title, description, tags:
            Forwarded directly to :meth:`generate`.

        Returns
        -------
        dict
            Same shape as :meth:`generate`.
        """
        try:
            # If there is already a running loop (e.g. Jupyter), use it.
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.generate(title, description, tags),
                    )
                    return future.result()
            return loop.run_until_complete(self.generate(title, description, tags))
        except RuntimeError:
            return asyncio.run(self.generate(title, description, tags))

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_fallback(
        title: str,
        description: str | None,
        tags: list[str] | None,
    ) -> dict:
        """Construct a safe fallback caption from raw metadata."""
        return {
            "title": (title or "")[:100],
            "description": (description or "")[:300],
            "hashtags": [f"#{t}" for t in (tags or [])[:15]],
        }


__all__ = ["CaptionAI", "DEFAULT_SYSTEM_PROMPT"]
