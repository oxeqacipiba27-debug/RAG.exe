"""
schoolX/api/app.py — Главное приложение FastAPI для Enterprise RAG 2.0.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.middleware import RequestLoggingMiddleware
from api.routes import router as api_router
from api.session_manager import SessionManager
from rag_engine import AppConfig, RAGPipeline

logger = logging.getLogger("RAGApiApp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл сервиса: загрузка и инициализация RAG-пайплайна при старте."""
    # Если зависимости уже инжектированы (например, в тестах), используем их
    if getattr(app.state, "pipeline", None) is not None:
        if getattr(app.state, "session_manager", None) is None:
            app.state.session_manager = SessionManager()
        yield
        return

    logger.info("=" * 60)
    logger.info("  Инициализация API-сервера Enterprise RAG...")
    logger.info("=" * 60)

    # 1. Загрузка конфигурации из .env
    config = AppConfig.from_env()
    logger.info(f"Активный LLM провайдер: {config.llm_provider} ({config.llm_model})")
    logger.info(f"Активный провайдер эмбеддингов: {config.embedding_provider} ({config.embedding_model})")

    # 2. Инициализация ядра RAGPipeline
    pipeline = RAGPipeline(config=config)
    is_healthy, health_msg = pipeline.check_health()
    if is_healthy:
        logger.info(f"[OK] RAG Core готов: {health_msg}")
    else:
        logger.warning(f"[!] Предупреждение при инициализации RAG: {health_msg}")

    # 3. Инициализация менеджера сессий
    session_manager = SessionManager()

    # 4. Привязка к состоянию приложения
    app.state.config = config
    app.state.pipeline = pipeline
    app.state.session_manager = session_manager

    try:
        yield
    finally:
        logger.info("Завершение работы API-сервера RAG...")
        sm = getattr(app.state, "session_manager", None)
        if sm and hasattr(sm, "close"):
            try:
                sm.close()
            except Exception:
                pass


def create_app(
    pipeline: Optional[Any] = None,
    session_manager: Optional[SessionManager] = None,
    config: Optional[AppConfig] = None
) -> FastAPI:
    """Фабрика создания экземпляра приложения FastAPI."""
    app = FastAPI(
        title="SchoolX Enterprise RAG API",
        description="Централизованный REST/SSE API-сервис RAG для Telegram-бота и внешних клиентов",
        version="2.0.0",
        lifespan=lifespan
    )

    if pipeline is not None:
        app.state.pipeline = pipeline
    if session_manager is not None:
        app.state.session_manager = session_manager
    if config is not None:
        app.state.config = config

    # Настройка CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware логирования
    app.add_middleware(RequestLoggingMiddleware)

    # Подключение роутов API
    app.include_router(api_router)

    # Статические файлы и веб-виджет
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/widget.js", tags=["Widget"])
    async def get_widget_js():
        """Возвращает встраиваемый JavaScript-файл чат-виджета для сайтов."""
        widget_file = static_dir / "widget.js"
        if widget_file.exists():
            return FileResponse(widget_file, media_type="application/javascript")
        raise HTTPException(status_code=404, detail="Файл виджета widget.js не найден.")

    @app.get("/widget", tags=["Widget"], response_class=HTMLResponse)
    async def get_widget_demo():
        """Демонстрационная страница встраивания чат-виджета."""
        demo_file = static_dir / "widget_demo.html"
        if demo_file.exists():
            return FileResponse(demo_file, media_type="text/html")
        return HTMLResponse("<h2>SchoolX RAG Web Widget Demo</h2><p>Файл демо-страницы не найден.</p>")

    # Прямой алиас /health на верхнем уровне
    @app.get("/health", tags=["System"])
    async def root_health():
        pipe = getattr(app.state, "pipeline", None)
        if not pipe:
            return {"status": "starting", "message": "Pipeline initializing"}
        is_healthy, msg = pipe.check_health()
        return {
            "status": "healthy" if is_healthy else "degraded",
            "message": msg,
            "total_chunks": len(pipe.chunks) if pipe.chunks else 0
        }

    return app


app = create_app()
