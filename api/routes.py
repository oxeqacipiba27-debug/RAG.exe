"""
schoolX/api/routes.py — REST и SSE эндпоинты API для взаимодействия с тонким клиентом Telegram-бота.
"""

import asyncio
import json
import logging
import re
import time
from typing import AsyncGenerator, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.middleware import verify_api_key
from api.schemas import (
    ActiveConfigProfile,
    HealthResponse,
    SessionResetResponse,
    SourceCitation,
    TelegramMessageRequest,
    TelegramMessageResponse,
)
from api.session_manager import SessionManager
from rag_engine import (
    Citation,
    PIISanitizer,
    RAGPipeline,
    RAGResponse,
    sanitize_llm_output,
)

logger = logging.getLogger("RAGApiRoutes")
router = APIRouter(prefix="/api/v1", tags=["RAG API"])


def get_pipeline(request: Request) -> RAGPipeline:
    """Извлечение синглтона RAGPipeline из состояния приложения."""
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ядро RAG-пайплайна еще не инициализировано."
        )
    return pipeline


def get_session_manager(request: Request) -> SessionManager:
    """Извлечение синглтона SessionManager из состояния приложения."""
    sm = getattr(request.app.state, "session_manager", None)
    if sm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Менеджер сессий еще не инициализирован."
        )
    return sm


# ==============================================================================
# Health Check & Config Profile
# ==============================================================================

@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """Проверка доступности RAG-системы, LLM и эмбеддингов."""
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        return HealthResponse(
            status="unhealthy",
            llm_provider="UNKNOWN",
            llm_healthy=False,
            embeddings_healthy=False,
            index_loaded=False,
            total_chunks=0,
            message="RAGPipeline не инициализирован."
        )

    try:
        is_healthy, msg = pipeline.check_health()
        chunks_count = len(pipeline.chunks) if pipeline.chunks else 0
        overall_status = "healthy" if is_healthy else "degraded"
        return HealthResponse(
            status=overall_status,
            llm_provider=pipeline.config.llm_provider,
            llm_healthy=is_healthy,
            embeddings_healthy=True,
            index_loaded=chunks_count > 0,
            total_chunks=chunks_count,
            message=msg
        )
    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            llm_provider=getattr(pipeline.config, "llm_provider", "UNKNOWN"),
            llm_healthy=False,
            embeddings_healthy=False,
            index_loaded=False,
            total_chunks=0,
            message=f"Ошибка проверки здоровья сервиса: {e}"
        )


@router.get("/config/profile", response_model=ActiveConfigProfile, dependencies=[Depends(verify_api_key)])
async def get_config_profile(pipeline: RAGPipeline = Depends(get_pipeline)):
    """Возвращает текущие активные параметры генерации и RAG (без секретов)."""
    cfg = pipeline.config
    return ActiveConfigProfile(
        llm_provider=cfg.llm_provider,
        llm_model=cfg.llm_model,
        llm_temperature=cfg.llm_temperature,
        llm_top_p=cfg.llm_top_p,
        llm_max_tokens=cfg.llm_max_tokens,
        embedding_provider=cfg.embedding_provider,
        embedding_model=cfg.embedding_model,
        retrieval_top_k=cfg.retrieval_top_k,
        context_max_chunks=cfg.context_max_chunks,
    )


# ==============================================================================
# Message Endpoints (Non-Streaming)
# ==============================================================================

