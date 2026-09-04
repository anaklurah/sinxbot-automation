"""
Twitter / X NSFW publisher.

Thin subclass of TwitterPublisher that permanently sets ``NSFW = True`` and
overrides the ``upload()`` method to ensure the sensitive-content flag is
always activated before posting.
"""
from playwright.async_api import Page

from osap.modules.publisher.twitter import TwitterPublisher


class TwitterNSFWPublisher(TwitterPublisher):
    """Posts a video tweet marked as sensitive / NSFW content.

    Inherits all logic from TwitterPublisher.  The only behavioural
    difference is that ``_mark_sensitive()`` is always called prior to
    clicking Post, regardless of the caller-supplied arguments.

    Auth method: storage_state (cfg.PROFILES_DIR / 'twitter_nsfw_storage.json')
    Tip: you can share the same storage file as the base twitter publisher by
    symlinking or copying it with the ``twitter_nsfw_`` prefix.
    """

    PLATFORM_NAME = 'twitter_nsfw'
    NSFW = True

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Upload a video tweet with the sensitive-content flag forced on.

        This method is a thin wrapper around the parent implementation.
        Because ``NSFW = True`` on this class, the parent's ``upload()``
        will always call ``_mark_sensitive()`` before posting.

        Args:
            video_path: Absolute path to the video file.
            title: Tweet text prefix.
            description: Additional text body.
            tags: Hashtag list.

        Returns:
            True on success.
        """
        # NSFW is already True on this class; parent upload() will handle it.
        # We call super() explicitly so any future changes to the parent's
        # upload flow are inherited automatically.
        self._log.info(
            '[twitter_nsfw] Starting NSFW upload — sensitive flag will be activated'
        )
        return await super().upload(video_path, title, description, tags)
