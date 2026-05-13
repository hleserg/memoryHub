# AGENT-4 — Новые модули: file_access, ocr, telegram

## Контекст

Ты создаёшь три новых файла. Никаких конфликтов с другими агентами — всё новое.
Единственное касание существующих файлов: добавить импорты в `cli.py` (описано в CLI Integration Notes).

**Создать:**
- `atman_agent_cli/src/atman/agent_cli/file_access.py`
- `atman_agent_cli/src/atman/agent_cli/ocr.py`
- `atman_agent_cli/src/atman/agent_cli/telegram.py`

**Не трогать:** `cli.py` — опиши интеграцию в конце каждого раздела.

---

## TASK-3.2 + TASK-3.3 — SafeFileExplorer

**Файл:** `file_access.py`

```python
from pathlib import Path
import subprocess

class PermissionError(Exception):
    pass

class SafeFileExplorer:
    """
    Read anywhere. Write/delete/execute only inside repo_root.
    Outside repo — read-only.
    """

    def __init__(self, repo_root: Path, work_dir: Path):
        self.repo_root = repo_root.resolve()
        self.work_dir = work_dir.resolve()

    def read(self, path: str | Path) -> str:
        """Читать любой файл. Автодетект OCR для изображений."""
        p = Path(path).resolve()
        if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'):
            from .ocr import OCRProcessor
            return OCRProcessor().extract_text(p)
        if p.suffix.lower() == '.pdf':
            return self._read_pdf(p)
        return p.read_text(encoding='utf-8', errors='replace')

    def _read_pdf(self, path: Path) -> str:
        try:
            from pdfminer.high_level import extract_text
            return extract_text(str(path))
        except ImportError:
            return f"[PDF reading requires: pip install pdfminer.six]"

    def list_dir(self, path: Path | str) -> list[Path]:
        """Листинг директории."""
        return list(Path(path).iterdir())

    def search(self, pattern: str, root: Path | str | None = None, recursive: bool = True) -> list[Path]:
        """Поиск файлов по glob-паттерну."""
        root = Path(root or self.work_dir)
        if recursive:
            return list(root.rglob(pattern))
        return list(root.glob(pattern))

    def write(self, path: Path | str, content: str) -> None:
        """Запись только внутри repo_root."""
        p = Path(path).resolve()
        if not p.is_relative_to(self.repo_root):
            raise PermissionError(f"Write outside repo is forbidden: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')

    def delete(self, path: Path | str) -> None:
        """Удаление только внутри repo_root."""
        p = Path(path).resolve()
        if not p.is_relative_to(self.repo_root):
            raise PermissionError(f"Delete outside repo is forbidden: {p}")
        p.unlink()

    def execute(self, cmd: str, confirm_callback=None) -> str:
        """
        Запуск команды только с подтверждением.
        confirm_callback: callable() -> bool. Если None — всегда отказывать.
        """
        if confirm_callback is None or not confirm_callback():
            raise PermissionError("Execution requires explicit user confirmation")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout + result.stderr

    @staticmethod
    def find_git_root(start: Path) -> Path | None:
        """Найти корень git репозитория начиная от start."""
        current = start.resolve()
        while current != current.parent:
            if (current / '.git').exists():
                return current
            current = current.parent
        return None

    @staticmethod
    def get_work_dir() -> tuple[Path, Path]:
        """
        Возвращает (repo_root, work_dir).
        repo_root = git root или work_dir если не git.
        """
        work_dir = Path.cwd()
        repo_root = SafeFileExplorer.find_git_root(work_dir) or work_dir
        return repo_root, work_dir
```

**CLI Integration Notes:**
> При старте: `repo_root, work_dir = SafeFileExplorer.get_work_dir()`
> Показать в header TUI: `atman-agent — {work_dir.name} — {branch}`
> Команда `/pwd` → показать `work_dir` и `repo_root`.
> Если агент пытается `write()` вне репо → поймать `PermissionError` → показать предупреждение + запросить `[y/N]`.

---

## TASK-3.5 — OCR для изображений

**Файл:** `ocr.py`

