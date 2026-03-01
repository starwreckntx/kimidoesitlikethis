import asyncio
import logging
from typing import Any

from .base import BaseTool

logger = logging.getLogger(__name__)


def _build_youtube_service(config):
    from googleapiclient.discovery import build
    if config.YOUTUBE_API_KEY:
        return build("youtube", "v3", developerKey=config.YOUTUBE_API_KEY)
    # Fall back to OAuth2 if API key not set but Google OAuth configured
    from google.oauth2.credentials import Credentials
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.readonly"],
    )
    return build("youtube", "v3", credentials=creds)


class YouTubeTool(BaseTool):
    name = "youtube"
    description = (
        "Interact with YouTube. Actions: search_videos, get_video_info, "
        "get_channel_info, list_playlists, get_playlist_items, get_trending."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search_videos", "get_video_info", "get_channel_info",
                         "list_playlists", "get_playlist_items", "get_trending"],
                "description": "YouTube action to perform.",
            },
            "query": {"type": "string", "description": "Search query."},
            "video_id": {"type": "string", "description": "YouTube video ID."},
            "channel_id": {"type": "string", "description": "YouTube channel ID."},
            "playlist_id": {"type": "string", "description": "YouTube playlist ID."},
            "max_results": {"type": "integer", "description": "Max results to return. Default 10."},
            "region_code": {"type": "string", "description": "Region code for trending (e.g. US). Default US."},
        },
        "required": ["action"],
    }

    def __init__(self, config):
        self._config = config

    def _svc(self):
        return _build_youtube_service(self._config)

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "search_videos":
                return await asyncio.to_thread(self._search_videos, kwargs)
            elif action == "get_video_info":
                return await asyncio.to_thread(self._get_video_info, kwargs)
            elif action == "get_channel_info":
                return await asyncio.to_thread(self._get_channel_info, kwargs)
            elif action == "list_playlists":
                return await asyncio.to_thread(self._list_playlists, kwargs)
            elif action == "get_playlist_items":
                return await asyncio.to_thread(self._get_playlist_items, kwargs)
            elif action == "get_trending":
                return await asyncio.to_thread(self._get_trending, kwargs)
            else:
                return f"Unknown YouTube action: {action}"
        except Exception as e:
            logger.error("YouTube tool error", exc_info=True)
            return f"YouTube error: {e}"

    def _search_videos(self, kwargs: dict) -> str:
        svc = self._svc()
        resp = svc.search().list(
            q=kwargs.get("query", ""),
            part="snippet",
            maxResults=int(kwargs.get("max_results", 10)),
            type="video",
        ).execute()
        items = resp.get("items", [])
        if not items:
            return "No videos found."
        lines = []
        for item in items:
            vid_id = item["id"].get("videoId", "")
            snip = item.get("snippet", {})
            lines.append(
                f"Title: {snip.get('title')}\n"
                f"  Channel: {snip.get('channelTitle')}\n"
                f"  URL: https://youtube.com/watch?v={vid_id}\n"
                f"  Description: {snip.get('description', '')[:120]}..."
            )
        return "\n\n".join(lines)

    def _get_video_info(self, kwargs: dict) -> str:
        svc = self._svc()
        resp = svc.videos().list(
            id=kwargs.get("video_id", ""),
            part="snippet,statistics,contentDetails",
        ).execute()
        items = resp.get("items", [])
        if not items:
            return "Video not found."
        v = items[0]
        snip = v.get("snippet", {})
        stats = v.get("statistics", {})
        return (
            f"Title: {snip.get('title')}\n"
            f"Channel: {snip.get('channelTitle')}\n"
            f"Published: {snip.get('publishedAt')}\n"
            f"Views: {stats.get('viewCount', 0)} | "
            f"Likes: {stats.get('likeCount', 0)} | "
            f"Comments: {stats.get('commentCount', 0)}\n"
            f"Duration: {v.get('contentDetails', {}).get('duration', 'N/A')}\n"
            f"Description: {snip.get('description', '')[:400]}"
        )

    def _get_channel_info(self, kwargs: dict) -> str:
        svc = self._svc()
        resp = svc.channels().list(
            id=kwargs.get("channel_id", ""),
            part="snippet,statistics",
        ).execute()
        items = resp.get("items", [])
        if not items:
            return "Channel not found."
        c = items[0]
        snip = c.get("snippet", {})
        stats = c.get("statistics", {})
        return (
            f"Name: {snip.get('title')}\n"
            f"Subscribers: {stats.get('subscriberCount', 'hidden')}\n"
            f"Videos: {stats.get('videoCount', 0)}\n"
            f"Views: {stats.get('viewCount', 0)}\n"
            f"Description: {snip.get('description', '')[:300]}"
        )

    def _list_playlists(self, kwargs: dict) -> str:
        svc = self._svc()
        resp = svc.playlists().list(
            part="snippet,contentDetails",
            mine=True,
            maxResults=int(kwargs.get("max_results", 20)),
        ).execute()
        items = resp.get("items", [])
        if not items:
            return "No playlists found."
        lines = [
            f"[{p['id']}] {p['snippet']['title']} ({p['contentDetails']['itemCount']} videos)"
            for p in items
        ]
        return "\n".join(lines)

    def _get_playlist_items(self, kwargs: dict) -> str:
        svc = self._svc()
        resp = svc.playlistItems().list(
            part="snippet",
            playlistId=kwargs.get("playlist_id", ""),
            maxResults=int(kwargs.get("max_results", 20)),
        ).execute()
        items = resp.get("items", [])
        if not items:
            return "Playlist is empty."
        lines = []
        for i, item in enumerate(items, 1):
            snip = item.get("snippet", {})
            vid_id = snip.get("resourceId", {}).get("videoId", "")
            lines.append(f"{i}. {snip.get('title')} – https://youtube.com/watch?v={vid_id}")
        return "\n".join(lines)

    def _get_trending(self, kwargs: dict) -> str:
        svc = self._svc()
        resp = svc.videos().list(
            part="snippet,statistics",
            chart="mostPopular",
            regionCode=kwargs.get("region_code", "US"),
            maxResults=int(kwargs.get("max_results", 10)),
        ).execute()
        items = resp.get("items", [])
        if not items:
            return "No trending videos found."
        lines = []
        for i, v in enumerate(items, 1):
            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            lines.append(
                f"{i}. {snip.get('title')} – {stats.get('viewCount', 0)} views "
                f"(https://youtube.com/watch?v={v['id']})"
            )
        return "\n".join(lines)
