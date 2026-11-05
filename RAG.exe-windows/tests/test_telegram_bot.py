"""
Unit tests for telegram_bot.py helper functions and message processing.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telegram_bot import (
    build_chat_keyboard,
    get_request_headers,
    split_message_by_length,
    MAX_TELEGRAM_MESSAGE_LEN,
)


class TestTelegramBotHelpers(unittest.TestCase):
    """Test suite for Telegram bot thin client components."""

    def test_build_chat_keyboard(self):
        """Test inline keyboard construction."""
        kb = build_chat_keyboard()
        self.assertIsNotNone(kb)
        self.assertIsNotNone(kb.inline_keyboard)
        # Should have 2 buttons: reset and status
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("🔄 Новая тема", buttons)
        self.assertIn("ℹ️ Статус ИИ-сервера", buttons)

    def test_split_message_short(self):
        """Test that short messages are not split."""
        short_text = "Это короткое сообщение от ассистента."
        chunks = split_message_by_length(short_text, max_length=100)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], short_text)

    def test_split_message_long_paragraphs(self):
        """Test splitting by paragraphs when exceeding max_length."""
        p1 = "Параграф один. " * 10
        p2 = "Параграф два. " * 10
        full_text = f"{p1}\n\n{p2}"

        # Limit to length of p1 + 5
        limit = len(p1) + 5
        chunks = split_message_by_length(full_text, max_length=limit)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0], p1)
        self.assertEqual(chunks[1], p2)

    def test_split_message_massive_single_paragraph(self):
        """Test that single huge paragraph is split without crash."""
        line = "Очень длинная строка текста без двойных переводов.\n" * 50
        chunks = split_message_by_length(line, max_length=200)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 250)

    def test_get_request_headers_default(self):
        """Test headers without API key."""
        headers = get_request_headers()
        self.assertIn("Content-Type", headers)
        self.assertEqual(headers["Content-Type"], "application/json")


if __name__ == "__main__":
    unittest.main()
