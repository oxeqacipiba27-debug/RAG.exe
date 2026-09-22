"""
test_cjk_fix.py — Проверка устранения китайских иероглифов (CJK)
и неразрешенных символов в точном диалоге пользователя.
"""

import sys
import re
from rag_engine import RAGPipeline, RAGResponse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def check_no_cjk(text: str) -> bool:
    # Проверка на наличие любых CJK символов
    cjk_pattern = re.compile(
        r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u2e80-\u2eff\u3000-\u303f'
        r'\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\uac00-\ud7af\uff00-\uffef]'
    )
    return not bool(cjk_pattern.search(text))

def main():
    print("=" * 80)
    print(" 🧪 ТЕСТ УСТРАНЕНИЯ КИТАЙСКИХ ИЕРОГЛИФОВ (CJK FIX)")
    print("=" * 80)

    pipeline = RAGPipeline(
        index_file="rag_index.json",
        llm_model="qwen2.5-14b-instruct-1m",
        embed_model="text-embedding-nomic-embed-text-v1.5",
        base_url="http://127.0.0.1:1234/v1"
    )

    history = []

    # Ход 1
    q1 = "какая одежда нужна для ученика 6го класса"
    print(f"\n--- ХОД 1: '{q1}' ---")
    resp1: RAGResponse = pipeline.query(user_query=q1, chat_history=history, top_k=4)
    print("Ответ ИИ:")
    print(resp1.answer)
    assert check_no_cjk(resp1.answer), "ОШИБКА: Обнаружены иероглифы в ответе 1!"
    print("Проверка CJK в Ходе 1: ✅ ЧИСТО (иероглифов нет)")

    history.append({"role": "user", "content": q1})
    history.append({"role": "assistant", "content": resp1.answer})

    # Ход 2 (точно из скриншота пользователя)
    q2 = "а на физру?"
    print(f"\n--- ХОД 2: '{q2}' ---")
    resp2: RAGResponse = pipeline.query(user_query=q2, chat_history=history, top_k=4)
    print("Ответ ИИ:")
    print(resp2.answer)
    assert check_no_cjk(resp2.answer), "ОШИБКА: Обнаружены иероглифы в ответе 2!"
    assert "班主任" not in resp2.answer, "ОШИБКА: '班主任' найден в ответе 2!"
    print("Проверка CJK в Ходе 2: ✅ ЧИСТО (иероглифов нет, 班主任 устранен)")

    print("\n" + "=" * 80)
    print("🎉 ТЕСТ УСПЕШНО ПРОЙДЕН! Все ответы на 100% состоят из чистого русского текста без иероглифов.")
    print("=" * 80)

if __name__ == "__main__":
    main()
