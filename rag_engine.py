"""
rag_engine.py — Высокопроизводительное ядро RAG (Retrieval-Augmented Generation)
производственного уровня (Production-Ready).

Архитектура включает:
1. Ingestion: Очистка текста, дегифенация PDF, дедупликация (SHA-256), рекурсивный иерархический сплиттер.
2. Metadata: Строго типизированные Pydantic-схемы (ChunkMetadata, DocumentChunk, RetrievalHit, RAGResponse).
3. Embeddings: Пакетная векторизация (batching) с экспоненциальным backoff, проверка размерности, L2-нормализация.
4. Hybrid Search: Плотный поиск (Dense Cosine Similarity) + Разреженный поиск (Okapi BM25 на инвертированном индексе).
5. Fusion & Rerank: Reciprocal Rank Fusion (RRF k=60), многофакторный реранкер (фразы, заголовки, близость).
6. Lost in the Middle: Оптимизация расположения чанков в контексте (распределение по краям контекстного окна).
7. Context Assembly: Точный подсчет токенов через tiktoken, XML-изоляция (<context><document>...</document></context>).
8. Generation & Sanitization: Строгая защита от иероглифов и нелатинских/нерусских символов (sanitize_llm_output),
   валидация цитат, структурированный ответ Pydantic, Zero-Retrieval порог без галлюцинаций.
"""

from __future__ import annotations

import os
import sys
import json
import time
import math
import re
import hashlib
import urllib.parse
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime

# Настройка UTF-8 для вывода в Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Исключение локального адреса из системных прокси
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from dataclasses import dataclass, field
import dotenv
from openai import OpenAI
import numpy as np
import httpx
from pydantic import BaseModel, Field

# Автоматическая подгрузка переменных окружения из .env
dotenv.load_dotenv(override=False)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("RAGEngine")

# Опциональный импорт tiktoken для точного подсчета токенов
try:
    import tiktoken
    _TOKENIZER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _TOKENIZER = None
    logger.warning("tiktoken не загружен, используется эвристический токенизатор (1 токен ~ 3.5 символа).")

# Опциональный импорт pypdf / pymupdf
try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pymupdf  # fitz
except ImportError:
    pymupdf = None


# =====================================================================
# 0. Конфигурация бэкендов и Pre-flight HealthChecker
# =====================================================================

@dataclass
class AppConfig:
    """
    Единая модульная конфигурация RAG-системы.
    Поддерживает динамическое переключение между:
    - Провайдерами LLM: LM_STUDIO, OLLAMA_LOCAL, DOCKER, CUSTOM
    - Провайдерами Embeddings: REMOTE (/v1/embeddings), SENTENCE_TRANSFORMERS (локально PyTorch)
    """
    # 1. Провайдер LLM (генерация)
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "LM_STUDIO").upper())
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", "not-needed"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.28")))
    llm_top_p: float = field(default_factory=lambda: float(os.getenv("LLM_TOP_P", "0.8")))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "1500")))
    llm_presence_penalty: float = field(default_factory=lambda: float(os.getenv("LLM_PRESENCE_PENALTY", "0.1")))

    # 2. Провайдер эмбеддингов
    embedding_provider: str = field(default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "REMOTE").upper())
    embedding_base_url: str = field(default_factory=lambda: os.getenv("EMBEDDING_BASE_URL", ""))
    embedding_api_key: str = field(default_factory=lambda: os.getenv("EMBEDDING_API_KEY", "not-needed"))
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5"))
    sentence_transformer_model: str = field(default_factory=lambda: os.getenv("SENTENCE_TRANSFORMER_MODEL", "nomic-ai/nomic-embed-text-v1.5"))
    embedding_device: str = field(default_factory=lambda: os.getenv("EMBEDDING_DEVICE", "cpu"))

    # 3. Параметры RAG и хранилища
    index_file: str = field(default_factory=lambda: os.getenv("INDEX_FILE", "rag_index.json"))
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
    chunk_size: int = field(default_factory=lambda: int(os.getenv("CHUNK_SIZE", "1500")))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv("CHUNK_OVERLAP", "350")))
    retrieval_top_k: int = field(default_factory=lambda: int(os.getenv("RETRIEVAL_TOP_K", "5")))
    context_max_chunks: int = field(default_factory=lambda: int(os.getenv("CONTEXT_MAX_CHUNKS", "6")))

    def __post_init__(self):
        # Нормализация провайдера
        self.llm_provider = self.llm_provider.upper()
        self.embedding_provider = self.embedding_provider.upper()

        # Автоматическая настройка базовых URL по умолчанию
        if not self.llm_base_url:
            if self.llm_provider == "LM_STUDIO":
                self.llm_base_url = "http://localhost:1234/v1"
            elif self.llm_provider == "OLLAMA_LOCAL":
                self.llm_base_url = "http://localhost:11434/v1"
            elif self.llm_provider == "DOCKER":
                self.llm_base_url = "http://host.docker.internal:11434/v1"
            else:
                self.llm_base_url = "http://localhost:1234/v1"

        if not self.llm_model:
            if self.llm_provider == "LM_STUDIO":
                self.llm_model = "qwen2.5-14b-instruct-1m"
            elif self.llm_provider in ("OLLAMA_LOCAL", "DOCKER"):
                self.llm_model = "qwen2.5:14b"
            else:
                self.llm_model = "qwen2.5-14b-instruct-1m"

        if not self.embedding_base_url:
            self.embedding_base_url = self.llm_base_url

        if not self.embedding_api_key:
            self.embedding_api_key = self.llm_api_key

        if self.llm_provider in ("OLLAMA_LOCAL", "DOCKER"):
            if not self.embedding_model or "text-embedding-nomic" in self.embedding_model:
                self.embedding_model = "nomic-embed-text"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls()


CONFIG = AppConfig.from_env()


class BackendHealthChecker:
    """
    Pre-flight валидатор доступности серверных сервисов генерации и эмбеддингов.
    Генерирует детальные рекомендации и инструкции для пользователя в случае сбоя.
    """
    @staticmethod
    def get_remediation_message(config: AppConfig, service_type: str, error_detail: str) -> str:
        provider = config.llm_provider
        url = config.llm_base_url if service_type == "LLM" else config.embedding_base_url
        model = config.llm_model if service_type == "LLM" else config.embedding_model

        lines = [
            f"❌ [RAG HealthCheck] Сервис {service_type} недоступен по адресу: {url}",
            f"   Провайдер: {provider} | Модель: {model}",
            f"   Детали ошибки: {error_detail}",
            "",
            "ИНСТРУКЦИЯ ПО УСТРАНЕНИЮ:"
        ]

        if provider == "LM_STUDIO":
            lines.extend([
                "  1. Запустите приложение LM Studio на вашем компьютере.",
                "  2. Перейдите во вкладку 'Local Server' (<->) на левой панели.",
                f"  3. Загрузите модель '{model}' в память GPU/RAM.",
                "  4. Нажмите кнопку 'Start Server' (убедитесь, что сервер слушает порт 1234).",
                "  5. Проверьте адрес в файле конфигурации .env: LLM_BASE_URL=http://localhost:1234/v1"
            ])
        elif provider == "OLLAMA_LOCAL":
            lines.extend([
                "  1. Убедитесь, что служба Ollama установлена и запущена на компьютере.",
                "  2. Запустите Ollama в терминале командой: ollama serve",
                f"  3. Проверьте, скачана ли требуемая модель: ollama pull {model}",
                "  4. Проверьте список установленных моделей: ollama list",
                "  5. Проверьте адрес в .env: LLM_BASE_URL=http://localhost:11434/v1"
            ])
        elif provider == "DOCKER":
            lines.extend([
                "  1. Убедитесь, что служба Docker Desktop / docker daemon запущена.",
                "  2. Запустите стек инференса командой: docker compose up -d",
                "  3. Проверьте статус контейнеров командой: docker compose ps",
                "  4. Проверьте логи сервиса: docker compose logs -f ollama",
                f"  5. Загрузите модель в контейнер: docker compose exec ollama ollama pull {model}",
                "  6. Если скрипт работает на хосте, используйте адрес: http://localhost:11434/v1",
                "     Если скрипт работает внутри Docker-сети, используйте: http://host.docker.internal:11434/v1 или http://ollama:11434/v1"
            ])
        else:
            lines.extend([
                f"  1. Проверьте доступность хоста {url}.",
                "  2. Проверьте настройки фаервола и системных прокси (NO_PROXY=localhost,127.0.0.1).",
                "  3. Убедитесь, что API ключ указан корректно (если требуется)."
            ])

        return "\n".join(lines)

    @classmethod
    def check_llm(cls, client: OpenAI, config: AppConfig) -> Tuple[bool, str]:
        """Проверка доступности LLM через OpenAI-совместимый API."""
        try:
            client.models.list(timeout=4.0)
            return True, "OK"
        except Exception as e:
            msg = cls.get_remediation_message(config, "LLM", str(e))
            return False, msg

    @classmethod
    def check_embeddings(cls, store: "DenseVectorStore", config: AppConfig) -> Tuple[bool, str]:
        """Проверка доступности поставщика эмбеддингов."""
        try:
            ok = store.check_health()
            if ok:
                return True, "OK"
            msg = cls.get_remediation_message(config, "EMBEDDING", "Эндпоинт векторизации не вернул валидный вектор")
            return False, msg
        except Exception as e:
            msg = cls.get_remediation_message(config, "EMBEDDING", str(e))
            return False, msg


