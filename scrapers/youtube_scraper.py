"""YouTube channel scraper: metadata via yt-dlp, transcripts via
youtube-transcript-api. Both libraries are synchronous, so the heavy
lifting runs in worker threads via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List, Optional

from config import YouTubeConfig, company_dir
from database.schema import YouTubeVideo
from utils.checkpoint import Checkpoint
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _list_channel_video_ids(channel_url: str, limit: int) -> List[str]:
    import yt_dlp

    opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": limit,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    entries = info.get("entries") or []
    ids = []
    for e in entries:
        if not e:
            continue
        # Channels sometimes nest tabs (Videos/Shorts/Live) as sub-entries.
        if e.get("_type") == "playlist" and e.get("entries"):
            for sub in e["entries"]:
                if sub and sub.get("id"):
                    ids.append(sub["id"])
        elif e.get("id"):
            ids.append(e["id"])
    return ids[:limit]


def _fetch_video_metadata(video_id: str) -> dict:
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    chapters = [
        {"title": c.get("title", ""), "start": c.get("start_time"), "end": c.get("end_time")}
        for c in (info.get("chapters") or [])
    ]

    return {
        "video_id": video_id,
        "title": info.get("title", ""),
        "description": info.get("description", "") or "",
        "upload_date": info.get("upload_date", ""),
        "view_count": info.get("view_count"),
        "comment_count": info.get("comment_count"),
        "chapters": chapters,
        "url": url,
    }


def _fetch_transcript(video_id: str, languages: tuple, transcripts_dir: Path) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ""

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=list(languages))
    except Exception as exc:  # noqa: BLE001
        logger.info("No transcript for %s: %s", video_id, exc)
        return ""

    text = " ".join(chunk["text"] for chunk in transcript)
    txt_path = transcripts_dir / f"{video_id}.txt"
    json_path = transcripts_dir / f"{video_id}.json"
    txt_path.write_text(text, encoding="utf-8")
    json_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(txt_path)


def _scrape_sync(company: str, channel_url: str, cfg: YouTubeConfig, checkpoint: Checkpoint) -> List[dict]:
    videos_out: List[dict] = checkpoint.get_state("videos", [])
    transcripts_dir = company_dir(company) / "transcripts"

    try:
        video_ids = _list_channel_video_ids(channel_url, cfg.max_videos)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not list videos for channel '%s': %s", channel_url, exc)
        return videos_out

    for video_id in video_ids:
        if checkpoint.is_done(video_id):
            continue
        try:
            meta = _fetch_video_metadata(video_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Metadata fetch failed for video %s: %s", video_id, exc)
            continue

        transcript_path = ""
        if cfg.download_transcripts:
            transcript_path = _fetch_transcript(video_id, cfg.languages, transcripts_dir)

        record = YouTubeVideo(
            video_id=meta["video_id"],
            title=meta["title"],
            description=meta["description"],
            upload_date=meta["upload_date"],
            view_count=meta["view_count"],
            comment_count=meta["comment_count"],
            chapters=meta["chapters"],
            transcript_path=transcript_path,
            url=meta["url"],
        )
        videos_out.append(record.__dict__)
        checkpoint.mark_done(video_id)
        checkpoint.set_state("videos", videos_out)

    return videos_out


async def scrape_youtube(company: str, channel_url: str, config: Optional[YouTubeConfig] = None) -> List[dict]:
    """Scrape up to `config.max_videos` videos (metadata + transcripts) from
    a YouTube channel URL."""
    cfg = config or YouTubeConfig()
    checkpoint = Checkpoint(company, "youtube")
    videos = await asyncio.to_thread(_scrape_sync, company, channel_url, cfg, checkpoint)
    logger.info("YouTube scrape complete: %d videos for %s", len(videos), channel_url)
    return videos
