"""Instagram scraper built on top of `instaloader` (a public scraping library
that talks to Instagram's own web API, no official API key required).

Instagram aggressively rate-limits and login-walls anonymous scraping, so
every failure mode here is treated as recoverable: we log a warning and
return whatever we already collected rather than crashing the pipeline.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from config import InstagramConfig, company_dir
from database.schema import InstagramPost
from utils.checkpoint import Checkpoint
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _build_loader(cfg: InstagramConfig):
    import instaloader

    loader = instaloader.Instaloader(
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )
    if cfg.login_username and cfg.login_password:
        try:
            loader.login(cfg.login_username, cfg.login_password)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Instagram login failed, continuing anonymously: %s", exc)
    return loader


def _scrape_sync(company: str, handle: str, cfg: InstagramConfig, checkpoint: Checkpoint) -> List[dict]:
    import instaloader

    posts_out: List[dict] = checkpoint.get_state("posts", [])
    images_dir = company_dir(company) / "images"

    try:
        loader = _build_loader(cfg)
        profile = instaloader.Profile.from_username(loader.context, handle.lstrip("@"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not load Instagram profile '%s': %s", handle, exc)
        return posts_out

    count = 0
    try:
        for post in profile.get_posts():
            if count >= cfg.max_posts:
                break
            if checkpoint.is_done(post.shortcode):
                count += 1
                continue

            alt_text = ""
            try:
                alt_text = post.accessibility_caption or ""
            except Exception:  # noqa: BLE001
                pass

            image_path = ""
            if cfg.download_images:
                try:
                    target = images_dir / f"{post.shortcode}.jpg"
                    if post.typename != "GraphSidecar" and not post.is_video:
                        loader.download_pic(str(target.with_suffix("")), post.url, post.date_utc)
                        image_path = str(target)
                except Exception as exc:  # noqa: BLE001
                    logger.info("Image download failed for %s: %s", post.shortcode, exc)

            record = InstagramPost(
                shortcode=post.shortcode,
                caption=post.caption or "",
                hashtags=list(post.caption_hashtags or []),
                date=post.date_utc.isoformat(),
                likes=getattr(post, "likes", None),
                comments_count=getattr(post, "comments", None),
                is_video=post.is_video,
                alt_text=alt_text,
                image_path=image_path,
                url=f"https://www.instagram.com/p/{post.shortcode}/",
            )
            posts_out.append(record.__dict__)
            checkpoint.mark_done(post.shortcode)
            checkpoint.set_state("posts", posts_out)
            count += 1

    except Exception as exc:  # noqa: BLE001
        # Rate limiting / login wall / private profile — stop but keep partial results.
        logger.warning("Instagram scraping stopped early for '%s': %s", handle, exc)

    return posts_out


async def scrape_instagram(company: str, handle: str, config: Optional[InstagramConfig] = None) -> List[dict]:
    """Scrape up to `config.max_posts` public posts from an Instagram handle.

    Runs the synchronous `instaloader` calls in a worker thread so the rest
    of the async pipeline keeps making progress in parallel.
    """
    cfg = config or InstagramConfig()
    checkpoint = Checkpoint(company, "instagram")
    posts = await asyncio.to_thread(_scrape_sync, company, handle, cfg, checkpoint)
    logger.info("Instagram scrape complete: %d posts for @%s", len(posts), handle)
    return posts