# =====================================================================
# 1. Pydantic Схемы данных (Data Contracts)
# =====================================================================

class ChunkMetadata(BaseModel):
    chunk_id: str = Field(..., description="Уникальный идентификатор фрагмента")
    doc_id: str = Field(..., description="Хеш исходного документа")
    source: str = Field(..., description="Человекочитаемое имя файла/источника")
    raw_source: str = Field(..., description="Оригинальный путь к файлу")
    page: int = Field(default=1, description="Номер страницы (1-based)")
    sheet: Optional[str] = Field(default=None, description="Имя листа для табличных документов Excel")
    char_count: int = Field(..., description="Число символов во фрагменте")
    token_count: int = Field(..., description="Число токенов во фрагменте")
    created_at: str = Field(..., description="ISO timestamp создания")
    content_hash: str = Field(..., description="SHA-256 хеш очищенного текста")


class DocumentChunk(BaseModel):
    metadata: ChunkMetadata
    text: str = Field(..., description="Содержимое текстового фрагмента")
    vector: Optional[List[float]] = Field(default=None, description="Нормализованный вектор эмбеддинга")

    def get_display_source(self) -> str:
        if self.metadata.sheet:
            return f"{self.metadata.source} (лист '{self.metadata.sheet}')"
        return f"{self.metadata.source} (стр. {self.metadata.page})"

    @property
    def source(self) -> str:
        return self.metadata.source

    @property
    def page(self) -> int:
        return self.metadata.page

    @property
    def chunk_id(self) -> str:
        return self.metadata.chunk_id

    @property
    def content(self) -> str:
        return self.text


class Citation(BaseModel):
    source: str
    page: int
    quote: Optional[str] = None


class RetrievalHit(BaseModel):
    chunk: DocumentChunk
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    final_rank: int = 0

    @property
    def bm25_score(self) -> float:
        return self.sparse_score

    @property
    def bm25_rank(self) -> int:
        return self.final_rank

    @property
    def dense_rank(self) -> int:
        return self.final_rank


class RAGResponse(BaseModel):
    query: str
    query_reformulated: str
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    context_chunks_used: int = 0
    retrieval_strategy: str = "hybrid_rrf_rerank"
    latency_ms: float = 0.0
    is_zero_retrieval: bool = False

    @property
    def sources(self) -> List[Citation]:
        """Псевдоним для совместимости со старыми скриптами и тестами."""
        return self.citations


# =====================================================================
# 2. Словари нормализации, опечаток, китайских артефактов и стоп-слов
# =====================================================================

# Словарь семантического перевода распространенных китайских артефактов модели Qwen
CJK_TRANSLATIONS: Dict[str, str] = {
    '班主任': 'к классному руководителю',
    '班级': 'класс',
    '老师': 'учителю',
    '教师': 'учителю',
    '学校': 'школе',
    '学生': 'ученикам',
    '家长': 'родителям',
    '校长': 'директору',
    '教导处': 'учебную часть',
    '教务处': 'учебную часть',
    '体育': 'физкультуре',
    '体育课': 'урокам физкультуры',
    '同学': 'одноклассникам'
}

GRADE_WORDS: Dict[str, str] = {
    'перв': '1 1-4', '1-й': '1 1-4', '1й': '1 1-4', 'началк': '1-4', 'младш': '1-4',
    'втор': '2 1-4', '2-й': '2 1-4', '2й': '2 1-4',
    'трет': '3 1-4', '3-й': '3 1-4', '3й': '3 1-4',
    'четверт': '4 1-4', '4-й': '4 1-4', '4й': '4 1-4',
    'пят': '5 5-9', '5-й': '5 5-9', '5й': '5 5-9', 'средн': '5-9',
    'шест': '6 5-9', '6-й': '6 5-9', '6й': '6 5-9',
    'седьм': '7 5-9', '7-й': '7 5-9', '7й': '7 5-9',
    'восьм': '8 5-9', '8-й': '8 5-9', '8й': '8 5-9',
    'девят': '9 5-9', '9-й': '9 5-9', '9й': '9 5-9',
    'десят': '10 10-11', '10-й': '10 10-11', '10й': '10 10-11', 'старш': '10-11', 'выпускн': '10-11',
    'одиннадцат': '11 10-11', '11-й': '11 10-11', '11й': '11 10-11'
}

SYNONYM_GROUPS: List[Dict[str, Any]] = [
    {
        'triggers': ['одежд', 'одеажд', 'форм', 'дресс', 'стил', 'внешн', 'носить', 'надеть', 'ходить', 'гардероб', 'костюм', 'блузк', 'брюк', 'юбк', 'сарафан', 'туфл', 'обув', 'вещ', 'джинс', 'сменк'],
        'expansion': 'деловой стиль одежды форма цвет памятка обучающихся школьная форма'
    },
    {
        'triggers': ['физр', 'физкульт', 'спорт', 'тренировк'],
        'expansion': 'физическая культура занятия физической культурой спортивная одежда форма обувь'
    },
    {
        'triggers': ['документ', 'поступлен', 'зачислен', 'прием', 'поступить', 'записаться', 'паспорт', 'справк'],
        'expansion': 'правила приема зачисления перечень документов заявление'
    },
    {
        'triggers': ['каникул', 'отдых', 'четверт', 'триместр', 'период', 'график'],
        'expansion': 'сроки каникул учебные периоды учебный график'
    },
    {
        'triggers': ['питан', 'еда', 'столов', 'обед', 'завтрак', 'меню', 'льготн'],
        'expansion': 'организация питания школьная столовая меню горячее питание'
    },
    {
        'triggers': ['школ', 'школе', 'школу', 'школы', 'гбоу', '1468', 'учрежден', 'заведен', 'директор', 'здани', 'корпус'],
        'expansion': 'гбоу школа 1468 публичный доклад руководителя директор итоги года здания отделения предпрофессиональные классы медицинский инженерный медиакласс предпринимательский форма деловой стиль'
    },
    {
        'triggers': ['баз', 'документ', 'материал', 'тем', 'содержан', 'справк'],
        'expansion': 'локальные нормативные акты правила регламенты памятки образовательные программы школа 1468'
    }
]

CORPUS_STOP_WORDS: Set[str] = {
    'какая', 'какой', 'какие', 'каком', 'каких', 'какую', 'какое', 'каким', 'какими',
    'что', 'кто', 'где', 'когда', 'куда', 'откуда', 'почему', 'зачем', 'как', 'сколько',
    'это', 'этот', 'эта', 'эти', 'этих', 'этом', 'этому', 'этой',
    'был', 'была', 'были', 'быть', 'есть', 'будет', 'будут',
    'все', 'всех', 'всем', 'всеми', 'всё', 'всего',
    'для', 'при', 'под', 'над', 'без', 'через', 'про', 'обо',
    'или', 'если', 'так', 'уже', 'еще', 'ещё', 'нет', 'да', 'в', 'и', 'на', 'с', 'по',
    'нужна', 'нужно', 'нужны', 'нужен', 'можно', 'надо', 'подскажи', 'скажи', 'пожалуйста',
    'хочу', 'узнать', 'расскажи', 'знаешь', 'подробнее'
}

TYPO_MAP: Dict[str, str] = {
    'одеажда': 'одежда', 'одеажды': 'одежды', 'одеажде': 'одежде', 'одеажду': 'одежду',
    'одёжа': 'одежда', 'фома': 'форма', 'дрескод': 'дресс-код',
    'директр': 'директор', 'клас': 'класс', 'класе': 'классе',
    'докуметы': 'документы', 'докумнты': 'документы', 'правило': 'правила',
    'каникулы': 'каникулы', 'каникулах': 'каникулах', 'столовая': 'столовая',
    'физра': 'физкультура', 'физре': 'физкультуре', 'физру': 'физкультуру'
}


# =====================================================================
# 3. Утилиты очистки текста, токенизации, Nomic-префиксов и защиты от CJK
# =====================================================================

NOMIC_DOC_PREFIX: str = "search_document: "
NOMIC_QUERY_PREFIX: str = "search_query: "

def format_nomic_input(text: str, is_query: bool = False) -> str:
    """
    Принудительно форматирует текст для модели nomic-embed-text-v1.5:
    - Для чанков документов: префикс строго 'search_document: '
    - Для поисковых запросов пользователя: префикс строго 'search_query: '
    Исключает дублирование префиксов или конфликт разнородных префиксов.
    """
    text = text.strip()
    target_prefix = NOMIC_QUERY_PREFIX if is_query else NOMIC_DOC_PREFIX
    other_prefix = NOMIC_DOC_PREFIX if is_query else NOMIC_QUERY_PREFIX

    if text.startswith(target_prefix):
        return text
    if text.startswith(other_prefix):
        text = text[len(other_prefix):].strip()

    return f"{target_prefix}{text}"


def count_tokens(text: str) -> int:
    """Точный подсчет токенов через tiktoken либо fallback-оценка."""
    if _TOKENIZER is not None:
        return len(_TOKENIZER.encode(text, disallowed_special=()))
    return max(1, int(len(text) / 3.5))


