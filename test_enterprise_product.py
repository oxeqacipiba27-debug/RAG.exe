"""
test_enterprise_product.py — Комплексный сквозной тест автономного RAG-продукта.
"""

import sys
import os
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

print("=" * 60)
print("  ТЕСТИРОВАНИЕ АВТОНОМНОГО КОРПОРАТИВНОГО RAG")
print("=" * 60)

# 1. Проверка модулей
print("\n[1/5] Проверка импортов и компиляции модулей...")
import dotenv
dotenv.load_dotenv(override=True)
import server_manager
from rag_engine import RAGPipeline, sanitize_llm_output, CONFIG
print("  [✓] server_manager и rag_engine успешно импортированы.")

# 2. Проверка доступности активного локального сервера и моделей
provider = os.getenv("LLM_PROVIDER", "LM_STUDIO").upper()
print(f"\n[2/5] Проверка активного ИИ-бэкенда ({provider})...")

if "OLLAMA" in provider:
    online = server_manager.is_ollama_online()
    print(f"  Статус Ollama: {'В СЕТИ 🟢' if online else 'ОФФЛАЙН 🔴'}")
    assert online, "Служба Ollama должна быть запущена для теста!"
    loaded = server_manager.get_ollama_loaded_models()
    print(f"  Доступные модели в Ollama: {loaded}")
    assert any("qwen" in m.lower() for m in loaded), "Модель qwen2.5 должна быть в Ollama!"
    assert any("nomic" in m.lower() or "embed" in m.lower() for m in loaded), "Модель nomic-embed-text должна быть в Ollama!"
    print("  [✓] Обе модели (LLM + Эмбеддинги) доступны в Ollama.")
else:
    online = server_manager.is_server_online()
    print(f"  Статус сервера LM Studio: {'В СЕТИ 🟢' if online else 'ОФФЛАЙН 🔴'}")
    assert online, "Сервер LM Studio должен быть запущен для теста!"
    loaded = server_manager.get_loaded_models()
    print(f"  Загруженные модели в памяти: {loaded}")
    assert any("qwen" in m.lower() for m in loaded), "Модель qwen2.5 должна быть в памяти LM Studio!"
    assert any("nomic" in m.lower() or "embed" in m.lower() for m in loaded), "Модель nomic-embed-text должна быть в памяти LM Studio!"
    print("  [✓] Обе модели (LLM + Эмбеддинги) активны в GPU.")

# 3. Проверка CJK-санитайзера
print("\n[3/5] Проверка CJK-санитайзера...")
test_dirty = "Согласно правилам школы (第3条) форма должна быть классической (校规)."
cleaned = sanitize_llm_output(test_dirty)
assert "第" not in cleaned and "校" not in cleaned, "Иероглифы должны быть удалены!"
assert "Согласно правилам школы" in cleaned and "форма должна быть классической" in cleaned
print(f"  Очищенный текст: {cleaned}")
print("  [✓] CJK-санитайзер работает на 100%.")

# 4. Сквозной RAG запрос
print("\n[4/5] Выполнение сквозного запроса через пайплайн...")
pipeline = RAGPipeline(index_file="rag_index.json")

query = "какой цвет формы для начальных 1-4 классов?"
print(f"  Вопрос: '{query}'")
resp = pipeline.query(query)
print(f"\n  [Ответ модели]:\n{resp.answer}\n")
print(f"  [Цитаты ({len(resp.citations)})]:")
for c in resp.citations[:2]:
    print(f"   - Документ: {c.source}, Стр: {c.page}")

assert len(resp.answer.strip()) > 10, "Ответ модели не должен быть пустым!"
assert len(resp.citations) > 0, "Должны присутствовать подтверждающие первоисточники!"
print("  [✓] Сквозной RAG-ответ получен корректно.")

# 5. Проверка файлов презентации и запуска
print("\n[5/5] Проверка файлов поставки продукта...")
required_files = ["rag_gui.py", "server_manager.py", "run_app.py", "start_rag.bat", "PRODUCT_MANUAL.md", "rag_index.json"]
for rf in required_files:
    assert Path(rf).exists(), f"Файл {rf} должен существовать!"
    print(f"  [✓] {rf} присутствует.")

print("\n" + "=" * 60)
print("  ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ! ПРОДУКТ ГОТОВ К ДЕМОНСТРАЦИИ.")
print("=" * 60)
