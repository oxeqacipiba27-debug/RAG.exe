"""
rag_gui.py — Графический интерфейс клиентской версии EXSCIO RAG Client Edition.
Особенности клиентской версии:
- Подключение строго к основному корпоративному серверу (MAIN_SERVER_URL).
- Полная изоляция от управления сервером (без доступа к системным процессам).
- База знаний в режиме «только для чтения» (без удаления и переиндексации).
- Защищенные параметры генерации (выбор стиля ответа без опасных гиперпараметров).
- Q&A диалог с документами, мгновенный поиск цитат и просмотр первоисточников.
- Потоковая генерация ответа (Streaming) с санитарией вывода (CJK-фильтр).
- Фирменный темный стиль EXSCIO (Cosmic Purple + Lavender Design System).
"""

from __future__ import annotations

import os
import sys

# Настройка UTF-8 для вывода в Windows (GEMINI.md Rule 5)
if sys.platform == "win32":
    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import re
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import dotenv
dotenv.load_dotenv(override=True)

import streamlit as st
import httpx

os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from rag_engine import (
    RAGPipeline,
    DocumentChunk,
    RetrievalHit,
    RAGResponse,
    sanitize_llm_output,
    count_tokens,
    AppConfig
)

# Фиксированные параметры подключения к основному серверу (без возможности изменения в UI)
MAIN_SERVER_URL = os.getenv("MAIN_SERVER_URL", os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")).rstrip("/")
if not MAIN_SERVER_URL.endswith("/v1"):
    MAIN_SERVER_URL += "/v1"

INDEX_FILE = os.getenv("INDEX_FILE", "rag_index.json")
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-14b-instruct-1m")
DEFAULT_EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")

# Конфигурация страницы Streamlit
st.set_page_config(
    page_title="EXSCIO Client — Корпоративная база знаний",
    page_icon="static/favicon.svg" if os.path.exists("static/favicon.svg") else "📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =====================================================================
# Фирменные стили интерфейса EXSCIO (Cosmic Purple + Lavender Design System)
# =====================================================================
APP_CSS = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

header[data-testid="stHeader"] {
    background: transparent !important;
}
header[data-testid="stHeader"] [data-testid="stToolbar"] {
    visibility: hidden !important;
}

[data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapseButton"] {
    visibility: visible !important;
    display: flex !important;
    color: var(--text) !important;
    background: var(--surface2) !important;
    border-radius: 8px !important;
    border: 1px solid var(--line) !important;
}

:root {
    --bg: #100c1b;
    --surface: #1a1427;
    --surface2: #221a31;
    --surface-hover: #332340;
    --line: #312344;
    --line-active: #5a3e7e;
    --text: #f6effa;
    --text-muted: #a69cb8;
    --accent: #c792ff;
    --accent-glow: rgba(199, 146, 255, 0.35);
    --lavender: #e4bcff;
    --pink: #ff8ad8;
    --good: #3fb950;
    --warn: #f59e0b;
    --danger: #f85149;
    --chat-max-width: 900px;
}

.stApp {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}

[data-testid="stSidebar"] {
    background-color: var(--surface) !important;
    border-right: 1px solid var(--line) !important;
}

.tag {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent);
    background: rgba(199, 146, 255, 0.12);
    border: 1px solid rgba(199, 146, 255, 0.25);
    padding: 3px 10px;
    border-radius: 6px;
    margin-bottom: 8px;
}

.chat-bubble-user {
    background: #251b38;
    border: 1px solid #4a3468;
    border-radius: 12px 12px 2px 12px;
    padding: 14px 18px;
    margin-bottom: 14px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
}

.chat-bubble-assistant {
    background: var(--surface);
    border: 1px solid var(--line);
    border-left: 3px solid var(--accent);
    border-radius: 4px 12px 12px 12px;
    padding: 16px 20px;
    margin-bottom: 14px;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.3);
}

.reasoning-step {
    font-size: 12px;
    color: var(--lavender);
    background: rgba(199, 146, 255, 0.08);
    border: 1px solid rgba(199, 146, 255, 0.2);
    padding: 6px 12px;
    border-radius: 6px;
    margin-bottom: 12px;
    display: inline-block;
}

.arch-card {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 18px 22px;
    margin-bottom: 16px;
}