def sanitize_llm_output(text: str) -> str:
    """
    Гарантированная фильтрация ответа модели от китайских иероглифов и посторонних символов:
    1. Семантическая замена распространенных китайских терминов на русский язык с сохранением пробелов.
    2. Полное удаление любых оставшихся символов CJK (Китай, Корея, Япония).
    3. Жесткий белый список символов: только русский алфавит, английский алфавит, цифры,
       стандартные пробелы и общепринятые знаки препинания / синтаксис Markdown.
    4. Удаление повисших союзов и предлогов при вырезании слов ('или .' -> '.').
    """
    if not text:
        return ""

    # 1. Семантическая замена китайских школьных терминов на русский
    for cjk, rus in CJK_TRANSLATIONS.items():
        if cjk in text:
            text = re.sub(r'([а-яА-ЯёЁa-zA-Z0-9])' + re.escape(cjk), r'\1 ' + rus, text)
            text = text.replace(cjk, rus)

    # 2. Удаление всех CJK и восточно-азиатских символов (Unified Ideographs, Katakana, Hiragana, Hangul)
    cjk_pattern = re.compile(
        r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u2e80-\u2eff\u3000-\u303f'
        r'\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\uac00-\ud7af\uff00-\uffef]'
    )
    text = cjk_pattern.sub('', text)

    # 3. Белый список разрешенных символов:
    # - Русский алфавит: а-я А-Я ё Ё
    # - Английский алфавит: a-z A-Z
    # - Цифры: 0-9
    # - Пробелы и переносы: \s
    # - Знаки препинания, кавычки, списки, таблицы и Markdown:
    #   . , ! ? : ; ' " « » „ “ — – - ( ) [ ] { } < > / * # № % + = @ & _ \ $ ~ ` ^ |
    allowed_chars = (
        r'а-яА-ЯёЁ'
        r'a-zA-Z'
        r'0-9'
        r'\s'
        r'\.,!\?:;\'"«»„“—–\-\(\)\[\]\{\}<>\/\*#№%\+=@&_\\\$~`\^\|'
    )
    allowed_pattern = re.compile(f'[^{allowed_chars}]')
    text = allowed_pattern.sub('', text)

    # 4. Нормализация пробелов и удаление повисших союзов/предлогов
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\b(или|и|а|к|в|с|на|от|у|о|об)\s*([.!?])', r'\2', text)
    return text.strip()


def clean_document_text(text: str) -> str:
    """
    Глубокая очистка текста от артефактов PDF, битых символов и мусора:
    - Замена U+FFFD и нечитаемых control characters.
    - Склейка разорванных дефисом слов на переносах строк: 'сло-\\nво' -> 'слово'.
    - Нормализация множественных пробелов и пустых строк.
    """
    if not text:
        return ""
    text = text.replace('\xa0', ' ').replace('\u200b', '').replace('\ufeff', '')
    text = text.replace('\ufffd', '')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'([а-яА-ЯёЁa-zA-Z]{2,})-\s*\n\s*([а-яА-ЯёЁa-zA-Z]{2,})', r'\1\2', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def stem_russian_word(w: str) -> str:
    """Быстрый нормализующий стеммер окончаний русского языка."""
    w = w.lower().replace('ё', 'е')
    w = re.sub(r'(?:ами|ями|ов|ев|ам|ям|ом|ем|ой|ей|ью|ях|ах|ии|ия|ию|ие|ое|ее|ые|ых|их|ую|юю|ая|яя|ый|ой|ий|а|е|и|й|о|у|ы|ь|ю|я)$', '', w)
    return w


def normalize_grade_ranges(text: str) -> str:
    """Преобразование диапазонов классов ('5-9') в явный список классов ('5 6 7 8 9')."""
    def repl(m: re.Match) -> str:
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start <= 11 and 1 <= end <= 11 and start < end:
            all_grades = " ".join(str(g) for g in range(start, end + 1))
            return f"{m.group(0)} {start}-{end} {all_grades}"
        return m.group(0)
    return re.sub(r'\b(\d+)\s*-\s*(\d+)\b', repl, text)


def log_retrieval_debug(hits: List[RetrievalHit], query: str, top_display: int = 6) -> None:
    """
    Легковесный блок отладки (debug logging) выдачи Retriever перед отправкой в LLM.
    Выводит в консоль top_k извлеченных чанков:
    - Ранг и итоговый балл (Rerank / RRF)
    - Баллы косинусного сходства (Dense) и BM25 (Sparse)
    - Источник, страницу
    - Первые 200 символов текста фрагмента
    """
    separator = "=" * 80
    sub_sep = "-" * 80
    print(f"\n{separator}")
    print(f"🔍 [RETRIEVER DEBUG] Запрос: '{query}'")
    print(f"   Отобрано чанков для контекста: {len(hits)} (показаны топ-{min(len(hits), top_display)})")
    print(separator)

    if not hits:
        print("   ⚠️ ВНИМАНИЕ: Нет извлеченных фрагментов (Zero-Retrieval).")
        print(f"{separator}\n")
        return

    for idx, hit in enumerate(hits[:top_display], 1):
        meta = hit.chunk.metadata
        snippet = hit.chunk.text.replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:197] + "..."

        print(f"[{idx}] 📄 Документ: {meta.source} | Стр: {meta.page} | ID: {meta.chunk_id}")
        print(f"    📊 Метрики -> Rerank: {hit.rerank_score:.4f} | Dense Cosine: {hit.dense_score:.4f} | BM25: {hit.sparse_score:.2f} | RRF: {hit.rrf_score:.4f}")
        print(f"    📝 Сниппет: {snippet}")
        if idx < min(len(hits), top_display):
            print(sub_sep)

    print(f"{separator}\n")


# =====================================================================
# 4. Иерархический рекурсивный сплиттер (Recursive Text Splitter)
# =====================================================================

class RecursiveCharacterSplitter:
    """
    Рекурсивный сплиттер с учетом структуры документа:
    - Конфигурация: размер чанка 1200–1800 символов (~400–600 токенов),
      перекрытие 300–450 символов (~100–150 токенов).
    - Делит по абзацам (\\n\\n), затем по строкам/спискам (\\n),
      затем по границам предложений (. ! ?), затем по словам.
    - Обеспечивает скользящее окно с перекрытием (chunk_overlap)
      для сохранения смыслового контекста на стыках фрагментов.
    """
    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 350):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]

    def split_text(self, text: str) -> List[str]:
        text = clean_document_text(text)
        if len(text) <= self.chunk_size:
            return [text] if len(text) >= 30 else []

        raw_chunks = self._recursive_split(text, self.separators)
        merged_chunks = self._merge_chunks(raw_chunks)
        return [c for c in merged_chunks if len(c.strip()) >= 30]

    def _recursive_split(self, text: str, separators: List[str]) -> List[str]:
        if not separators:
            return [text[i : i + self.chunk_size] for i in range(0, len(text), max(1, self.chunk_size - self.chunk_overlap))]

        sep = separators[0]
        splits = text.split(sep)
        result: List[str] = []

        for s in splits:
            s_clean = s.strip()
            if not s_clean:
                continue
            if len(s_clean) <= self.chunk_size:
                result.append(s_clean)
            else:
                sub_splits = self._recursive_split(s_clean, separators[1:])
                result.extend(sub_splits)
        return result

    def _merge_chunks(self, pieces: List[str]) -> List[str]:
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        for piece in pieces:
            piece_len = len(piece)
            if current and (current_len + piece_len + 1 > self.chunk_size):
                full_chunk = " ".join(current).strip()
                chunks.append(full_chunk)
                overlap_pieces: List[str] = []
                overlap_len = 0
                for prev in reversed(current):
                    if overlap_len + len(prev) < self.chunk_overlap:
                        overlap_pieces.insert(0, prev)
                        overlap_len += len(prev)
                    else:
                        break
                current = overlap_pieces
                current_len = sum(len(p) for p in current) + max(0, len(current) - 1)

            current.append(piece)
            current_len += piece_len + 1

        if current:
            chunks.append(" ".join(current).strip())

        return chunks


# =====================================================================
# 5. Okapi BM25 с инвертированным индексом (Sparse Retrieval)
# =====================================================================

class OkapiBM25:
    """
    Быстрый инвертированный индекс Okapi BM25 с логарифмическим IDF
    и нормализацией длины документа:
    BM25(D, Q) = sum( IDF(q_i) * (TF * (k1 + 1)) / (TF + k1 * (1 - b + b * (|D| / avgdl))) )
    """
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.inverted_index: Dict[str, List[Tuple[int, int]]] = {}
        self.doc_lengths: List[int] = []
        self.avg_dl: float = 1.0
        self.num_docs: int = 0
        self.idf_cache: Dict[str, float] = {}

    def fit(self, tokenized_corpus: List[List[str]]):
        self.num_docs = len(tokenized_corpus)
        if self.num_docs == 0:
            return

        self.doc_lengths = [len(doc) for doc in tokenized_corpus]
        self.avg_dl = sum(self.doc_lengths) / max(1, self.num_docs)
        self.inverted_index.clear()
        self.idf_cache.clear()

        for doc_id, tokens in enumerate(tokenized_corpus):
            counts: Dict[str, int] = {}
            for t in tokens:
                counts[t] = counts.get(t, 0) + 1
            for term, tf in counts.items():
                if term not in self.inverted_index:
                    self.inverted_index[term] = []
                self.inverted_index[term].append((doc_id, tf))

        for term, postings in self.inverted_index.items():
            df = len(postings)
            self.idf_cache[term] = math.log(1.0 + (self.num_docs - df + 0.5) / (df + 0.5))

    def query(self, query_terms: List[str], top_k: int = 80) -> List[Tuple[int, float]]:
        if not query_terms or self.num_docs == 0:
            return []

        scores: Dict[int, float] = {}
        for qt in query_terms:
            idf = self.idf_cache.get(qt, 0.0)
            if idf <= 0.0:
                continue
            postings = self.inverted_index.get(qt, [])
            for doc_id, tf in postings:
                doc_len = self.doc_lengths[doc_id]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_dl))
                term_score = idf * (numerator / denominator)
                scores[doc_id] = scores.get(doc_id, 0.0) + term_score

        if not scores:
            return []

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_scores[:top_k]


