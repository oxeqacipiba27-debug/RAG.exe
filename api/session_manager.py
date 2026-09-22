"""
schoolX/api/session_manager.py — Потокобезопасный менеджер сессий и истории диалогов.
Хранит контекст бесед в SQLite базе данных (data/sessions.db) с in-memory кэшированием.
"""

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger("SessionManager")


class SessionManager:
    """Управляет историей диалогов и сопоставлением telegram_chat_id с контекстом."""

    def __init__(self, db_path: Optional[str] = None, max_history_messages: int = 10):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent / "data"
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(base_dir / "sessions.db")
        
        self.db_path = db_path
        self.max_history_messages = max_history_messages
        self._lock = threading.Lock()
        self._memory_cache: Dict[str, List[Dict[str, str]]] = {}
        self._session_ids: Dict[str, str] = {}
        self._init_sqlite()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        """Инициализация таблиц для персистентного хранения сессий и сообщений."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        chat_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chat_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        FOREIGN KEY (chat_id) REFERENCES chat_sessions(chat_id) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON chat_messages(chat_id)")
                conn.commit()

    def get_or_create_session_id(self, chat_id: str, custom_session_id: Optional[str] = None) -> str:
        """Возвращает текущий session_id для chat_id или генерирует новый."""
        chat_id = str(chat_id).strip()
        with self._lock:
            if chat_id in self._session_ids:
                return self._session_ids[chat_id]

            now = time.time()
            with self._get_connection() as conn:
                cur = conn.execute("SELECT session_id FROM chat_sessions WHERE chat_id = ?", (chat_id,))
                row = cur.fetchone()
                if row:
                    sess_id = row["session_id"]
                else:
                    sess_id = custom_session_id or str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO chat_sessions (chat_id, session_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (chat_id, sess_id, now, now)
                    )
                    conn.commit()

                self._session_ids[chat_id] = sess_id
                return sess_id

    def get_history(self, chat_id: str) -> List[Dict[str, str]]:
        """Возвращает последние N сообщений диалога для chat_id."""
        chat_id = str(chat_id).strip()
        with self._lock:
            if chat_id in self._memory_cache:
                return list(self._memory_cache[chat_id])

            with self._get_connection() as conn:
                cur = conn.execute(
                    """
                    SELECT role, content FROM chat_messages 
                    WHERE chat_id = ? 
                    ORDER BY id ASC
                    """,
                    (chat_id,)
                )
                rows = cur.fetchall()
                history = [{"role": r["role"], "content": r["content"]} for r in rows]
                # Ограничиваем скользящим окном
                if len(history) > self.max_history_messages:
                    history = history[-self.max_history_messages:]

                self._memory_cache[chat_id] = history
                return list(history)

    def add_turn(
        self,
        chat_id: str,
        user_query: str,
        assistant_answer: str,
        custom_session_id: Optional[str] = None
    ) -> str:
        """Сохраняет пару (вопрос пользователя, ответ ассистента) в историю."""
        chat_id = str(chat_id).strip()
        now = time.time()
        session_id = self.get_or_create_session_id(chat_id, custom_session_id)

        with self._lock:
            # 1. Запись в SQLite
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE chat_sessions SET updated_at = ? WHERE chat_id = ?",
                    (now, chat_id)
                )
                conn.execute(
                    "INSERT INTO chat_messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                    (chat_id, "user", user_query, now)
                )
                conn.execute(
                    "INSERT INTO chat_messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                    (chat_id, "assistant", assistant_answer, now)
                )
                conn.commit()

            # 2. Обновление in-memory кэша
            if chat_id not in self._memory_cache:
                self._memory_cache[chat_id] = []
            
            self._memory_cache[chat_id].append({"role": "user", "content": user_query})
            self._memory_cache[chat_id].append({"role": "assistant", "content": assistant_answer})

            # Поддерживаем максимальный размер скользящего окна
            if len(self._memory_cache[chat_id]) > self.max_history_messages:
                self._memory_cache[chat_id] = self._memory_cache[chat_id][-self.max_history_messages:]

        return session_id

    def reset_session(self, chat_id: str) -> str:
        """Сбрасывает контекст и историю для chat_id, генерирует новый session_id."""
        chat_id = str(chat_id).strip()
        new_session_id = str(uuid.uuid4())
        now = time.time()

        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
                conn.execute(
                    """
                    INSERT INTO chat_sessions (chat_id, session_id, created_at, updated_at) 
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET 
                        session_id = excluded.session_id,
                        updated_at = excluded.updated_at
                    """,
                    (chat_id, new_session_id, now, now)
                )
                conn.commit()

            self._memory_cache[chat_id] = []
            self._session_ids[chat_id] = new_session_id
            logger.info(f"Session reset for chat_id={chat_id}. New session_id={new_session_id}")

        return new_session_id
