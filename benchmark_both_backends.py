"""
benchmark_both_backends.py — Сравнительный бенчмарк инференса RAG
на одинаковом запросе для бэкендов Ollama Native и LM Studio.
"""

import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import dotenv
import switch_backend
from rag_engine import RAGPipeline

question = "Какие профильные направления и предпрофессиональные классы открыты?"

print("=" * 75)
print("🔬 СРАВНИТЕЛЬНЫЙ ТЕСТ ИНФЕРЕНСА RAG: OLLAMA VS LM STUDIO")
print(f"Вопрос: \"{question}\"")
print("=" * 75)

# --- 1. OLLAMA NATIVE ---
print("\n🦙 ТЕСТИРОВАНИЕ OLLAMA NATIVE...")
switch_backend.switch_to("ollama")
dotenv.load_dotenv(override=True)

start_time = time.time()
pipe_ol = RAGPipeline()
res_ol = pipe_ol.query(question)
time_ol = time.time() - start_time

print("\n" + "-" * 75)
print(f"✅ [OLLAMA NATIVE] Время: {time_ol:.2f}s | Модель: {pipe_ol.config.llm_model}")
print("Ответ:\n" + res_ol.answer.strip())
print(f"\nИспользовано цитат: {len(res_ol.citations)}")
for c in res_ol.citations[:3]:
    print(f"  - Документ: {c.source} | Стр: {c.page}")

# --- 2. LM STUDIO ---
print("\n🟣 ТЕСТИРОВАНИЕ LM STUDIO...")
switch_backend.switch_to("lmstudio")
dotenv.load_dotenv(override=True)

start_time = time.time()
pipe_lm = RAGPipeline()
res_lm = pipe_lm.query(question)
time_lm = time.time() - start_time

print("\n" + "-" * 75)
print(f"✅ [LM STUDIO] Время: {time_lm:.2f}s | Модель: {pipe_lm.config.llm_model}")
print("Ответ:\n" + res_lm.answer.strip())
print(f"\nИспользовано цитат: {len(res_lm.citations)}")
for c in res_lm.citations[:3]:
    print(f"  - Документ: {c.source} | Стр: {c.page}")

print("\n" + "=" * 75)
print("🏁 БЕНЧМАРК УСПЕШНО ЗАВЕРШЕН ДЛЯ ОБОИХ БЭКЕНДОВ!")
print("=" * 75)