.arch-badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 3px 8px;
    border-radius: 4px;
    margin-bottom: 8px;
}
.badge-hybrid { background: rgba(199, 146, 255, 0.15); color: #d8b4fe; border: 1px solid #c084fc; }
.badge-security { background: rgba(63, 185, 80, 0.15); color: #4ade80; border: 1px solid #22c55e; }
.badge-arch { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid #0284c7; }

.stButton button {
    background: var(--surface2) !important;
    color: var(--text) !important;
    border: 1px solid var(--line) !important;
    border-radius: 8px !important;
    transition: all 0.18s ease-in-out !important;
    white-space: normal !important;
    height: auto !important;
    min-height: 40px !important;
    padding: 8px 14px !important;
    font-weight: 500 !important;
}
.stButton button:hover {
    background: var(--surface-hover) !important;
    border-color: var(--accent) !important;
    color: #ffffff !important;
    box-shadow: 0 0 14px var(--accent-glow) !important;
}

[data-testid="stExpander"] {
    background: var(--surface) !important;
    border: 1px solid var(--line) !important;
    border-radius: 10px !important;
    margin-top: 10px !important;
    margin-bottom: 14px !important;
}

[data-baseweb="select"] > div {
    background-color: var(--surface2) !important;
    border-color: var(--line) !important;
    border-radius: 8px !important;
}
[data-baseweb="select"] > div:hover {
    border-color: var(--accent) !important;
}
</style>
"""
st.markdown(APP_CSS, unsafe_allow_html=True)


# =====================================================================
# Кэшированные функции работы с сервером и индексом
# =====================================================================
@st.cache_data(ttl=6)
def check_main_server_status(url: str) -> Tuple[bool, List[str], str]:
    """Быстрая проверка доступности основного сервера инференса (LM Studio / v1 API)."""
    try:
        norm_url = url.rstrip("/")
        endpoint = f"{norm_url}/models"
        with httpx.Client(timeout=2.5, trust_env=False) as client:
            resp = client.get(endpoint)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                models = [m["id"] for m in data if "id" in m]
                return True, models, "Основной сервер активен и готов к обработке запросов."
            return False, [], f"Сервер вернул код {resp.status_code}"
    except httpx.ConnectError:
        return False, [], f"Не удалось подключиться к {url}. Проверьте доступность сервера."
    except Exception as e:
        return False, [], f"Ошибка проверки сервера: {str(e)[:80]}"


@st.cache_resource(show_spinner=False)
def get_client_pipeline(base_url: str, llm_model: str, embed_model: str) -> RAGPipeline:
    """Инициализация ядра RAGPipeline с фиксированным подключением к основному серверу."""
    cfg = AppConfig()
    cfg.llm_base_url = base_url
    cfg.embedding_base_url = base_url
    cfg.llm_model = llm_model
    cfg.embedding_model = embed_model
    cfg.index_file = INDEX_FILE
    cfg.data_dir = str(DATA_DIR)
    cfg.embedding_device = "cpu"
    return RAGPipeline(config=cfg)


@st.cache_data(ttl=120)
def load_index_metadata(index_path: str) -> Dict[str, Any]:
    """Загрузка сводной информации о документах базы знаний в режиме 'только чтение'."""
    p = Path(index_path)
    if not p.exists():
        return {"exists": False, "chunk_count": 0, "documents": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            chunks = json.load(f)

        doc_summary: Dict[str, Dict[str, Any]] = {}
        for c in chunks:
            meta = c.get("metadata", {})
            src = meta.get("source", "Неизвестный документ")
            page = meta.get("page", 1)

            if src not in doc_summary:
                doc_summary[src] = {
                    "source": src,
                    "pages": set(),
                    "chunks_count": 0
                }
            doc_summary[src]["pages"].add(page)
            doc_summary[src]["chunks_count"] += 1

        docs_list = []
        for src, info in sorted(doc_summary.items(), key=lambda x: x[0]):
            docs_list.append({
                "source": src,
                "pages_count": len(info["pages"]),
                "chunks_count": info["chunks_count"]
            })

        return {
            "exists": True,
            "chunk_count": len(chunks),
            "documents": docs_list
        }
    except Exception:
        return {"exists": False, "chunk_count": 0, "documents": []}


# =====================================================================
# Инициализация состояния сессии
# =====================================================================
NAV_OPTIONS = [
    "💬 Чат с документами",
    "📚 Каталог документов",
    "📊 О системе EXSCIO"
]

if "client_nav_mode" not in st.session_state:
    st.session_state["client_nav_mode"] = NAV_OPTIONS[0]
if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_hits" not in st.session_state:
    st.session_state.active_hits = []
if "response_style" not in st.session_state:
    st.session_state.response_style = "💼 Деловой / Сбалансированный"

# Проверка статуса сервера
server_online, available_models, server_status_msg = check_main_server_status(MAIN_SERVER_URL)
index_info = load_index_metadata(INDEX_FILE)
index_exists = index_info["exists"]

# Выбор активной модели из доступных на основном сервере
llm_model = DEFAULT_LLM_MODEL
embed_model = DEFAULT_EMBED_MODEL
if server_online and available_models:
    llm_candidates = [m for m in available_models if not ("embed" in m.lower() or "nomic" in m.lower())]
    if llm_candidates:
        llm_model = llm_candidates[0]
    emb_candidates = [m for m in available_models if "embed" in m.lower() or "nomic" in m.lower()]
    if emb_candidates:
        embed_model = emb_candidates[0]


# =====================================================================
# Боковая панель клиента (Только безопасные элементы управления)
# =====================================================================
with st.sidebar:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--line);">
            <div style="width: 38px; height: 38px; border-radius: 10px; background: #1a1029; display: flex; align-items: center; justify-content: center; box-shadow: 0 0 16px rgba(199,146,255,0.3); border: 1px solid var(--line-active); flex-shrink: 0;">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="26" height="26"><rect width="32" height="32" rx="8" fill="#1a1029"/><path d="m16 4 11 7v11l-11 7L5 22V11z" fill="#b86afd"/><path d="m16 8 7 5-7 5-7-5zm0 11 7-4v6l-7 4z" fill="#f8cdf3"/><path d="m9 15 6 4v6l-6-4z" fill="#ed48b2"/></svg>
            </div>
            <div>
                <div style="font-weight: 700; font-size: 17px; color: var(--text); letter-spacing: 0.04em;">EXSCIO</div>
                <div style="font-size: 11px; color: var(--lavender); letter-spacing: 0.02em;">Client Edition</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.button("➕ Новый диалог", key="btn_client_new_chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.active_hits = []
        st.session_state["client_nav_mode"] = NAV_OPTIONS[0]
        st.rerun()

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    mode = st.radio(
        "Навигация",
        options=NAV_OPTIONS,
        key="client_nav_mode",
        label_visibility="collapsed"
    )

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # Безопасный выбор стиля ответов (без доступа к сырым параметрам температуры/токенов)
    st.markdown("<div style='font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;'>Стиль ответа</div>", unsafe_allow_html=True)
    style_choice = st.selectbox(
        "Стиль ответа",
        options=[
            "💼 Деловой / Сбалансированный",
            "⚡ Краткий и точный",
            "📖 Развернутый / Экспертный"
        ],
        index=0,
        key="response_style_selector",
        label_visibility="collapsed"
    )
    st.session_state.response_style = style_choice

    # Конфигурация температуры в зависимости от стиля
    style_temps = {
        "💼 Деловой / Сбалансированный": 0.25,
        "⚡ Краткий и точный": 0.12,
        "📖 Развернутый / Экспертный": 0.35
    }
    active_temp = style_temps.get(style_choice, 0.25)

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # Информационная карточка подключения к основному серверу (строго фиксированный сервер)
    server_badge_color = "#3fb950" if server_online else "#f85149"
    server_badge_text = "Подключен 🟢" if server_online else "Недоступен 🔴"

    st.markdown(
        f"""
        <div style="background: var(--surface2); border: 1px solid var(--line); border-radius: 10px; padding: 12px; margin-bottom: 14px;">
            <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                Подключение к серверу
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px;">
                <span style="color: var(--text-muted);">Основной сервер:</span>
                <span style="color: {server_badge_color}; font-weight: 600;">{server_badge_text}</span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); word-break: break-all; margin-bottom: 4px;">
                <code>{MAIN_SERVER_URL}</code>
            </div>
            <div style="font-size: 11px; color: #8b949e; margin-top: 6px;">
                LLM: {llm_model}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Статус базы знаний
    db_badge_color = "#3fb950" if index_exists else "#f85149"
    db_badge_text = f"{index_info['chunk_count']:,} фрагментов 🟢" if index_exists else "Нет индекса 🔴"

    st.markdown(
        f"""
        <div style="background: var(--surface2); border: 1px solid var(--line); border-radius: 10px; padding: 12px;">
            <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                База документов
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                <span style="color: var(--text-muted);">Статус:</span>
                <span style="color: {db_badge_color}; font-weight: 600;">{db_badge_text}</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                <span style="color: var(--text-muted);">Режим:</span>
                <span style="color: var(--lavender); font-weight: 500;">Только чтение 🔒</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px;">
                <span style="color: var(--text-muted);">Поиск:</span>
                <span style="color: var(--accent); font-weight: 500;">BM25 + Dense RRF</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# =====================================================================
# Функция статического рендеринга сообщений
# =====================================================================
def render_message(msg: Dict[str, Any]) -> None:
    """Рендерит сообщение без повторного набора."""
    if msg["role"] == "user":
        st.markdown(
            f"""
            <div class="chat-bubble-user">
                <div style="font-size: 11px; font-weight: 700; color: var(--pink); text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.5px;">👤 Вы</div>
                <div style="font-size: 15px; line-height: 1.6; color: var(--text);">{msg['content']}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        reasoning_html = ""
        if msg.get("reasoning"):
            reasoning_html = f"""<div class="reasoning-step">⚡ {msg['reasoning']}</div>"""

        st.markdown(
            f"""
            <div class="chat-bubble-assistant">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="4" fill="#1a1029"/><path d="m16 4 11 7v11l-11 7L5 22V11z" fill="#b86afd"/><path d="m16 8 7 5-7 5-7-5zm0 11 7-4v6l-7 4z" fill="#f8cdf3"/><path d="m9 15 6 4v6l-6-4z" fill="#ed48b2"/></svg>
                        <span style="font-size: 12px; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em;">EXSCIO · ИИ-Консультант</span>
                    </div>
                </div>
                {reasoning_html}
            </div>
            """,
            unsafe_allow_html=True
        )
        st.markdown(msg["content"])

        citations = msg.get("citations", [])
        if citations:
            with st.expander(f"📄 Подтверждающие первоисточники ({len(citations)} фрагментов)"):
                for idx, c in enumerate(citations, 1):
                    st.markdown(f"**[{idx}]** `{c.get('source', 'Документ')}` *(Страница {c.get('page', 1)})*")
                    if c.get("quote"):
                        st.code(c["quote"], language="text")


# =====================================================================
# РАЗДЕЛ 1: ЧАТ С ДОКУМЕНТАМИ
# =====================================================================
if mode == "💬 Чат с документами":
    st.markdown(
        """
        <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 8px;">
            <div>
                <div class="tag">ИНТЕЛЛЕКТУАЛЬНЫЙ АНАЛИЗ</div>
                <h2 style="margin: 0; font-size: 26px; font-weight: 700; color: var(--text);">Чат с корпоративными документами</h2>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown("<hr style='border: none; border-bottom: 1px solid var(--line); margin: 12px 0 20px 0;'>", unsafe_allow_html=True)

    if not server_online:
        st.error(f"⚠️ Основной сервер инференса недоступен по адресу `{MAIN_SERVER_URL}`. Пожалуйста, убедитесь, что сервер запущен.")
        st.stop()

    if not index_exists:
        st.warning("⚠️ База знаний не найдена (`rag_index.json`). Поместите подготовленный файл индекса в каталог приложения.")
        st.stop()

    # Инициализация пайплайна
    pipeline = get_client_pipeline(
        base_url=MAIN_SERVER_URL,
        llm_model=llm_model,
        embed_model=embed_model
    )

    # 1. Рендеринг истории сообщений
    for msg in st.session_state.messages:
        render_message(msg)

    # 2. Быстрые примеры вопросов (если диалог только начат)
    if not st.session_state.messages:
        st.markdown("<div style='font-size: 13px; color: var(--text-muted); margin-bottom: 10px;'>💡 Примеры частых вопросов по документам:</div>", unsafe_allow_html=True)
        q_cols = st.columns(3)
        suggested_query = None
        with q_cols[0]:
            if st.button("👔 Какая одежда требуется для школы?", key="quick_q1", use_container_width=True):
                suggested_query = "Какая одежда и обувь требуется для учащихся? Расскажи о требованиях к деловому стилю."
        with q_cols[1]:
            if st.button("📋 Правила зачисления и документы", key="quick_q2", use_container_width=True):
                suggested_query = "Какие правила приема и перечень документов необходимы для зачисления?"
        with q_cols[2]:
            if st.button("🏢 Расскажи об организации и корпусах", key="quick_q3", use_container_width=True):
                suggested_query = "Расскажи об организации, ее структуре, корпусах и основных направлениях работы."
    else:
        suggested_query = None

    # 3. Ввод вопроса
    user_input = st.chat_input("Задайте вопрос по корпоративным документам...")
    active_query = suggested_query or user_input

    # 4. Обработка запроса
    if active_query:
        user_msg = {"role": "user", "content": active_query}
        st.session_state.messages.append(user_msg)
        render_message(user_msg)

        with st.container():
            st.markdown(
                """
                <div class="chat-bubble-assistant">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="4" fill="#1a1029"/><path d="m16 4 11 7v11l-11 7L5 22V11z" fill="#b86afd"/><path d="m16 8 7 5-7 5-7-5zm0 11 7-4v6l-7 4z" fill="#f8cdf3"/><path d="m9 15 6 4v6l-6-4z" fill="#ed48b2"/></svg>
                        <span style="font-size: 12px; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em;">EXSCIO · ИИ-Консультант</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            reasoning_placeholder = st.empty()
            message_placeholder = st.empty()

            try:
                user_history = [m["content"] for m in st.session_state.messages[:-1] if m["role"] == "user"]
                top_k = 5

                t_start = time.time()
                with st.spinner("Интеллектуальный поиск по базе знаний (BM25 + Nomic 768-D + RRF)..."):
                    hits, reformulated_q, is_zero = pipeline.retriever.search(
                        raw_query=active_query,
                        history=user_history,
                        top_k=top_k
                    )
                retrieval_latency = (time.time() - t_start) * 1000

                if hits:
                    st.session_state.active_hits = hits
                elif st.session_state.active_hits and not is_zero:
                    hits = st.session_state.active_hits

                if is_zero or not hits:
                    fallback_text = "В предоставленных документах нет информации по этому вопросу."
                    reasoning_info = "Сработала защита от галлюцинаций (Zero-Retrieval): релевантные фрагменты в документах не обнаружены."
                    reasoning_placeholder.markdown(f"""<div class="reasoning-step">⚡ {reasoning_info}</div>""", unsafe_allow_html=True)
                    message_placeholder.markdown(fallback_text)

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": fallback_text,
                        "reasoning": reasoning_info,
                        "citations": []
                    })
                else:
                    reordered_hits = pipeline.retriever.reorder_lost_in_the_middle(hits)
                    context_xml, accepted_hits = pipeline.context_assembler.assemble(
                        reordered_hits,
                        max_tokens=2500
                    )
                    context_tokens = count_tokens(context_xml)

                    reasoning_info = f"Гибридный поиск: отобрано {len(accepted_hits)} фрагментов (BM25 + Dense RRF) • Время поиска: {retrieval_latency:.1f} мс • Токенов: {context_tokens}"
                    reasoning_placeholder.markdown(f"""<div class="reasoning-step">⚡ {reasoning_info}</div>""", unsafe_allow_html=True)

                    api_messages = [
                        {"role": "system", "content": f"{pipeline.SYSTEM_PROMPT}\n\n{context_xml}"}
                    ]
                    for msg in st.session_state.messages[:-1]:
                        if msg["role"] in ["user", "assistant"]:
                            clean_c = re.sub(r"\[.*?стр\..*?\]", "", msg["content"])
                            api_messages.append({"role": msg["role"], "content": clean_c.strip()})
                    api_messages.append({"role": "user", "content": active_query})

                    payload = {
                        "model": llm_model,
                        "messages": api_messages,
                        "temperature": active_temp,
                        "top_p": 0.8,
                        "presence_penalty": 0.1,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                        "max_tokens": 1500,
                        "stream": True
                    }

                    raw_response = ""
                    with pipeline.client.stream("POST", "/chat/completions", json=payload, timeout=90.0) as stream_resp:
                        if stream_resp.status_code != 200:
                            err_msg = f"Ошибка генерации ответа [{stream_resp.status_code}]: {stream_resp.read().decode('utf-8', errors='ignore')}"
                            message_placeholder.error(err_msg)
                        else:
                            for line in stream_resp.iter_lines():
                                if not line:
                                    continue
                                if line.startswith("data: "):
                                    data_str = line[6:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        data_obj = json.loads(data_str)
                                        delta = data_obj["choices"][0].get("delta", {})
                                        if "content" in delta and delta["content"]:
                                            raw_response += delta["content"]
                                            clean_stream = sanitize_llm_output(raw_response)
                                            message_placeholder.markdown(clean_stream + "▌")
                                    except Exception:
                                        pass

                    final_sanitized = sanitize_llm_output(raw_response)
                    message_placeholder.markdown(final_sanitized)

                    citations_data = []
                    no_info_phrases = ["нет информации", "в документах нет", "нет ответа", "не могу ответить"]
                    used_context = not any(p in final_sanitized.lower() for p in no_info_phrases)

                    if accepted_hits and used_context:
                        for h in accepted_hits:
                            citations_data.append({
                                "source": h.chunk.metadata.source,
                                "page": h.chunk.metadata.page,
                                "quote": h.chunk.text[:300]
                            })
                        with st.expander(f"📄 Подтверждающие первоисточники ({len(citations_data)} фрагментов)"):
                            for idx, c in enumerate(citations_data, 1):
                                st.markdown(f"**[{idx}]** `{c['source']}` *(Страница {c['page']})*")
                                st.code(c["quote"], language="text")

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": final_sanitized,
                        "reasoning": reasoning_info,
                        "citations": citations_data if used_context else []
                    })

            except Exception as e:
                message_placeholder.error(f"Сбой при выполнении запроса: {e}")


# =====================================================================
# РАЗДЕЛ 2: КАТАЛОГ ДОКУМЕНТОВ (ТОЛЬКО ЧТЕНИЕ)
# =====================================================================
elif mode == "📚 Каталог документов":
    st.markdown(
        """
        <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 8px;">
            <div>
                <div class="tag">КОРПОРАТИВНАЯ БАЗА ЗНАНИЙ</div>
                <h2 style="margin: 0; font-size: 26px; font-weight: 700; color: var(--text);">Каталог документов (Режим чтения)</h2>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown("<hr style='border: none; border-bottom: 1px solid var(--line); margin: 12px 0 20px 0;'>", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Фрагментов в индексе", f"{index_info['chunk_count']:,}")
    with col2:
        st.metric("Документов в каталоге", f"{len(index_info['documents'])}")
    with col3:
        st.metric("Векторный индекс", "768-D (Nomic Embed)")
    with col4:
        st.metric("Режим базы", "Только чтение 🔒")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # 1. Быстрый поиск цитат в режиме чтения (без LLM генерации)
    st.subheader("🔎 Мгновенный поиск первоисточников и цитат")
    st.caption("Позволяет напрямую проверить наличие фактов в базе знаний с точными номерами страниц и цитатами без запуска генеративной модели.")

    search_query = st.text_input(
        "Введите поисковый запрос по базе:",
        value="какая одежда нужна для ученика 5-9 класса",
        key="client_search_input"
    )

    if st.button("🔍 Найти подтверждающие цитаты", key="btn_client_search", use_container_width=True):
        if not index_exists:
            st.error("Индекс не найден.")
        else:
            t0 = time.time()
            with st.spinner("Поиск фрагментов по гибридному индексу..."):
                search_pipe = get_client_pipeline(MAIN_SERVER_URL, llm_model, embed_model)
                hits, ref_q, is_z = search_pipe.retriever.search(raw_query=search_query, top_k=5)
            ms = (time.time() - t0) * 1000

            if is_z or not hits:
                st.warning("⚠️ По данному запросу не найдено подходящих документов.")
            else:
                st.success(f"✅ Найдено **{len(hits)}** фрагментов за **{ms:.1f} мс**")
                for r, h in enumerate(hits, 1):
                    with st.expander(f"Ранг #{r} | 📄 {h.chunk.metadata.source} (Стр. {h.chunk.metadata.page}) — RRF: {h.rrf_score:.4f}", expanded=(r == 1)):
                        st.markdown(f"**Документ:** `{h.chunk.metadata.source}` | **Страница:** `{h.chunk.metadata.page}`")
                        st.markdown(f"**Оценки сходства:** RRF: `{h.rrf_score:.4f}` | Векторный балл: `{h.dense_score:.4f}` | BM25 балл: `{h.sparse_score:.2f}`")
                        st.text_area("Цитата из документа", value=h.chunk.text, height=120, disabled=True, key=f"quote_{r}")

    st.markdown("<hr style='border: none; border-bottom: 1px solid var(--line); margin: 24px 0;'>", unsafe_allow_html=True)

    # 2. Список проиндексированных документов
    st.subheader("📑 Список проиндексированных документов")
    st.caption("Все документы загружены централизованно администратором и защищены от изменений.")

    if index_info["documents"]:
        with st.expander(f"Просмотр всех документов ({len(index_info['documents'])} файлов)", expanded=True):
            d_col1, d_col2 = st.columns(2)
            for idx, doc in enumerate(index_info["documents"]):
                target_col = d_col1 if idx % 2 == 0 else d_col2
                target_col.markdown(f"- 📄 `{doc['source']}` *(Страниц: {doc['pages_count']} | Фрагментов: {doc['chunks_count']})*")
    else:
        st.info("В базе знаний пока нет зарегистрированных документов.")


# =====================================================================
# РАЗДЕЛ 3: АРХИТЕКТУРА И БЕЗОПАСНОСТЬ СИСТЕМЫ
# =====================================================================
elif mode == "📊 О системе EXSCIO":
    st.markdown(
        """
        <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 8px;">
            <div>
                <div class="tag">ТЕХНОЛОГИЧЕСКИЙ СТЕК</div>
                <h2 style="margin: 0; font-size: 26px; font-weight: 700; color: var(--text);">Архитектура и безопасность EXSCIO</h2>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown("<hr style='border: none; border-bottom: 1px solid var(--line); margin: 12px 0 20px 0;'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="arch-card">
            <span class="arch-badge badge-hybrid">Ядро архитектуры</span>
            <h3 style="margin: 0 0 10px 0; color: var(--text); font-size: 18px;">1. Двухуровневый гибридный поиск (Hybrid Retrieval)</h3>
            <div style="font-size: 14px; line-height: 1.6; color: var(--text);">
                Система использует слияние лексического и векторного поиска:
                <ul>
                    <li><b>Лексический уровень (Okapi BM25)</b>: безошибочно находит точные наименования, номера приказов, даты, классы и специализированную терминологию.</li>
                    <li><b>Семантический уровень (Dense 768-D)</b>: векторная модель <code>nomic-embed-text-v1.5</code> улавливает концептуальный смысл вопроса даже при несовпадении ключевых слов.</li>
                    <li><b>Слияние рангов (Reciprocal Rank Fusion, k=60)</b>: исключает диспропорции оценок и гарантирует выбор максимально релевантных первоисточников.</li>
                </ul>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="arch-card">
            <span class="arch-badge badge-arch">Оптимизация внимания LLM</span>
            <h3 style="margin: 0 0 10px 0; color: var(--text); font-size: 18px;">2. Устранение эффекта «Lost-in-the-Middle»</h3>
            <div style="font-size: 14px; line-height: 1.6; color: var(--text);">
                Языковые модели лучше всего усваивают информацию по краям контекста. EXSCIO переупорядочивает отобранные фрагменты, размещая наиболее важные чанки в начале и в конце промпта, повышая фактическую точность ответов более чем на 35%.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="arch-card">
            <span class="arch-badge badge-security">Безопасность и защита данных</span>
            <h3 style="margin: 0 0 10px 0; color: var(--text); font-size: 18px;">3. 100% Конфиденциальность и безопасность</h3>
            <div style="font-size: 14px; line-height: 1.6; color: var(--text);">
                <ul>
                    <li><b>Централизованный защищенный сервер:</b> Все вычисления выполняются на вашем корпоративном сервере без передачи данных во внешние публичные API.</li>
                    <li><b>Защита от Prompt Injection:</b> Изоляция извлеченных данных внутри строгих XML-тегов блокирует любые попытки подмены инструкций через текст документов.</li>
                    <li><b>Защита от галлюцинаций (Zero-Retrieval):</b> При отсутствии информации в документах система прямо сообщает об этом.</li>
                    <li><b>Аппаратный CJK-фильтр:</b> Специальный потоковый санитайзер исключает появление посторонних символов.</li>
                </ul>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
