"""
test_button_and_assemble.py — Проверка устранения ошибки TypeError в ContextAssembler.assemble
и стабильности навигации по заготовленным ответам.
"""

import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rag_engine import RAGPipeline, ContextAssembler, RetrievalHit, DocumentChunk, ChunkMetadata

print("=" * 80)
print(" 🧪 ТЕСТ ContextAssembler.assemble() С ПАРАМЕТРОМ max_tokens")
print("=" * 80)

# 1. Проверка сигнатуры assemble() с max_tokens и без
assembler = ContextAssembler(max_context_tokens=2000)
meta = ChunkMetadata(
    chunk_id="test_1",
    doc_id="doc_1",
    source="data/test.pdf",
    raw_source="data/test.pdf",
    page=1,
    chunk_index=0,
    char_count=50,
    token_count=10,
    created_at="2026-09-11T00:00:00",
    content_hash="hash1"
)
chunk = DocumentChunk(chunk_id="test_1", text="Тестовый текст правил формы для физкультуры.", metadata=meta)
hit = RetrievalHit(chunk=chunk, score=0.95)

# Вызов с max_tokens
xml1, hits1 = assembler.assemble([hit], max_tokens=1500)
assert "<context>" in xml1, "XML должен содержать тег <context>"
assert len(hits1) == 1, "Должен быть принят 1 фрагмент"
print("✅ [TEST 1 PASSED] assembler.assemble(hits, max_tokens=1500) работает без ошибок!")

# Вызов без max_tokens (обратная совместимость)
xml2, hits2 = assembler.assemble([hit])
assert "<context>" in xml2
assert len(hits2) == 1
print("✅ [TEST 2 PASSED] assembler.assemble(hits) без аргументов работает штатно!")

# 2. Тест реального RAG-пайплайна по запросу из скриншота пользователя:
# "какие требования к одежде и обуви на уроках физкультуры?"
print("\n" + "=" * 80)
print(" 🧪 ТЕСТ РЕАЛЬНОГО ЗАПРОСА ИЗ СКРИНШОТА ПОЛЬЗОВАТЕЛЯ")
print("=" * 80)

pipeline = RAGPipeline(index_file="rag_index.json")
query_from_screenshot = "какие требования к одежде и обуви на уроках физкультуры?"
hits, reformulated_q, is_zero = pipeline.retriever.search(
    raw_query=query_from_screenshot,
    top_k=5
)
assert len(hits) > 0, "Должны быть найдены фрагменты по форме для физкультуры!"
print(f"Найдено фрагментов: {len(hits)}")

reordered = pipeline.retriever.reorder_lost_in_the_middle(hits)
context_xml, accepted = pipeline.context_assembler.assemble(reordered, max_tokens=2500)
assert "<context>" in context_xml
assert len(accepted) > 0
print(f"Собрано в контекст: {len(accepted)} фрагментов. Длина XML: {len(context_xml)} симв.")
print("✅ [TEST 3 PASSED] Полная цепочка Search -> Reorder -> Assemble(max_tokens=2500) выполнена успешно!")

print("\n🎉 ВСЕ ТЕСТЫ ИСПРАВЛЕНИЯ ОШИБКИ СО СКРИНШОТА УСПЕШНО ПРОЙДЕНЫ!")
