import asyncio
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .base import BaseTool

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
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
    return build("gmail", "v1", credentials=creds)


def _decode_body(payload: dict) -> str:
    """Recursively decode email body from MIME parts."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") in ("text/plain", "text/html"):
                if part["body"].get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    return ""


class GmailTool(BaseTool):
    name = "gmail"
    description = (
        "Interact with Gmail. Actions: list_emails, get_email, send_email, "
        "reply_email, search_emails, create_draft, trash_email."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_emails", "get_email", "send_email", "reply_email",
                         "search_emails", "create_draft", "trash_email"],
                "description": "The Gmail action to perform.",
            },
            "query": {"type": "string", "description": "Search query (for list_emails / search_emails)."},
            "max_results": {"type": "integer", "description": "Max emails to return. Default 10."},
            "message_id": {"type": "string", "description": "Gmail message ID."},
            "to": {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string", "description": "Email subject."},
            "body": {"type": "string", "description": "Email body (plain text)."},
        },
        "required": ["action"],
    }

    def __init__(self, config):
        self._config = config

    def _get_service(self):
        return _build_service(self._config)

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "list_emails":
                return await asyncio.to_thread(self._list_emails, kwargs)
            elif action == "get_email":
                return await asyncio.to_thread(self._get_email, kwargs)
            elif action == "send_email":
                return await asyncio.to_thread(self._send_email, kwargs)
            elif action == "reply_email":
                return await asyncio.to_thread(self._reply_email, kwargs)
            elif action == "search_emails":
                return await asyncio.to_thread(self._list_emails, kwargs)
            elif action == "create_draft":
                return await asyncio.to_thread(self._create_draft, kwargs)
            elif action == "trash_email":
                return await asyncio.to_thread(self._trash_email, kwargs)
            else:
                return f"Unknown Gmail action: {action}"
        except Exception as e:
            logger.error("Gmail tool error", exc_info=True)
            return f"Gmail error: {e}"

    def _list_emails(self, kwargs: dict) -> str:
        svc = self._get_service()
        query = kwargs.get("query", "")
        max_results = int(kwargs.get("max_results", 10))
        result = svc.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return "No emails found."
        lines = []
        for msg in messages:
            meta = svc.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
            lines.append(
                f"ID: {msg['id']}\n"
                f"  From: {headers.get('From', 'N/A')}\n"
                f"  Subject: {headers.get('Subject', 'N/A')}\n"
                f"  Date: {headers.get('Date', 'N/A')}"
            )
        return "\n\n".join(lines)

    def _get_email(self, kwargs: dict) -> str:
        svc = self._get_service()
        msg_id = kwargs.get("message_id", "")
        msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = _decode_body(msg.get("payload", {}))
        return (
            f"From: {headers.get('From')}\n"
            f"To: {headers.get('To')}\n"
            f"Subject: {headers.get('Subject')}\n"
            f"Date: {headers.get('Date')}\n\n"
            f"{body[:4000]}"
        )

    def _build_message(self, to: str, subject: str, body: str,
                        thread_id: str | None = None, reply_to_id: str | None = None) -> dict:
        mime = MIMEMultipart()
        mime["to"] = to
        mime["subject"] = subject
        mime.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        msg_body: dict = {"raw": raw}
        if thread_id:
            msg_body["threadId"] = thread_id
        return msg_body

    def _send_email(self, kwargs: dict) -> str:
        svc = self._get_service()
        msg = self._build_message(
            kwargs.get("to", ""),
            kwargs.get("subject", "(no subject)"),
            kwargs.get("body", ""),
        )
        sent = svc.users().messages().send(userId="me", body=msg).execute()
        return f"Email sent. Message ID: {sent['id']}"

    def _reply_email(self, kwargs: dict) -> str:
        svc = self._get_service()
        orig_id = kwargs.get("message_id", "")
        orig = svc.users().messages().get(userId="me", id=orig_id, format="metadata",
                                          metadataHeaders=["From", "Subject", "Message-ID"]).execute()
        headers = {h["name"]: h["value"] for h in orig.get("payload", {}).get("headers", [])}
        thread_id = orig.get("threadId")
        to = headers.get("From", "")
        subject = "Re: " + headers.get("Subject", "")
        msg = self._build_message(to, subject, kwargs.get("body", ""), thread_id=thread_id)
        sent = svc.users().messages().send(userId="me", body=msg).execute()
        return f"Reply sent. Message ID: {sent['id']}"

    def _create_draft(self, kwargs: dict) -> str:
        svc = self._get_service()
        msg = self._build_message(
            kwargs.get("to", ""),
            kwargs.get("subject", "(no subject)"),
            kwargs.get("body", ""),
        )
        draft = svc.users().drafts().create(userId="me", body={"message": msg}).execute()
        return f"Draft created. Draft ID: {draft['id']}"

    def _trash_email(self, kwargs: dict) -> str:
        svc = self._get_service()
        svc.users().messages().trash(userId="me", id=kwargs.get("message_id", "")).execute()
        return "Email moved to trash."
