"""
ingestion package — Модуль парсинга, предобработки и чанкинга документов
для Enterprise RAG 2.0 (PDF, TXT, DOCX, XLSX).
"""

from ingestion.parsers import (
    parse_docx,
    parse_xlsx,
    load_and_chunk_document,
    format_nomic_document,
    format_nomic_query,
    NOMIC_DOC_PREFIX,
    NOMIC_QUERY_PREFIX,
)

__all__ = [
    "parse_docx",
    "parse_xlsx",
    "load_and_chunk_document",
    "format_nomic_document",
    "format_nomic_query",
    "NOMIC_DOC_PREFIX",
    "NOMIC_QUERY_PREFIX",
]
