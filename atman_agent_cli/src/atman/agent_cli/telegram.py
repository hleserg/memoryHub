"""
atman/agent_cli/telegram.py
Telegram bot for receiving tasks and files (python-telegram-bot v21+, async).

CLI Integration Notes:
  If config exposes a token, construct in cli.py:
    self.telegram = TelegramBot(
        token=secrets.get('telegram_token'),
        allowed_ids=config.telegram_allowed_ids,
        on_message=lambda text, cid: self.call_from_thread(self._inject_telegram_message, text),
        on_file=lambda path, mime, cid: self.call_from_thread(self._notify_file_received, path),
    )
    asyncio.create_task(self.telegram.start())
  On /quit: await self.telegram.stop()
  Bot commands to add later: /status (agent status), /stop (stop executor)
  Add ~/.atman/telegram/media/ to project .gitignore when enabling downloads.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

MEDIA_DIR = Path.home() / ".atman" / "telegram" / "media"

OnMessageCallback = Callable[[str, int], Awaitable[None]]
OnFileCallback = Callable[[Path, str, int], Awaitable[None]]


class TelegramBot:
    """
    Bot for receiving tasks and files from Telegram.
    Intended to run alongside the TUI via an asyncio task.
    Only authorized chat_ids are accepted.
    """

    def __init__(
        self,
        token: str,
        allowed_ids: list[int],
        on_message: OnMessageCallback,
        on_file: OnFileCallback,
    ) -> None:
        self.token = token
        self.allowed_ids = set(allowed_ids)
        self.on_message = on_message
        self.on_file = on_file
        self._app: Any = None

    def _is_allowed(self, chat_id: int) -> bool:
        return chat_id in self.allowed_ids

    async def start(self) -> None:
        from telegram.ext import Application, MessageHandler, filters

        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(MessageHandler(filters.TEXT, self._handle_text))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def send(self, chat_id: int, text: str) -> None:
        if self._app:
            await self._app.bot.send_message(chat_id=chat_id, text=text)

    async def _handle_text(self, update: Any, context: Any) -> None:
        if update.effective_chat is None or update.message is None:
            return
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        text = update.message.text or ""
        await self.on_message(text, chat_id)

    async def _handle_photo(self, update: Any, context: Any) -> None:
        if update.effective_chat is None or update.message is None or not update.message.photo:
            return
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        path = MEDIA_DIR / f"{uuid4()}.jpg"
        await file.download_to_drive(str(path))

        try:
            from .ocr import OCRProcessor

            text = OCRProcessor().extract_text(path)
            await self.on_message(f"[Photo OCR]\n{text}", chat_id)
        except Exception as e:
            logger.warning("OCR failed: %s", e)
            await self.on_file(path, "image/jpeg", chat_id)

    async def _handle_document(self, update: Any, context: Any) -> None:
        if (
            update.effective_chat is None
            or update.message is None
            or update.message.document is None
        ):
            return
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)
        suffix = Path(doc.file_name or "file").suffix
        path = MEDIA_DIR / f"{uuid4()}{suffix}"
        await file.download_to_drive(str(path))

        if suffix.lower() == ".pdf":
            from .file_access import SafeFileExplorer

            text = SafeFileExplorer(path.parent, path.parent).read(path)
            await self.on_message(f"[PDF Content]\n{text[:3000]}", chat_id)
        else:
            await self.on_file(path, doc.mime_type or "application/octet-stream", chat_id)
