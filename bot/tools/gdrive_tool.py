import asyncio
import io
import logging
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from .base import BaseTool

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]


def _build_service(config):
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)


class GDriveTool(BaseTool):
    name = "google_drive"
    description = (
        "Interact with Google Drive. Actions: list_files, search_files, get_file_content, "
        "create_text_file, delete_file, share_file, create_folder."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_files", "search_files", "get_file_content",
                         "create_text_file", "delete_file", "share_file", "create_folder"],
                "description": "Drive action to perform.",
            },
            "query": {"type": "string", "description": "Search query or folder name."},
            "file_id": {"type": "string", "description": "Google Drive file/folder ID."},
            "name": {"type": "string", "description": "File or folder name."},
            "content": {"type": "string", "description": "Text content for new file."},
            "email": {"type": "string", "description": "Email to share file with."},
            "role": {
                "type": "string",
                "enum": ["reader", "writer", "commenter"],
                "description": "Sharing role. Default: reader.",
            },
            "max_results": {"type": "integer", "description": "Max files to list. Default 20."},
        },
        "required": ["action"],
    }

    def __init__(self, config):
        self._config = config

    def _svc(self):
        return _build_service(self._config)

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "list_files":
                return await asyncio.to_thread(self._list_files, kwargs)
            elif action == "search_files":
                return await asyncio.to_thread(self._search_files, kwargs)
            elif action == "get_file_content":
                return await asyncio.to_thread(self._get_file_content, kwargs)
            elif action == "create_text_file":
                return await asyncio.to_thread(self._create_text_file, kwargs)
            elif action == "delete_file":
                return await asyncio.to_thread(self._delete_file, kwargs)
            elif action == "share_file":
                return await asyncio.to_thread(self._share_file, kwargs)
            elif action == "create_folder":
                return await asyncio.to_thread(self._create_folder, kwargs)
            else:
                return f"Unknown Drive action: {action}"
        except Exception as e:
            logger.error("Drive tool error", exc_info=True)
            return f"Google Drive error: {e}"

    def _fmt_file(self, f: dict) -> str:
        return (
            f"ID: {f['id']} | Name: {f.get('name')} | "
            f"Type: {f.get('mimeType', '').split('.')[-1]} | "
            f"Modified: {f.get('modifiedTime', 'N/A')}"
        )

    def _list_files(self, kwargs: dict) -> str:
        svc = self._svc()
        max_results = int(kwargs.get("max_results", 20))
        results = svc.files().list(
            pageSize=max_results,
            fields="files(id,name,mimeType,modifiedTime,size)",
            orderBy="modifiedTime desc",
        ).execute()
        files = results.get("files", [])
        if not files:
            return "No files found."
        return "\n".join(self._fmt_file(f) for f in files)

    def _search_files(self, kwargs: dict) -> str:
        svc = self._svc()
        q = kwargs.get("query", "")
        drive_q = f"name contains '{q}' and trashed = false"
        results = svc.files().list(
            q=drive_q,
            fields="files(id,name,mimeType,modifiedTime)",
            pageSize=20,
        ).execute()
        files = results.get("files", [])
        if not files:
            return f"No files found matching '{q}'."
        return "\n".join(self._fmt_file(f) for f in files)

    def _get_file_content(self, kwargs: dict) -> str:
        svc = self._svc()
        file_id = kwargs.get("file_id", "")
        meta = svc.files().get(fileId=file_id, fields="mimeType,name").execute()
        mime = meta.get("mimeType", "")
        name = meta.get("name", "")
        # Export Google Docs as plain text
        if "google-apps.document" in mime:
            content = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
            return f"# {name}\n\n{content.decode('utf-8', errors='replace')[:6000]}"
        # Download other files
        content = svc.files().get_media(fileId=file_id).execute()
        if isinstance(content, bytes):
            try:
                return f"# {name}\n\n{content.decode('utf-8', errors='replace')[:6000]}"
            except Exception:
                return f"File '{name}' is binary and cannot be displayed as text."
        return str(content)[:6000]

    def _create_text_file(self, kwargs: dict) -> str:
        svc = self._svc()
        name = kwargs.get("name", "untitled.txt")
        content = kwargs.get("content", "")
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/plain",
            resumable=False,
        )
        file = svc.files().create(
            body={"name": name},
            media_body=media,
            fields="id,name",
        ).execute()
        return f"File created: '{file['name']}' (ID: {file['id']})"

    def _delete_file(self, kwargs: dict) -> str:
        svc = self._svc()
        svc.files().delete(fileId=kwargs.get("file_id", "")).execute()
        return "File deleted."

    def _share_file(self, kwargs: dict) -> str:
        svc = self._svc()
        svc.permissions().create(
            fileId=kwargs.get("file_id", ""),
            body={
                "type": "user",
                "role": kwargs.get("role", "reader"),
                "emailAddress": kwargs.get("email", ""),
            },
            sendNotificationEmail=True,
        ).execute()
        return f"File shared with {kwargs.get('email')} as {kwargs.get('role', 'reader')}."

    def _create_folder(self, kwargs: dict) -> str:
        svc = self._svc()
        folder = svc.files().create(
            body={"name": kwargs.get("name", "New Folder"),
                  "mimeType": "application/vnd.google-apps.folder"},
            fields="id,name",
        ).execute()
        return f"Folder created: '{folder['name']}' (ID: {folder['id']})"