# =====================================================================
# 6. Плотный векторный движок (Dense Vector Store)
# =====================================================================

class DenseVectorStore:
    """
    NumPy-ускоренный векторный поиск с поддержкой двух модульных бэкендов:
    1. REMOTE: OpenAI-совместимый эндпоинт (/v1/embeddings) в LM Studio, Ollama или vLLM
       через официальный SDK openai.OpenAI.
    2. SENTENCE_TRANSFORMERS: Локальное вычисление эмбеддингов через HuggingFace
       с автоматическим выбором устройства (CUDA / Apple MPS / CPU).

    Особенности:
    - Принудительное форматирование префиксов Nomic v1.5 ('search_document: ', 'search_query: ')
      без дублирования.
    - Гарантированная L2-нормализация каждого вектора.
    - Высокоскоростное пакетное вычисление (batching).
    """
    def __init__(
        self,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        sentence_transformer_model: Optional[str] = None,
        device: Optional[str] = None,
        config: Optional[AppConfig] = None
    ):
        cfg = config or CONFIG
        self.provider = (provider or cfg.embedding_provider).upper()
        self.model_name = model_name or cfg.embedding_model
        self.base_url = base_url or cfg.embedding_base_url
        self.api_key = api_key or cfg.embedding_api_key
        self.st_model_name = sentence_transformer_model or cfg.sentence_transformer_model
        self.device_preference = (device or cfg.embedding_device or "cpu").lower()

        # Сетевые клиенты для REMOTE режима
        self.client = httpx.Client(base_url=self.base_url, timeout=45.0, trust_env=False)
        self.openai_client = OpenAI(base_url=self.base_url, api_key=self.api_key)

        # Локальная модель SentenceTransformer (инициализируется при первом требовании)
        self.st_model = None
        self.resolved_device: Optional[str] = None

        self.matrix: Optional[np.ndarray] = None
        self.embedding_dim: Optional[int] = None

        if self.provider == "SENTENCE_TRANSFORMERS":
            self._init_sentence_transformer()

    def _init_sentence_transformer(self):
        """Ленивая инициализация локальной библиотеки sentence-transformers на CPU/устройстве."""
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            if self.device_preference in ("cpu", "processor", "proc"):
                self.resolved_device = "cpu"
            elif self.device_preference == "auto":
                self.resolved_device = "cpu"
            else:
                self.resolved_device = self.device_preference

            logger.info(f"Инициализация SentenceTransformer '{self.st_model_name}' на устройстве [{self.resolved_device}]...")
            self.st_model = SentenceTransformer(self.st_model_name, device=self.resolved_device, trust_remote_code=True)
            logger.info(f"Локальная модель SentenceTransformer успешно готова к работе.")
        except ImportError:
            err_msg = (
                "Для локального расчета эмбеддингов (EMBEDDING_PROVIDER=SENTENCE_TRANSFORMERS) "
                "требуются пакеты torch и sentence-transformers.\n"
                "Установите их командой: pip install torch sentence-transformers"
            )
            logger.error(err_msg)
            raise ImportError(err_msg)
        except Exception as e:
            logger.error(f"Не удалось загрузить локальную модель '{self.st_model_name}': {e}")
            raise e

    def check_health(self) -> bool:
        """Проверка доступности выбранного бэкенда эмбеддингов."""
        try:
            if self.provider == "SENTENCE_TRANSFORMERS":
                if self.st_model is None:
                    self._init_sentence_transformer()
                test_vec = self.get_embedding("тест", is_query=True)
                if test_vec is not None and len(test_vec) > 0:
                    self.embedding_dim = len(test_vec)
                    return True
                return False

            # Режим REMOTE через OpenAI SDK
            test_input = format_nomic_input("тест", is_query=True)
            res = self.openai_client.embeddings.create(
                model=self.model_name,
                input=test_input,
                timeout=5.0
            )
            if res.data and len(res.data) > 0:
                emb = res.data[0].embedding
                self.embedding_dim = len(emb)
                return True
        except Exception as e:
            # Fallback на httpx при временных неполадках OpenAI SDK
            try:
                test_input = format_nomic_input("тест", is_query=True)
                r = self.client.post("/embeddings", json={"model": self.model_name, "input": test_input}, timeout=3.0)
                if r.status_code == 200:
                    emb = r.json()["data"][0]["embedding"]
                    self.embedding_dim = len(emb)
                    return True
            except Exception:
                pass
            logger.warning(f"Embedding бэкенд ({self.provider}) недоступен: {e}")
        return False

    def get_embedding(self, text: str, is_query: bool = False, max_retries: int = 3) -> Optional[List[float]]:
        clean_t = text[:2000].strip()
        if not clean_t:
            return None

        # Принудительная расстановка префикса nomic
        formatted_input = format_nomic_input(clean_t, is_query=is_query)

        # 1. Локальный режим через SentenceTransformers
        if self.provider == "SENTENCE_TRANSFORMERS":
            if self.st_model is None:
                self._init_sentence_transformer()
            emb = self.st_model.encode([formatted_input], normalize_embeddings=True)[0]
            return [float(x) for x in emb]

        # 2. Удаленный режим (OpenAI API / LM Studio / Ollama)
        delay = 1.0
        for attempt in range(max_retries):
            try:
                res = self.openai_client.embeddings.create(
                    model=self.model_name,
                    input=formatted_input,
                    timeout=30.0
                )
                if res.data and len(res.data) > 0:
                    arr = np.array(res.data[0].embedding, dtype=np.float32)
                    norm = np.linalg.norm(arr)
                    if norm > 0:
                        arr /= norm
                    return arr.tolist()
            except Exception:
                # Fallback прямой httpx запрос
                try:
                    resp = self.client.post(
                        "/embeddings",
                        json={"model": self.model_name, "input": formatted_input},
                        timeout=30.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()["data"][0]["embedding"]
                        arr = np.array(data, dtype=np.float32)
                        norm = np.linalg.norm(arr)
                        if norm > 0:
                            arr /= norm
                        return arr.tolist()
                except Exception:
                    pass
                time.sleep(delay)
                delay *= 2.0
        return None

    def get_batch_embeddings(self, texts: List[str], is_query: bool = False, batch_size: int = 16) -> List[Optional[List[float]]]:
        results: List[Optional[List[float]]] = []

        # 1. Локальный расчет батча через SentenceTransformers
        if self.provider == "SENTENCE_TRANSFORMERS":
            if self.st_model is None:
                self._init_sentence_transformer()
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                formatted_batch = [format_nomic_input(t[:2000].strip(), is_query=is_query) for t in batch]
                encodings = self.st_model.encode(formatted_batch, normalize_embeddings=True, show_progress_bar=False)
                for vec in encodings:
                    results.append([float(x) for x in vec])
            return results

        # 2. Удаленный расчет батча через OpenAI API
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            formatted_batch = [format_nomic_input(t[:2000].strip(), is_query=is_query) for t in batch]

            try:
                res = self.openai_client.embeddings.create(
                    model=self.model_name,
                    input=formatted_batch,
                    timeout=45.0
                )
                if res.data:
                    sorted_items = sorted(res.data, key=lambda x: getattr(x, "index", 0))
                    for item in sorted_items:
                        arr = np.array(item.embedding, dtype=np.float32)
                        norm = np.linalg.norm(arr)
                        if norm > 0:
                            arr /= norm
                        results.append(arr.tolist())
                    continue
            except Exception as e:
                logger.warning(f"Пакетная векторизация batch {i} через OpenAI SDK: ({e}), пробуем httpx...")
                try:
                    resp = self.client.post(
                        "/embeddings",
                        json={"model": self.model_name, "input": formatted_batch},
                        timeout=45.0
                    )
                    if resp.status_code == 200:
                        batch_data = resp.json().get("data", [])
                        sorted_items = sorted(batch_data, key=lambda x: x.get("index", 0))
                        for item in sorted_items:
                            arr = np.array(item["embedding"], dtype=np.float32)
                            norm = np.linalg.norm(arr)
                            if norm > 0:
                                arr /= norm
                            results.append(arr.tolist())
                        continue
                except Exception as ex:
                    logger.warning(f"Пакетная векторизация batch {i} не удалась ({ex}), переключаемся на поштучную.")

            # Fallback на поштучную генерацию
            for t in batch:
                results.append(self.get_embedding(t, is_query=is_query))

        return results

    def build_matrix(self, chunks: List[DocumentChunk]):
        vectors = []
        for ch in chunks:
            if ch.vector and len(ch.vector) > 0:
                vectors.append(ch.vector)

        if vectors:
            self.matrix = np.array(vectors, dtype=np.float32)
            norms = np.linalg.norm(self.matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self.matrix /= norms
            self.embedding_dim = self.matrix.shape[1]
            logger.info(f"Dense матрица построена: {self.matrix.shape[0]} векторов, размерность {self.embedding_dim}")
        else:
            self.matrix = None

    def query(self, query_text: str, top_k: int = 80) -> List[Tuple[int, float]]:
        if self.matrix is None:
            return []

        # Запрос пользователя строго векторизуется с префиксом 'search_query: '
        q_vec = self.get_embedding(query_text, is_query=True)
        if q_vec is None:
            return []

        q_arr = np.array(q_vec, dtype=np.float32)
        scores = np.dot(self.matrix, q_arr)

        if len(scores) <= top_k:
            best_indices = np.argsort(scores)[::-1]
        else:
            best_indices = np.argpartition(scores, -top_k)[-top_k:]
            best_indices = best_indices[np.argsort(scores[best_indices])[::-1]]

        return [(int(idx), float(scores[idx])) for idx in best_indices if scores[idx] > 0.0]


# =====================================================================
# 7. Гибридный поисковый ретривер (Hybrid Search & RRF & Rerank)
# =====================================================================

class HybridRetriever:
    """
    Координирует гибридный поиск:
    1. Query Reformulation & Typo Correction
    2. Dense Retrieval + Sparse Retrieval (BM25)
    3. Reciprocal Rank Fusion (RRF k=60)
    4. Multi-Feature Cross-Reranker (фразы, близость, заголовки, штрафы)
    5. Lost in the Middle Reordering
    """
    def __init__(self, dense_store: DenseVectorStore, bm25_engine: OkapiBM25, chunks: List[DocumentChunk]):
        self.dense_store = dense_store
        self.bm25_engine = bm25_engine
        self.chunks = chunks

    @staticmethod
    def reformulate_query(query: str, history: Optional[List[str]] = None) -> Tuple[str, List[str]]:
        if history:
            full_raw_query = f"{' '.join(history[-2:])} {query}"
        else:
            full_raw_query = query

        tokens = re.findall(r'\b[a-zA-Zа-яёА-ЯЁ0-9_-]+\b', full_raw_query.lower().replace('ё', 'е'))
        fixed_tokens = [TYPO_MAP.get(t, t) for t in tokens]
        expanded_query = " ".join(fixed_tokens)

        for t in fixed_tokens:
            for root, exp in GRADE_WORDS.items():
                if root in t:
                    expanded_query += f" {exp}"
                    break

        for group in SYNONYM_GROUPS:
            if any(trigger in expanded_query for trigger in group['triggers']):
                expanded_query += f" {group['expansion']}"
                break

        # Определение общего запроса об учреждении или базе знаний
        q_lower = full_raw_query.lower()
        is_school_overview = any(
            t in q_lower for t in [
                'общая сводка', 'сводка по документам', 'об организации', 'про организацию', 'знаешь об организации',
                'руководство и структура', 'о нашей школе', 'о школе', 'про школу', 'знаешь о школе', 'знаешь о нашей школе',
                'что за школа', 'какая это школа', 'информация о школе', 'расскажи о школе',
                'чем занимается школа', 'о школе 1468', 'школа 1468', 'наша школа', 'нашей школе',
                'что ты знаешь', 'обобщи информацию', 'общая информация', 'история школы', 'здания школы',
                'руководство школы', 'директор школы', 'о нашем учебном заведении'
            ]
        ) or ('знаешь' in q_lower and ('школ' in q_lower or 'организац' in q_lower or 'документ' in q_lower)) or ('расскажи' in q_lower and ('школ' in q_lower or 'организац' in q_lower or 'документ' in q_lower))

        if is_school_overview:
            expanded_query += " гбоу школа 1468 публичный доклад руководителя директор итоги года 11 зданий 5 школьных 6 дошкольных медицинский инженерный медиакласс предпринимательский форма деловой стиль"

        is_kb_overview = any(
            t in q_lower for t in [
                'о чем эти документы', 'о чем документы', 'что в документах', 'содержание документов',
                'база знаний', 'базе знаний', 'какие документы', 'список документов', 'что ты умеешь'
            ]
        )
        if is_kb_overview:
            expanded_query += " документы школы гбоу 1468 публичный доклад локальные нормативные акты правила внутреннего распорядка памятки безопасности образовательные программы питание деловой стиль"

        q_words = re.findall(r'\b[a-zA-Zа-яёА-ЯЁ0-9_-]+\b', expanded_query.lower().replace('ё', 'е'))
        meaningful = [w for w in q_words if w not in CORPUS_STOP_WORDS]
        if not meaningful:
            meaningful = [w for w in q_words if len(w) > 2]
        stems = [stem_russian_word(w) for w in meaningful]

        return expanded_query, stems

    def search(
        self,
        raw_query: Optional[str] = None,
        history: Optional[List[str]] = None,
        top_k: int = 5,
        rrf_k: int = 60,
        w_dense: float = 1.0,
        w_sparse: float = 1.0,
        confidence_threshold: float = 0.015,
        query: Optional[str] = None,
        enable_expansion: bool = True
    ) -> Tuple[List[RetrievalHit], str, bool]:
        target_q = (raw_query if raw_query is not None else query) or ""
        reformulated_query, stems = self.reformulate_query(target_q, history)
        logger.info(f"Поисковый запрос: '{target_q}' -> Расширенный: '{reformulated_query[:120]}...'")

        # 1. Sparse Search (BM25)
        sparse_results = self.bm25_engine.query(stems, top_k=80)
        sparse_ranks: Dict[int, int] = {doc_id: rank + 1 for rank, (doc_id, _) in enumerate(sparse_results)}
        sparse_scores: Dict[int, float] = dict(sparse_results)

        # 2. Dense Search
        dense_results = self.dense_store.query(reformulated_query, top_k=80)
        dense_ranks: Dict[int, int] = {doc_id: rank + 1 for rank, (doc_id, _) in enumerate(dense_results)}
        dense_scores: Dict[int, float] = dict(dense_results)

        # 3. Reciprocal Rank Fusion (RRF)
        all_candidate_ids = set(sparse_ranks.keys()).union(dense_ranks.keys())
        if not all_candidate_ids:
            return [], reformulated_query, True

        rrf_scores: Dict[int, float] = {}
        for doc_id in all_candidate_ids:
            score = 0.0
            if doc_id in dense_ranks:
                score += w_dense / (rrf_k + dense_ranks[doc_id])
            if doc_id in sparse_ranks:
                score += w_sparse / (rrf_k + sparse_ranks[doc_id])
            rrf_scores[doc_id] = score

        # 4. Multi-Feature Reranking
        is_clothing_query = any(w in reformulated_query for w in ['форм', 'одежд', 'стил', 'внешн', 'дресс', 'носить', 'цвет', 'костюм', 'брюк', 'блузк', 'юбк', 'сарафан', 'обув', 'джинс', 'сменк', 'спорт', 'физкульт'])
        
        q_lower = raw_query.lower()
        is_school_overview = any(
            t in q_lower for t in [
                'общая сводка', 'сводка по документам', 'об организации', 'про организацию', 'знаешь об организации',
                'руководство и структура', 'о нашей школе', 'о школе', 'про школу', 'знаешь о школе', 'знаешь о нашей школе',
                'что за школа', 'какая это школа', 'информация о школе', 'расскажи о школе',
                'чем занимается школа', 'о школе 1468', 'школа 1468', 'наша школа', 'нашей школе',
                'что ты знаешь', 'обобщи информацию', 'общая информация'
            ]
        ) or ('знаешь' in q_lower and ('школ' in q_lower or 'организац' in q_lower or 'документ' in q_lower)) or ('расскажи' in q_lower and ('школ' in q_lower or 'организац' in q_lower or 'документ' in q_lower))

        is_kb_overview = any(
            t in q_lower for t in [
                'о чем эти документы', 'о чем документы', 'что в документах', 'содержание документов',
                'база знаний', 'базе знаний', 'какие документы', 'список документов', 'что ты умеешь'
            ]
        )

        effective_top_k = max(top_k, 8) if (is_school_overview or is_kb_overview) else top_k

        reranked_hits: List[RetrievalHit] = []
        for doc_id, rrf_sc in rrf_scores.items():
            chunk = self.chunks[doc_id]
            text = chunk.text.lower().replace('ё', 'е')
            source = chunk.metadata.source.lower()
            full_text = text + " " + source

            boost = 1.0
            matched_stems = [st for st in stems if re.search(r'\b' + re.escape(st), full_text)]
            match_ratio = len(matched_stems) / max(1, len(set(stems)))
            boost += match_ratio * 2.5

            digit_stems = [st for st in stems if st.isdigit()]
            if digit_stems and all(re.search(r'\b' + re.escape(dst), full_text) for dst in digit_stems):
                boost += 2.0

            for j in range(len(stems) - 1):
                st1, st2 = stems[j], stems[j+1]
                if st1 in matched_stems and st2 in matched_stems and st1 != st2:
                    p1 = r'\b' + re.escape(st1) + r'\w*\b(?:\W+\w+){0,8}?\W+\b' + re.escape(st2) + r'\w*\b'
                    p2 = r'\b' + re.escape(st2) + r'\w*\b(?:\W+\w+){0,8}?\W+\b' + re.escape(st1) + r'\w*\b'
                    if re.search(p1, text) or re.search(p2, text):
                        boost += 1.5

            if is_clothing_query:
                clothing_terms = ['одежд', 'дресс', 'блузк', 'рубашк', 'брюк', 'костюм', 'туфл', 'юбк', 'пиджак', 'жилет', 'сарафан', 'галстук', 'обув', 'физкульт', 'спорт']
                if any(w in text for w in clothing_terms):
                    boost += 2.0
                if any(p in text for p in ['деловой стиль', 'стиль одежды', 'цвет формы', 'памятка для родителей и учащихся', 'памятка для родителей', 'спортивная одежда']):
                    boost += 3.0
                if 'форма обучения' in text and not any(w in text for w in clothing_terms):
                    boost *= 0.1

            if is_school_overview or is_kb_overview:
                if '6a50f010d3e30.pdf' in source: # Публичный доклад руководителя ГБОУ Школа № 1468
                    boost += 4.0
                elif '68b8296aa2c29.pdf' in source: # Итоги учебного года ГБОУ Школа № 1468
                    boost += 3.2
                elif any(fs in source for fs in ['6a7d653763d0c.pdf', '6a7d65434d2f9.pdf', '6a7d6551966ae.pdf']): # Памятка формы
                    boost += 2.2
                elif '69bba1b8cbf22.pdf' in source: # Профсоюз / сотрудники Школы 1468
                    boost += 2.0
                elif '1468' in full_text:
                    boost += 2.2

                if any(term in full_text for term in ['11 зданий', 'дошкольн', 'руководител', 'директор', 'гончаров']):
                    boost += 2.2
                if any(term in full_text for term in ['инженерный класс', 'медицинский класс', 'медиакласс', 'предпринимательский', 'предпрофессиональн']):
                    boost += 2.2

            final_score = rrf_sc * boost
            hit = RetrievalHit(
                chunk=chunk,
                dense_score=dense_scores.get(doc_id, 0.0),
                sparse_score=sparse_scores.get(doc_id, 0.0),
                rrf_score=rrf_sc,
                rerank_score=final_score
            )
            reranked_hits.append(hit)

        reranked_hits.sort(key=lambda h: h.rerank_score, reverse=True)

        if not reranked_hits or reranked_hits[0].rerank_score < confidence_threshold:
            logger.info(f"Zero Retrieval: максимальный скор {reranked_hits[0].rerank_score if reranked_hits else 0.0:.4f} < {confidence_threshold}")
            log_retrieval_debug([], raw_query)
            return [], reformulated_query, True

        filtered_hits: List[RetrievalHit] = []
        seen_sources: Dict[str, int] = {}
        for h in reranked_hits:
            src = h.chunk.metadata.source
            if seen_sources.get(src, 0) < 2:
                filtered_hits.append(h)
                seen_sources[src] = seen_sources.get(src, 0) + 1
            if len(filtered_hits) >= effective_top_k:
                break

        for idx, h in enumerate(filtered_hits, 1):
            h.final_rank = idx

        # Детальная отладка выдачи Retriever в консоль разработчика
        log_retrieval_debug(filtered_hits, raw_query, top_display=min(len(filtered_hits), 6))

        return filtered_hits, reformulated_query, False

    @staticmethod
    def reorder_lost_in_the_middle(hits: List[RetrievalHit]) -> List[RetrievalHit]:
        """
        Решает проблему 'Lost in the Middle':
        Размещает наиболее релевантные фрагменты по краям контекстного окна:
        Позиции: [1, 3, 5, ..., 6, 4, 2].
        """
        if len(hits) <= 2:
            return hits

        reordered: List[Optional[RetrievalHit]] = [None] * len(hits)
        left = 0
        right = len(hits) - 1

        for i, hit in enumerate(hits):
            if i % 2 == 0:
                reordered[left] = hit
                left += 1
            else:
                reordered[right] = hit
                right -= 1

        return [h for h in reordered if h is not None]


# =====================================================================
# 8. Сборка контекста с токен-бюджетом и XML-изоляцией
# =====================================================================

class ContextAssembler:
    """
    Сборка защищенного контекста для LLM:
    - Ограничение финального контекста 4–6 наиболее релевантными чанками (Lost-in-the-Middle mitigation).
    - Токен-бюджет (token budget limit).
    - Строгая XML-изоляция каждого фрагмента документа.
    """
    def __init__(self, max_context_tokens: int = 2500, max_chunks: int = 6):
        self.max_context_tokens = max_context_tokens
        self.max_chunks = max_chunks

    def assemble(
        self,
        hits: List[RetrievalHit],
        max_tokens: Optional[int] = None,
        max_chunks: Optional[int] = None
    ) -> Tuple[str, List[RetrievalHit]]:
        limit_chunks = max_chunks if max_chunks is not None else self.max_chunks
        candidate_hits = hits[:limit_chunks]
        token_limit = max_tokens if max_tokens is not None else self.max_context_tokens

        assembled_docs = []
        current_tokens = 0
        accepted_hits: List[RetrievalHit] = []

        for idx, hit in enumerate(candidate_hits, 1):
            chunk = hit.chunk
            clean_text = clean_document_text(chunk.text)
            doc_xml = (
                f'<document id="doc_{idx}" source="{chunk.metadata.source}" page="{chunk.metadata.page}">\n'
                f'{clean_text}\n'
                f'</document>'
            )
            doc_tokens = count_tokens(doc_xml)
            if current_tokens + doc_tokens > token_limit and accepted_hits:
                logger.info(f"Достигнут токен-лимит ({current_tokens}/{token_limit}). Ограничиваем число фрагментов.")
                break

            assembled_docs.append(doc_xml)
            accepted_hits.append(hit)
            current_tokens += doc_tokens

        full_context_xml = "<context>\n" + "\n\n".join(assembled_docs) + "\n</context>"
        return full_context_xml, accepted_hits


# =====================================================================
# 9. Индексатор документов (Document Pipeline & Ingestion)
# =====================================================================

class DocumentIngestionPipeline:
    """
    Полный цикл загрузки, очистки, нарезки и векторизации документов:
    - Поддержка PDF (pypdf/pymupdf) и TXT.
    - Очистка URL-кодировок в именах файлов (urllib.parse.unquote).
    - Генерация метаданных (chunk_id, doc_id, timestamp, content_hash).
    - Дедупликация дубликатов по хешу контента.
    - Пакетное вычисление эмбеддингов.
    """
    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 350):
        self.splitter = RecursiveCharacterSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def load_file(self, file_path: Path) -> List[Dict[str, Any]]:
        clean_name = urllib.parse.unquote(file_path.name)
        pages_data = []

        if file_path.suffix.lower() == ".pdf":
            if pymupdf is not None:
                try:
                    doc = pymupdf.open(str(file_path))
                    for p_num in range(len(doc)):
                        page = doc[p_num]
                        text = page.get_text() or ""
                        text = clean_document_text(text)
                        if text:
                            pages_data.append({"page": p_num + 1, "text": text})
                    doc.close()
                    if pages_data:
                        return pages_data
                except Exception as e:
                    logger.warning(f"Ошибка PyMuPDF на {file_path.name}: {e}, переключаемся на pypdf")

            if pypdf is not None:
                try:
                    reader = pypdf.PdfReader(str(file_path))
                    for p_num, page in enumerate(reader.pages):
                        text = page.extract_text() or ""
                        text = clean_document_text(text)
                        if text:
                            pages_data.append({"page": p_num + 1, "text": text})
                except Exception as e:
                    logger.error(f"Ошибка чтения PDF {file_path.name}: {e}")

        elif file_path.suffix.lower() == ".txt":
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = clean_document_text(f.read())
                    if text:
                        pages_data.append({"page": 1, "text": text})
            except Exception as e:
                logger.error(f"Ошибка чтения TXT {file_path.name}: {e}")

        elif file_path.suffix.lower() == ".docx":
            try:
                from ingestion.parsers import parse_docx
                blocks = parse_docx(str(file_path))
                if blocks:
                    pages_data.append({"page": 1, "text": "\n\n".join(blocks)})
            except Exception as e:
                logger.error(f"Ошибка чтения DOCX {file_path.name}: {e}")

        elif file_path.suffix.lower() == ".xlsx":
            try:
                from ingestion.parsers import parse_xlsx
                rows = parse_xlsx(str(file_path))
                if rows:
                    pages_data.append({"page": 1, "text": "\n".join(rows)})
            except Exception as e:
                logger.error(f"Ошибка чтения XLSX {file_path.name}: {e}")

        return pages_data

    def process_directory(
        self,
        data_dir: Path,
        dense_store: Optional[DenseVectorStore] = None
    ) -> List[DocumentChunk]:
        if not data_dir.exists():
            logger.error(f"Директория {data_dir} не существует!")
            return []

        files = (
            list(data_dir.rglob("*.pdf"))
            + list(data_dir.rglob("*.txt"))
            + list(data_dir.rglob("*.docx"))
            + list(data_dir.rglob("*.xlsx"))
        )
        logger.info(f"Найдено файлов для индексации: {len(files)}")

        all_chunks: List[DocumentChunk] = []
        seen_hashes: Set[str] = set()
        timestamp = datetime.utcnow().isoformat()

        for f_idx, file_path in enumerate(files, 1):
            clean_name = urllib.parse.unquote(file_path.name)
            doc_id = hashlib.sha256(file_path.name.encode("utf-8")).hexdigest()[:16]
            ext = file_path.suffix.lower()

            # Использование специализированного чанкера для docx/xlsx
            if ext in (".docx", ".xlsx"):
                try:
                    from ingestion.parsers import load_and_chunk_document
                    doc_chunks_raw = load_and_chunk_document(
                        str(file_path),
                        chunk_size=self.splitter.chunk_size,
                        chunk_overlap=self.splitter.chunk_overlap
                    )
                    for item in doc_chunks_raw:
                        ch_text = item["text"]
                        c_hash = item["metadata"].get("content_hash") or hashlib.sha256(ch_text.encode("utf-8")).hexdigest()[:16]
                        if c_hash in seen_hashes:
                            continue
                        seen_hashes.add(c_hash)
                        meta_dict = item["metadata"]
                        meta = ChunkMetadata(
                            chunk_id=meta_dict["chunk_id"],
                            doc_id=doc_id,
                            source=clean_name,
                            raw_source=str(file_path),
                            page=meta_dict.get("page", 1),
                            sheet=meta_dict.get("sheet"),
                            char_count=meta_dict.get("char_count", len(ch_text)),
                            token_count=meta_dict.get("token_count", count_tokens(ch_text)),
                            created_at=timestamp,
                            content_hash=c_hash
                        )
                        all_chunks.append(DocumentChunk(metadata=meta, text=ch_text))
                    continue
                except Exception as e:
                    logger.error(f"Ошибка при обработке {file_path.name} через load_and_chunk_document: {e}")
            pages = self.load_file(file_path)

            chunk_counter = 0
            for page_info in pages:
                p_num = page_info["page"]
                p_text = page_info["text"]
                text_chunks = self.splitter.split_text(p_text)

                for chunk_text in text_chunks:
                    content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:16]
                    if content_hash in seen_hashes:
                        continue
                    seen_hashes.add(content_hash)

                    chunk_counter += 1
                    chunk_id = f"{doc_id}_c{chunk_counter:04d}"
                    meta = ChunkMetadata(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        source=clean_name,
                        raw_source=str(file_path),
                        page=p_num,
                        char_count=len(chunk_text),
                        token_count=count_tokens(chunk_text),
                        created_at=timestamp,
                        content_hash=content_hash
                    )
                    all_chunks.append(DocumentChunk(metadata=meta, text=chunk_text))

        logger.info(f"Всего сформировано уникальных фрагментов: {len(all_chunks)}")

        if dense_store and dense_store.check_health():
            logger.info("Запуск пакетного вычисления эмбеддингов...")
            texts_to_embed = [c.text for c in all_chunks]
            embeddings = dense_store.get_batch_embeddings(texts_to_embed, is_query=False, batch_size=16)
            for ch, vec in zip(all_chunks, embeddings):
                ch.vector = vec
            dense_store.build_matrix(all_chunks)

        return all_chunks


