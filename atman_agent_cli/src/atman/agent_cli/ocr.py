"""
atman/agent_cli/ocr.py
Image text extraction via easyocr with pytesseract fallback.

CLI Integration Notes:
  Wired from SafeFileExplorer.read() via image extension detection.
  In Telegram handlers: OCRProcessor().extract_text(saved_path) for photos → chat text.
  Folder ~/.atman/telegram/media/ — add to .gitignore when first used in production flows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class OCRProcessor:
    """
    Primary engine: easyocr (better for photos, supports RU).
    Fallback: pytesseract (faster for clean screenshots; needs system tesseract).
    """

    def __init__(self, languages: list[str] | None = None) -> None:
        self.languages = languages or ["ru", "en"]
        self._reader: Any = None

    def _get_reader(self) -> Any:
        if self._reader is None:
            import easyocr

            try:
                import torch

                gpu = torch.cuda.is_available()
            except ImportError:
                gpu = False
            self._reader = easyocr.Reader(self.languages, gpu=gpu)
        return self._reader

    def extract_text(self, image_path: Path) -> str:
        """Extract text from an image with automatic backend selection."""
        try:
            reader = self._get_reader()
            results = reader.readtext(str(image_path), detail=0)
            text = "\n".join(results)
            if len(text.strip()) < 10:
                return self._tesseract_fallback(image_path) or text
            return text
        except ImportError:
            return self._tesseract_fallback(image_path) or "[OCR unavailable: pip install easyocr]"

    def _tesseract_fallback(self, image_path: Path) -> str | None:
        try:
            import pytesseract
            from PIL import Image

            lang = "+".join({"ru": "rus", "en": "eng"}.get(code, code) for code in self.languages)
            return pytesseract.image_to_string(Image.open(image_path), lang=lang)
        except (ImportError, OSError, ValueError, RuntimeError):
            return None

    def is_available(self) -> bool:
        """Return True if at least one OCR backend import succeeds."""
        try:
            import easyocr  # noqa: F401

            return True
        except ImportError:
            pass
        try:
            import pytesseract  # noqa: F401

            return True
        except ImportError:
            pass
        return False
