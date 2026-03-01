import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BaseTool

logger = logging.getLogger(__name__)

# Subdirectory names within MNEMOSYNE_LEDGER_PATH
_NODES_DIR = "nodes"
_SESSIONS_DIR = "sessions"
_LEDGER_FILE = "LEDGER.md"
_TIMELINE_FILE = "TIMELINE.md"
_CONFIG_FILE = "CONFIG.yaml"
_KALI_NODE_FILE = "nodes/kali_context.md"


class MnemosyneTool(BaseTool):
    name = "mnemosyne"
    description = (
        "Read and write the Mnemosyne Ledger — the persistent cross-session memory "
        "store for this node. Actions: read_ledger, read_node_context, read_config, "
        "read_timeline, list_sessions, read_session, write_ledger_entry, "
        "write_session, update_node_context."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "read_ledger",
                    "read_node_context",
                    "read_config",
                    "read_timeline",
                    "list_sessions",
                    "read_session",
                    "write_ledger_entry",
                    "write_session",
                    "update_node_context",
                ],
                "description": "Ledger operation to perform.",
            },
            "entry": {
                "type": "string",
                "description": (
                    "Markdown content for the new ledger entry "
                    "(write_ledger_entry). A timestamp header is added automatically."
                ),
            },
            "filename": {
                "type": "string",
                "description": (
                    "Session filename (e.g. '2026-03-01_bot-test.md'). "
                    "Required for read_session and write_session."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "Full content for write_session or update_node_context."
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(self, config) -> None:
        self._root = Path(config.MNEMOSYNE_LEDGER_PATH).expanduser().resolve()

    # ------------------------------------------------------------------
    # Public execute
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "read_ledger":
                return await asyncio.to_thread(self._read_file, _LEDGER_FILE)
            elif action == "read_node_context":
                return await asyncio.to_thread(self._read_file, _KALI_NODE_FILE)
            elif action == "read_config":
                return await asyncio.to_thread(self._read_file, _CONFIG_FILE)
            elif action == "read_timeline":
                return await asyncio.to_thread(self._read_file, _TIMELINE_FILE)
            elif action == "list_sessions":
                return await asyncio.to_thread(self._list_sessions)
            elif action == "read_session":
                filename = kwargs.get("filename", "")
                if not filename:
                    return "Error: 'filename' is required for read_session."
                return await asyncio.to_thread(self._read_file, f"{_SESSIONS_DIR}/{filename}")
            elif action == "write_ledger_entry":
                entry = kwargs.get("entry", "")
                if not entry:
                    return "Error: 'entry' is required for write_ledger_entry."
                return await asyncio.to_thread(self._append_ledger_entry, entry)
            elif action == "write_session":
                filename = kwargs.get("filename", "")
                content = kwargs.get("content", "")
                if not filename or not content:
                    return "Error: 'filename' and 'content' are required for write_session."
                return await asyncio.to_thread(self._write_file, f"{_SESSIONS_DIR}/{filename}", content, True)
            elif action == "update_node_context":
                content = kwargs.get("content", "")
                if not content:
                    return "Error: 'content' is required for update_node_context."
                return await asyncio.to_thread(self._write_file, _KALI_NODE_FILE, content, True)
            else:
                return f"Unknown mnemosyne action: {action}"
        except Exception as e:
            logger.error("MnemosyneTool error", exc_info=True)
            return f"Mnemosyne error: {e}"

    # ------------------------------------------------------------------
    # File helpers (called in thread)
    # ------------------------------------------------------------------

    def _path(self, relative: str) -> Path:
        p = (self._root / relative).resolve()
        # Safety: ensure path stays within ledger root
        if not str(p).startswith(str(self._root)):
            raise ValueError(f"Path traversal denied: {relative}")
        return p

    def _read_file(self, relative: str) -> str:
        p = self._path(relative)
        if not p.exists():
            return f"File not found: {relative}"
        text = p.read_text(encoding="utf-8")
        # Truncate very large files so Claude doesn't overflow
        if len(text) > 12000:
            text = text[:12000] + "\n\n[… truncated …]"
        return f"# {relative}\n\n{text}"

    def _list_sessions(self) -> str:
        sessions_dir = self._path(_SESSIONS_DIR)
        if not sessions_dir.exists():
            return "sessions/ directory does not exist yet."
        files = sorted(sessions_dir.iterdir())
        if not files:
            return "No session files found."
        return "\n".join(f.name for f in files if f.is_file())

    def _append_ledger_entry(self, entry: str) -> str:
        p = self._path(_LEDGER_FILE)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        block = f"\n\n## [{ts}] :: BOT ENTRY\n{entry.strip()}\n"
        if p.exists():
            existing = p.read_text(encoding="utf-8")
            p.write_text(existing + block, encoding="utf-8")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# MNEMOSYNE LEDGER\n{block}", encoding="utf-8")
        self._git_commit([str(p)], f"mnemosyne: append ledger entry [{ts}]")
        return f"Ledger entry appended at {ts}."

    def _write_file(self, relative: str, content: str, git_commit: bool = False) -> str:
        p = self._path(relative)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if git_commit:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            self._git_commit([str(p)], f"mnemosyne: update {relative} [{ts}]")
        return f"Written: {relative}"

    # ------------------------------------------------------------------
    # Git helper
    # ------------------------------------------------------------------

    def _git_commit(self, files: list[str], message: str) -> None:
        """Stage the given files, commit, and push. Failures are logged but not raised."""
        try:
            subprocess.run(
                ["git", "add", "--"] + files,
                cwd=self._root,
                check=True,
                capture_output=True,
            )
            # Skip commit if nothing changed
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=self._root,
                capture_output=True,
            )
            if result.returncode == 0:
                return  # nothing to commit
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self._root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "push"],
                cwd=self._root,
                check=False,   # push failure is non-fatal
                capture_output=True,
            )
            logger.info("Mnemosyne git commit: %s", message)
        except Exception:
            logger.warning("Mnemosyne git operation failed (non-fatal)", exc_info=True)