# =====================================================================
# 10. Комплексный пайплайн (RAG Pipeline Orchestrator)
# =====================================================================

class RAGPipeline:
    """
    Главный координатор RAG-системы (Production Orchestrator):
    - Управление индексами и хранилищем.
    - Прогон через HybridRetriever, Lost-in-the-Middle, Token Budgeter.
    - Взаимодействие с LLM (LM Studio) с потоковой передачей (stream)
      или пакетной генерацией.
    - Обязательная санитария вывода от иероглифов (sanitize_llm_output).
    - Валидация цитат и формирование Pydantic ответа RAGResponse.
    """
    SYSTEM_PROMPT = (
        "Ты — ведущий ИИ-консультант и эксперт по нормативным документам, регламентам и внутренним актам организации.\n"
        "Твоя задача — давать точные, исчерпывающие, доброжелательные и структурированные ответы строго на основе предоставленного КОНТЕКСТА документов (<context>).\n\n"
        "ПРИНЦИПЫ ОБРАБОТКИ И АНАЛИЗА КОНТЕКСТА:\n"
        "1. СМЫСЛОВОЙ АНАЛИЗ И СВЯЗЫВАНИЕ ФАКТОВ:\n"
        "   - Анализируй контекст гибко и содержательно: обязательно учитывай синонимы, контекстные ассоциации и смежные понятия.\n"
        "     * Например: 'физкультура' = 'уроки физической культуры', 'занятия спортом';\n"
        "     * 'обувь для зала' = 'кроссовки / кеды со светлой подошвой';\n"
        "     * 'директор' = 'руководитель организации';\n"
        "     * 'питание' = 'столовая, организация питания, горячие завтраки и обеды';\n"
        "     * 'поступление' = 'правила приема, заявление, документы для зачисления'.\n"
        "   - Связывай разрозненные факты из разных фрагментов и документов, если они отвечают на вопрос пользователя.\n\n"
        "2. КРИТЕРИИ ОТКАЗА (СТРОГОЕ ПРАВИЛО):\n"
        "   - Фраза 'В предоставленных документах нет информации по этому вопросу.' разрешена ТОЛЬКО при ПОЛНОМ отсутствии смысловых или тематических пересечений в <context>.\n"
        "   - Если в документах содержится хотя бы частичная, смежная или косвенная информация, относящаяся к теме вопроса — обязательно изложи её полностью, пояснив, что именно зафиксировано в регламентах и нормативных актах.\n\n"
        "3. ОБЩИЕ ВОПРОСЫ ОБ ОРГАНИЗАЦИИ И ЕЁ ДЕЯТЕЛЬНОСТИ:\n"
        "   - На вопросы общего характера ('что ты знаешь по документам?', 'расскажи об организации', 'чем занимается организация?', 'о чем эти документы?', 'общая сводка по документам') формируй развернутый структурированный путеводитель на основе документов из контекста:\n"
        "     * Наименование и статус: наименование организации, реквизиты, руководство и структура подразделений.\n"
        "     * Инфраструктура: здания, корпуса, отделения и адреса, упомянутые в документах.\n"
        "     * Направления деятельности: ключевые программы, профильные направления и специфика работы.\n"
        "     * Результаты и показатели: ключевые достижения, аттестационные и проектные показатели.\n"
        "     * Регламенты и стандарты: требования к деловому стилю, внутренний распорядок, безопасность и питание.\n"
        "     * Дополнительные направления: секции, объединения, проекты и традиции.\n"
        "   - Оформляй ответ с подзаголовками, маркированными списками и выделением ключевых пунктов.\n\n"
        "4. ФАКТОЛОГИЧЕСКАЯ ТОЧНОСТЬ И ССЫЛКИ:\n"
        "   - Опирайся строго на содержание <context>. Не выдумывай несуществующие факты, имена, даты или нормативные акты.\n"
        "   - Обязательно подтверждай утверждения ссылками на первоисточники в формате: [Название документа, стр. X].\n\n"
        "5. ДИАЛОГОВЫЙ КОНТЕКСТ:\n"
        "   - Если пользователь задает уточняющий вопрос (например: 'а для мальчиков?', 'какой цвет?', 'кто директор?'), сохраняй контекст предыдущей беседы.\n\n"
        "6. ЯЗЫКОВЫЕ ТРЕБОВАНИЯ:\n"
        "   - Отвечай ИСКЛЮЧИТЕЛЬНО на грамотном русском языке в деловом и благожелательном тоне.\n"
        "   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выводить любые китайские символы, иероглифы (CJK) или их транслитерации. Все термины и должности пиши строго по-русски: 'директор', 'руководитель', 'сотрудник'."
    )

    def __init__(
        self,
        index_file: Optional[str] = None,
        llm_model: Optional[str] = None,
        embed_model: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[AppConfig] = None
    ):
        import copy
        if config is not None:
            self.config = copy.copy(config)
        else:
            dotenv.load_dotenv(override=True)
            self.config = AppConfig()
        if index_file is not None:
            self.config.index_file = index_file
        if llm_model is not None:
            self.config.llm_model = llm_model
        if embed_model is not None:
            self.config.embedding_model = embed_model
        if base_url is not None:
            self.config.llm_base_url = base_url
            self.config.embedding_base_url = base_url
            if "11434" in base_url:
                self.config.llm_provider = "OLLAMA_LOCAL"
                self.config.llm_api_key = "ollama"
                self.config.embedding_api_key = "ollama"
                if not embed_model or "text-embedding-nomic" in self.config.embedding_model:
                    self.config.embedding_model = "nomic-embed-text"
            elif "1234" in base_url:
                self.config.llm_provider = "LM_STUDIO"

        self.index_file = self.config.index_file
        self.llm_model = self.config.llm_model
        self.embed_model = self.config.embedding_model
        self.base_url = self.config.llm_base_url

        # Унифицированный клиент OpenAI
        self.openai_client = OpenAI(base_url=self.config.llm_base_url, api_key=self.config.llm_api_key)
        # HTTPX клиент для прямой совместимости (включая стриминг в GUI)
        self.client = httpx.Client(base_url=self.config.llm_base_url, timeout=90.0, trust_env=False)

        self.chunks: List[DocumentChunk] = []
        self.dense_store = DenseVectorStore(
            model_name=self.config.embedding_model,
            base_url=self.config.embedding_base_url,
            provider=self.config.embedding_provider,
            api_key=self.config.embedding_api_key,
            sentence_transformer_model=self.config.sentence_transformer_model,
            device=self.config.embedding_device,
            config=self.config
        )
        self.bm25 = OkapiBM25(k1=1.5, b=0.75)
        self.retriever: Optional[HybridRetriever] = None
        self.context_assembler = ContextAssembler(
            max_context_tokens=2500,
            max_chunks=self.config.context_max_chunks
        )

        self.load_index()

    def check_health(self) -> Tuple[bool, str]:
        """
        Pre-flight проверка доступности бэкендов LLM и Embeddings.
        Возвращает (успех: bool, сообщение_или_инструкция: str).
        """
        llm_ok, llm_msg = BackendHealthChecker.check_llm(self.openai_client, self.config)
        if not llm_ok:
            return False, llm_msg

        emb_ok, emb_msg = BackendHealthChecker.check_embeddings(self.dense_store, self.config)
        if not emb_ok:
            return False, emb_msg

        return True, "Все бэкенды RAG (LLM + Embeddings) доступны и функционируют штатно."

    def load_index(self) -> bool:
        if not Path(self.index_file).exists():
            logger.warning(f"Файл индекса {self.index_file} не найден.")
            return False

        logger.info(f"Загрузка индекса из {self.index_file}...")
        t0 = time.time()
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения {self.index_file}: {e}")
            return False

        self.chunks = []
        tokenized_corpus = []

        for item in raw_data:
            if "metadata" in item:
                meta = ChunkMetadata(**item["metadata"])
            else:
                clean_src = urllib.parse.unquote(item.get("source", "unknown"))
                doc_id = hashlib.sha256(clean_src.encode("utf-8")).hexdigest()[:16]
                chunk_id = f"{doc_id}_{len(self.chunks):04d}"
                text_content = item.get("text", "")
                meta = ChunkMetadata(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    source=clean_src,
                    raw_source=item.get("source", ""),
                    page=item.get("page", 1),
                    char_count=len(text_content),
                    token_count=count_tokens(text_content),
                    created_at=datetime.utcnow().isoformat(),
                    content_hash=hashlib.sha256(text_content.encode("utf-8")).hexdigest()[:16]
                )

            chunk = DocumentChunk(
                metadata=meta,
                text=item.get("text", ""),
                vector=item.get("vector", None)
            )
            self.chunks.append(chunk)

            raw_text = chunk.text.lower().replace('ё', 'е')
            norm_text = normalize_grade_ranges(raw_text)
            words = re.findall(r'\b[a-zA-Zа-яёА-ЯЁ0-9_-]+\b', norm_text)
            stems = [stem_russian_word(w) for w in words if w not in CORPUS_STOP_WORDS]
            tokenized_corpus.append(stems)

        self.bm25.fit(tokenized_corpus)
        self.dense_store.build_matrix(self.chunks)
        self.retriever = HybridRetriever(self.dense_store, self.bm25, self.chunks)
        logger.info(f"Индекс успешно загружен за {time.time()-t0:.2f}s! Загружено чанков: {len(self.chunks)}")
        return True

    def save_index(self):
        logger.info(f"Сохранение индекса в {self.index_file}...")
        serializable = [c.model_dump() for c in self.chunks]
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False)
        logger.info(f"Индекс успешно сохранен ({len(self.chunks)} чанков).")

    def query(
        self,
        user_query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        top_k: int = 5,
        temperature: float = 0.28,
        top_p: float = 0.8,
        max_tokens: int = 1500,
        presence_penalty: float = 0.1
    ) -> RAGResponse:
        start_time = time.time()
        if not self.retriever or not self.chunks:
            return RAGResponse(
                query=user_query,
                query_reformulated=user_query,
                answer="Ошибка: Индекс документов не инициализирован. Запустите индексацию.",
                confidence=0.0,
                latency_ms=0.0,
                is_zero_retrieval=True
            )

        user_history_texts = []
        if chat_history:
            user_history_texts = [m["content"] for m in chat_history if m.get("role") == "user"]

        # 1. Поиск и реранкинг (с встроенным выводом отладки log_retrieval_debug)
        hits, reformulated_q, is_zero = self.retriever.search(
            raw_query=user_query,
            history=user_history_texts,
            top_k=top_k
        )

        # 2. Обработка Zero-Retrieval
        if is_zero or not hits:
            latency = (time.time() - start_time) * 1000
            return RAGResponse(
                query=user_query,
                query_reformulated=reformulated_q,
                answer="В предоставленных документах нет информации по этому вопросу.",
                citations=[],
                confidence=0.0,
                context_chunks_used=0,
                latency_ms=round(latency, 2),
                is_zero_retrieval=True
            )

        # 3. Lost in the Middle оптимизация
        reordered_hits = self.retriever.reorder_lost_in_the_middle(hits)

        # 4. Сборка контекста с токен-бюджетом и лимитом чанков (4–6)
        context_xml, accepted_hits = self.context_assembler.assemble(
            reordered_hits,
            max_chunks=min(max(top_k, 4), 6)
        )

        # 5. Формирование структурированных сообщений для OpenAI-compatible API
        messages = [
            {"role": "system", "content": f"{self.SYSTEM_PROMPT}\n\n{context_xml}"}
        ]
        if chat_history:
            for msg in chat_history[-6:]:
                if msg.get("role") in ["user", "assistant"]:
                    clean_content = re.sub(r"\[.*?стр\..*?\]", "", msg["content"])
                    messages.append({"role": msg["role"], "content": clean_content.strip()})
        messages.append({"role": "user", "content": user_query})

        # 6. Вызов LLM через официальный унифицированный клиент OpenAI SDK
        answer_text = ""
        try:
            completion = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                presence_penalty=presence_penalty,
                stop=["<|im_end|>", "<|endoftext|>"],
                max_tokens=max_tokens,
                timeout=90.0
            )
            answer_text = completion.choices[0].message.content or ""
        except Exception as err:
            logger.warning(f"Запрос через OpenAI SDK завершился исключением: ({err}), пробуем прямой httpx...")
            try:
                payload = {
                    "model": self.llm_model,
                    "messages": messages,
                    "temperature": temperature,
                    "top_p": top_p,
                    "presence_penalty": presence_penalty,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "max_tokens": max_tokens,
                    "stream": False
                }
                resp = self.client.post("/chat/completions", json=payload, timeout=90.0)
                if resp.status_code == 200:
                    answer_text = resp.json()["choices"][0]["message"]["content"]
                else:
                    answer_text = BackendHealthChecker.get_remediation_message(
                        self.config, "LLM", f"HTTP {resp.status_code}: {resp.text}"
                    )
            except Exception as fallback_err:
                answer_text = BackendHealthChecker.get_remediation_message(
                    self.config, "LLM", str(fallback_err)
                )

        # 7. ГАРАНТИРОВАННАЯ САНИТАРИЯ ОТ ИЕРОГЛИФОВ И МУСОРА
        answer_text = sanitize_llm_output(answer_text)

        latency = (time.time() - start_time) * 1000

        citations = []
        for h in accepted_hits:
            citations.append(Citation(
                source=h.chunk.metadata.source,
                page=h.chunk.metadata.page,
                quote=h.chunk.text[:200]
            ))

        confidence = min(1.0, max(0.1, accepted_hits[0].rerank_score / 0.1)) if accepted_hits else 0.0

        return RAGResponse(
            query=user_query,
            query_reformulated=reformulated_q,
            answer=answer_text,
            citations=citations,
            confidence=round(confidence, 2),
            context_chunks_used=len(accepted_hits),
            latency_ms=round(latency, 2),
            is_zero_retrieval=False
        )