```python
from pathlib import Path

class OCRProcessor:
    """
    Основной движок: easyocr (лучше для фото, поддерживает RU).
    Fallback: pytesseract (быстрее для чистых скринов, требует системный tesseract).
    """

    def __init__(self, languages: list[str] | None = None):
        self.languages = languages or ['ru', 'en']
        self._reader = None

    def _get_reader(self):
        if self._reader is None:
            import easyocr
            # gpu=True если CUDA доступна, иначе False
            try:
                import torch
                gpu = torch.cuda.is_available()
            except ImportError:
                gpu = False
            self._reader = easyocr.Reader(self.languages, gpu=gpu)
        return self._reader

    def extract_text(self, image_path: Path) -> str:
        """Извлечь текст из изображения. Автовыбор движка."""
        try:
            reader = self._get_reader()
            results = reader.readtext(str(image_path), detail=0)
            text = '\n'.join(results)
            if len(text.strip()) < 10:
                # Слишком мало текста — попробовать tesseract
                return self._tesseract_fallback(image_path) or text
            return text
        except ImportError:
            return self._tesseract_fallback(image_path) or f"[OCR unavailable: pip install easyocr]"

    def _tesseract_fallback(self, image_path: Path) -> str | None:
        try:
            import pytesseract
            from PIL import Image
            lang = '+'.join(
                {'ru': 'rus', 'en': 'eng'}.get(l, l) for l in self.languages
            )
            return pytesseract.image_to_string(Image.open(image_path), lang=lang)
        except (ImportError, Exception):
            return None

    def is_available(self) -> bool:
        """Проверить что хотя бы один движок доступен."""
        try:
            import easyocr  # noqa
            return True
        except ImportError:
            pass
        try:
            import pytesseract  # noqa
            return True
        except ImportError:
            pass
        return False
```

**CLI Integration Notes:**
> В `SafeFileExplorer.read()` уже интегрировано (автодетект по расширению).
> В Telegram: при получении фото → `OCRProcessor().extract_text(saved_path)` → вставить текст в чат.
> Папка `~/.atman/telegram/media/` — добавить в `.gitignore` при первом использовании.

---

## TASK-3.8 — Telegram бот

**Файл:** `telegram.py`

**Зависимость:** `python-telegram-bot>=21.0` (async).

```python
import asyncio
import logging
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

MEDIA_DIR = Path.home() / '.atman' / 'telegram' / 'media'

class TelegramBot:
    """
    Бот для приёма задач и файлов из Telegram.
    Работает параллельно с TUI через asyncio task.
    Принимает сообщения только от authorized chat_ids.
    """

    def __init__(
        self,
        token: str,
        allowed_ids: list[int],
        on_message: callable,   # callback(text: str, chat_id: int)
        on_file: callable,      # callback(path: Path, mime: str, chat_id: int)
    ):
        self.token = token
        self.allowed_ids = set(allowed_ids)
        self.on_message = on_message
        self.on_file = on_file
        self._app = None

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

    async def send(self, chat_id: int, text: str) -> None:
        if self._app:
            await self._app.bot.send_message(chat_id=chat_id, text=text)

    async def _handle_text(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        text = update.message.text or ''
        await self.on_message(text, chat_id)

    async def _handle_photo(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        photo = update.message.photo[-1]  # наибольшее разрешение
        file = await context.bot.get_file(photo.file_id)
        path = MEDIA_DIR / f"{uuid4()}.jpg"
        await file.download_to_drive(str(path))

        # OCR автоматически
        try:
            from .ocr import OCRProcessor
            text = OCRProcessor().extract_text(path)
            await self.on_message(f"[Photo OCR]\n{text}", chat_id)
        except Exception as e:
            logger.warning("OCR failed: %s", e)
            await self.on_file(path, 'image/jpeg', chat_id)

    async def _handle_document(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)
        suffix = Path(doc.file_name or 'file').suffix
        path = MEDIA_DIR / f"{uuid4()}{suffix}"
        await file.download_to_drive(str(path))

        if suffix.lower() == '.pdf':
            from .file_access import SafeFileExplorer
            text = SafeFileExplorer(path.parent, path.parent).read(path)
            await self.on_message(f"[PDF Content]\n{text[:3000]}", chat_id)
        else:
            await self.on_file(path, doc.mime_type or 'application/octet-stream', chat_id)
```

**CLI Integration Notes:**
> Инициализация в cli.py при старте если `config.telegram_token` задан:
> ```python
> self.telegram = TelegramBot(
>     token=secrets.get('telegram_token'),
>     allowed_ids=config.telegram_allowed_ids,
>     on_message=lambda text, cid: self.call_from_thread(self._inject_telegram_message, text),
>     on_file=lambda path, mime, cid: self.call_from_thread(self._notify_file_received, path),
> )
> asyncio.create_task(self.telegram.start())
> ```
> При `/quit` → `await self.telegram.stop()`.
> Команды бота: `/status` → ответить статусом агента. `/stop` → остановить executor.
> `~/.atman/telegram/media/` добавить в `.gitignore` проекта автоматически.
