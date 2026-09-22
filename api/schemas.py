"""
schoolX/api/schemas.py — Pydantic-схемы для REST API и SSE эндпоинтов RAG-системы.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class TelegramMessageRequest(BaseModel):
    """Тело запроса от Telegram-бота (тонкого клиента).
    
    Содержит исключительно идентификаторы и текст запроса пользователя.
    НИКАКИХ параметров модели (temperature, top_k, prompt) от бота не принимается!
    """
    chat_id: Union[str, int] = Field(..., description="ID чата Telegram")
    user_id: Union[str, int] = Field(..., description="ID пользователя Telegram")
    message_id: Optional[Union[str, int]] = Field(None, description="ID исходного сообщения в Telegram")
    query: str = Field(..., min_length=1, description="Текст вопроса пользователя")
    session_id: Optional[str] = Field(None, description="Опциональный внешний UUID сессии")


class SourceCitation(BaseModel):
    """Информация о первоисточнике (документ, страница, цитата)."""
    source: str = Field(..., description="Название документа или первоисточника")
    page: Optional[Any] = Field(None, description="Номер страницы или раздел")
    quote: Optional[str] = Field(None, description="Фрагмент текста цитаты")


class TelegramMessageResponse(BaseModel):
    """Итоговый ответ RAG-системы для Telegram-бота."""
    answer: str = Field(..., description="Сгенерированный и санитизированный ответ модели")
    sources: List[SourceCitation] = Field(default_factory=list, description="Список использованных первоисточников")
    session_id: str = Field(..., description="Идентификатор сессии диалога")
    confidence: float = Field(default=0.0, description="Оценка уверенности ответа (0.0 - 1.0)")
    latency_ms: float = Field(default=0.0, description="Общее время генерации в миллисекундах")
    is_zero_retrieval: bool = Field(default=False, description="Флаг отсутствия релевантной информации в базе")


class SessionResetResponse(BaseModel):
    """Ответ на запрос сброса сессии."""
    status: str = Field(default="ok", description="Статус операции")
    message: str = Field(..., description="Описание результата")
    chat_id: Union[str, int] = Field(..., description="ID сброшенного чата")


class HealthResponse(BaseModel):
    """Статус работоспособности RAG-системы."""
    status: str = Field(..., description="Общий статус (healthy / degraded / unhealthy)")
    llm_provider: str = Field(..., description="Активный провайдер LLM")
    llm_healthy: bool = Field(..., description="Доступность сервера инференса LLM")
    embeddings_healthy: bool = Field(..., description="Доступность модели эмбеддингов")
    index_loaded: bool = Field(..., description="Флаг загрузки векторного индекса")
    total_chunks: int = Field(default=0, description="Количество чанков в активном индексе")
    message: str = Field(..., description="Диагностическое сообщение")


class ActiveConfigProfile(BaseModel):
    """Публичный профиль активных настроек генерации (без утечки секретов)."""
    llm_provider: str
    llm_model: str
    llm_temperature: float
    llm_top_p: float
    llm_max_tokens: int
    embedding_provider: str
    embedding_model: str
    retrieval_top_k: int
    context_max_chunks: int
