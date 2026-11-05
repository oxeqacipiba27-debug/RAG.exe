"""
schoolX/api package — REST & SSE API for Enterprise RAG 2.0.
"""

from api.app import create_app, app
from api.schemas import TelegramMessageRequest, TelegramMessageResponse, SourceCitation
from api.session_manager import SessionManager

__all__ = [
    "create_app",
    "app",
    "TelegramMessageRequest",
    "TelegramMessageResponse",
    "SourceCitation",
    "SessionManager",
]