@router.post("/telegram/message", response_model=TelegramMessageResponse, dependencies=[Depends(verify_api_key)])
@router.post("/chat/completions", response_model=TelegramMessageResponse, dependencies=[Depends(verify_api_key)])
async def process_telegram_message(
    payload: TelegramMessageRequest,
    pipeline: RAGPipeline = Depends(get_pipeline),
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """Прием сообщения от Telegram-бота.
    
    1. Загружает контекст диалога по chat_id.
    2. Применяет активный профиль настроек RAG (из конфигурации RAG).
    3. Выполняет retrieval и инференс с параметрами ядра.
    4. Сохраняет новый ход беседы в историю сессии.
    5. Возвращает готовый ответ и список источников.
    """
    chat_id = str(payload.chat_id)
    user_query = payload.query.strip()
    logger.info(f"Incoming query from chat_id={chat_id}, user_id={payload.user_id}: '{user_query[:60]}...'")

    # 1. Получаем историю сессии для chat_id
    history = session_mgr.get_history(chat_id)

    # 2. Выполняем синхронный RAG-конвейер в отдельном пуле потоков
    try:
        rag_resp: RAGResponse = await asyncio.to_thread(
            pipeline.query,
            user_query=user_query,
            chat_history=history
        )
    except Exception as exc:
        logger.exception(f"Error during RAG pipeline query execution: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка генерации ответа в ядре RAG: {exc}"
        )

    # 3. Сохраняем ход диалога в сессионном хранилище
    session_id = session_mgr.add_turn(
        chat_id=chat_id,
        user_query=user_query,
        assistant_answer=rag_resp.answer,
        custom_session_id=payload.session_id
    )

    # 4. Преобразуем цитаты в Pydantic схемы
    sources = [
        SourceCitation(source=c.source, page=c.page, quote=c.quote)
        for c in rag_resp.citations
    ]

    return TelegramMessageResponse(
        answer=rag_resp.answer,
        sources=sources,
        session_id=session_id,
        confidence=rag_resp.confidence,
        latency_ms=rag_resp.latency_ms,
        is_zero_retrieval=rag_resp.is_zero_retrieval
    )


# ==============================================================================
# Streaming Endpoint (Server-Sent Events)
# ==============================================================================

@router.post("/telegram/message/stream", dependencies=[Depends(verify_api_key)])
async def stream_telegram_message(
    payload: TelegramMessageRequest,
    pipeline: RAGPipeline = Depends(get_pipeline),
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """Потоковая передача ответа через Server-Sent Events (SSE).
    
    События потока:
    - data: {"delta": "фрагмент текста", "done": false}
    - data: {"done": true, "session_id": "...", "sources": [...], "confidence": 0.95, "latency_ms": 120.5}
    """
    chat_id = str(payload.chat_id)
    user_query = payload.query.strip()
    history = session_mgr.get_history(chat_id)

    async def sse_event_generator() -> AsyncGenerator[str, None]:
        t0 = time.time()
        # 1. Санитизация запроса
        sanitized_query = PIISanitizer.sanitize(user_query)

        if not pipeline.retriever or not pipeline.chunks:
            err_msg = "Ошибка: Индекс документов RAG не инициализирован."
            yield f"data: {json.dumps({'delta': err_msg, 'done': False}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'session_id': session_mgr.get_or_create_session_id(chat_id), 'sources': [], 'confidence': 0.0, 'latency_ms': 0.0}, ensure_ascii=False)}\n\n"
            return

        user_history_texts = [PIISanitizer.sanitize(m["content"]) for m in history if m.get("role") == "user"]

        # 2. Поиск и реранкинг
        hits, reformulated_q, is_zero = await asyncio.to_thread(
            pipeline.retriever.search,
            raw_query=sanitized_query,
            history=user_history_texts,
            top_k=pipeline.config.retrieval_top_k
        )

        if is_zero or not hits:
            no_info = "В предоставленных документах нет информации по этому вопросу."
            yield f"data: {json.dumps({'delta': no_info, 'done': False}, ensure_ascii=False)}\n\n"
            sess_id = session_mgr.add_turn(chat_id, user_query, no_info, payload.session_id)
            latency = (time.time() - t0) * 1000
            yield f"data: {json.dumps({'done': True, 'session_id': sess_id, 'sources': [], 'confidence': 0.0, 'latency_ms': round(latency, 2)}, ensure_ascii=False)}\n\n"
            return

        # 3. Lost in the Middle и сборка контекста
        reordered_hits = pipeline.retriever.reorder_lost_in_the_middle(hits)
        context_xml, accepted_hits = pipeline.context_assembler.assemble(
            reordered_hits,
            max_chunks=min(max(pipeline.config.retrieval_top_k, 4), 6)
        )

        # 4. Формирование сообщений для модели
        messages = [
            {"role": "system", "content": f"{pipeline.SYSTEM_PROMPT}\n\n{context_xml}"}
        ]
        for msg in history[-6:]:
            clean_content = re.sub(r"\[.*?стр\..*?\]", "", msg["content"])
            messages.append({"role": msg["role"], "content": PIISanitizer.sanitize(clean_content.strip())})
        messages.append({"role": "user", "content": sanitized_query})

        # 5. Стриминг из LLM через OpenAI SDK
        full_raw_text = ""
        try:
            stream = await asyncio.to_thread(
                pipeline.openai_client.chat.completions.create,
                model=pipeline.llm_model,
                messages=messages,
                temperature=pipeline.config.llm_temperature,
                top_p=pipeline.config.llm_top_p,
                presence_penalty=pipeline.config.llm_presence_penalty,
                stop=["<|im_end|>", "<|endoftext|>"],
                max_tokens=pipeline.config.llm_max_tokens,
                stream=True,
                timeout=90.0
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta:
                    delta_content = chunk.choices[0].delta.content or ""
                    if delta_content:
                        full_raw_text += delta_content
                        yield f"data: {json.dumps({'delta': delta_content, 'done': False}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.001)

        except Exception as stream_err:
            logger.exception(f"Error during LLM stream: {stream_err}")
            fallback_err = f"\n[Ошибка генерации: {stream_err}]"
            yield f"data: {json.dumps({'delta': fallback_err, 'done': False}, ensure_ascii=False)}\n\n"

        # 6. Финальная санитизация и сохранение истории
        clean_answer = sanitize_llm_output(full_raw_text)
        sess_id = session_mgr.add_turn(chat_id, user_query, clean_answer, payload.session_id)
        latency = (time.time() - t0) * 1000

        sources_data = [
            {"source": h.chunk.metadata.source, "page": h.chunk.metadata.page, "quote": h.chunk.text[:200]}
            for h in accepted_hits
        ]
        confidence = min(1.0, max(0.1, accepted_hits[0].rerank_score / 0.1)) if accepted_hits else 0.0

        final_event = {
            "done": True,
            "session_id": sess_id,
            "sources": sources_data,
            "confidence": round(confidence, 2),
            "latency_ms": round(latency, 2)
        }
        yield f"data: {json.dumps(final_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")


# ==============================================================================
# Session Management Endpoints
# ==============================================================================

@router.post("/chat/sessions/{chat_id}/reset", response_model=SessionResetResponse, dependencies=[Depends(verify_api_key)])
async def reset_chat_session(
    chat_id: str,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """Сброс контекста беседы для указанного chat_id."""
    new_sess_id = session_mgr.reset_session(chat_id)
    return SessionResetResponse(
        status="ok",
        message="Контекст диалога успешно сброшен. Начата новая тема.",
        chat_id=chat_id
    )


@router.get("/chat/sessions/{chat_id}", dependencies=[Depends(verify_api_key)])
async def get_chat_session(
    chat_id: str,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """Получение текущей истории сообщений диалога."""
    history = session_mgr.get_history(chat_id)
    sess_id = session_mgr.get_or_create_session_id(chat_id)
    return {
        "chat_id": chat_id,
        "session_id": sess_id,
        "history": history,
        "message_count": len(history)
    }