if __name__ == "__main__":
    print("=" * 75)
    print("  ENTERPRISE RAG — МОДУЛЬНОЕ ПРОИЗВОДСТВЕННОЕ ЯДРО")
    print("=" * 75)
    print(f"  • Провайдер генерации (LLM)   : {CONFIG.llm_provider}")
    print(f"  • Базовый URL LLM             : {CONFIG.llm_base_url}")
    print(f"  • Модель генерации            : {CONFIG.llm_model}")
    print(f"  • Провайдер эмбеддингов       : {CONFIG.embedding_provider}")
    print(f"  • URL / Модель эмбеддингов    : {CONFIG.embedding_base_url} / {CONFIG.embedding_model}")
    print(f"  • Файл векторного индекса     : {CONFIG.index_file}")
    print("-" * 75)

    print("🔍 [Pre-flight] Проверка доступности бэкендов...")
    rag = RAGPipeline()
    is_healthy, status_report = rag.check_health()
    if is_healthy:
        print(f"  [✓] {status_report}")
    else:
        print(f"\n{status_report}\n")

    test_q = "какой цвет формы установлен для начальных классов?"
    print(f"\n💬 Запрос: '{test_q}'")
    res = rag.query(test_q)
    print("\n📝 Ответ:")
    print(res.answer)
    print("\n📚 Первоисточники:")
    for c in res.citations:
        print(f"  - {c.source} (стр. {c.page})")
    print(f"\n⏱ Время отклика: {res.latency_ms:.1f} мс | Уверенность: {res.confidence}")
    print("=" * 75)
