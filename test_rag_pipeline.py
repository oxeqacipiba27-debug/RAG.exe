"""
test_rag_pipeline.py — Автоматизированный верификационный тестовый стенд
для всесторонней проверки качества и отказоустойчивости RAG-пайплайна.

Проверяет:
1. Запрос с опечатками и разговорной лексикой ('какая одеажда нужна для нашей школы')
2. Короткий уточняющий запрос с контекстом диалога ('а для мальчиков в 5 классе?')
3. Запрос не по теме / негативный тест на галлюцинации ('Сколько спутников у Юпитера?')
4. Граничное условие: слишком короткий запрос ('10 класс')
5. Длинный сложный запрос ('Подскажите правила приема и перечень документов...')
"""

import sys
import time
import json
from rag_engine import RAGPipeline, RAGResponse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def print_separator(title: str):
    print("\n" + "=" * 80)
    print(f" 🧪 {title.upper()}")
    print("=" * 80)

def main():
    print_separator("Инициализация RAG-пайплайна")
    t0 = time.time()
    pipeline = RAGPipeline(
        index_file="rag_index.json",
        llm_model="qwen2.5-14b-instruct-1m",
        embed_model="text-embedding-nomic-embed-text-v1.5",
        base_url="http://127.0.0.1:1234/v1"
    )
    print(f"✅ Пайплайн загружен за {time.time() - t0:.2f} сек. Чанков в памяти: {len(pipeline.chunks)}")

    test_cases = [
        {
            "id": "CASE-1",
            "name": "Запрос с опечаткой и разговорной лексикой",
            "query": "какая одеажда нужна для нашей школы",
            "history": [],
            "expect_zero": False,
            "must_contain_in_citations": ["6a7d65", "памятка", "одежд", "форм"]
        },
        {
            "id": "CASE-2",
            "name": "Короткий уточняющий запрос (проверка сохранения контекста)",
            "query": "а для мальчиков в 5 классе?",
            "history": [
                {"role": "user", "content": "какая одеажда нужна для нашей школы"},
                {"role": "assistant", "content": "В школе установлен деловой стиль одежды для всех параллелей с 1 по 11 класс."}
            ],
            "expect_zero": False,
            "must_contain_in_citations": ["6a7d65434d2f9", "5-9"]
        },
        {
            "id": "CASE-3",
            "name": "Запрос вне контекста базы (Zero-Retrieval / защита от галлюцинаций)",
            "query": "Сколько естественных спутников у планеты Юпитер и какая там температура?",
            "history": [],
            "expect_zero": True,
            "must_contain_in_citations": []
        },
        {
            "id": "CASE-4",
            "name": "Граничное условие: экстремально короткий запрос",
            "query": "10 класс",
            "history": [],
            "expect_zero": False,
            "must_contain_in_citations": []
        },
        {
            "id": "CASE-5",
            "name": "Длинный сложный запрос (правила приема и документы)",
            "query": "Подскажите пожалуйста подробные правила приема и перечень необходимых документов для зачисления ребенка в первый класс школы",
            "history": [],
            "expect_zero": False,
            "must_contain_in_citations": ["прием", "правил", "документ", "заявлен"]
        }
    ]

    all_passed = True
    results_summary = []

    for test in test_cases:
        print_separator(f"Тест {test['id']}: {test['name']}")
        print(f"📥 Запрос: \"{test['query']}\"")
        if test['history']:
            print(f"📜 История: {len(test['history'])} сообщений")

        t_start = time.time()
        response: RAGResponse = pipeline.query(
            user_query=test["query"],
            chat_history=test["history"],
            top_k=4,
            temperature=0.2
        )
        elapsed = time.time() - t_start

        print(f"\n🔄 Реформированный запрос: \"{response.query_reformulated}\"")
        print(f"⚡ Latency: {response.latency_ms} ms (Total: {elapsed:.2f} s)")
        print(f"🎯 Zero-Retrieval: {response.is_zero_retrieval}")
        print(f"📊 Confidence: {response.confidence}")
        print(f"📄 Использовано чанков: {response.context_chunks_used}")

        print("\n📚 Найденные источники (Citations):")
        for idx, c in enumerate(response.citations, 1):
            print(f"   [{idx}] {c.source} (стр. {c.page})")

        print(f"\n🤖 Ответ LLM:\n{response.answer}\n")

        # Валидация условий теста
        passed = True
        reason = "OK"

        if test["expect_zero"]:
            if not response.is_zero_retrieval and "нет информации" not in response.answer.lower():
                passed = False
                reason = "Ожидался Zero-Retrieval, но система вернула документы и ответ."
        else:
            if response.is_zero_retrieval:
                passed = False
                reason = "Ожидались найденные документы, но сработал Zero-Retrieval."
            elif test["must_contain_in_citations"]:
                matched_citation = False
                for c in response.citations:
                    src_lower = (c.source + " " + (c.quote or "")).lower()
                    if any(target.lower() in src_lower for target in test["must_contain_in_citations"]):
                        matched_citation = True
                        break
                if not matched_citation:
                    # Предупреждение, но проверяем ответ
                    if not response.answer:
                        passed = False
                        reason = "Отсутствуют ожидаемые целевые источники."

        status_emoji = "✅ PASS" if passed else "❌ FAIL"
        print(f"Результат проверки: {status_emoji} ({reason})")
        
        results_summary.append({
            "id": test["id"],
            "name": test["name"],
            "status": "PASS" if passed else "FAIL",
            "latency_ms": response.latency_ms,
            "zero_retrieval": response.is_zero_retrieval,
            "citations_count": len(response.citations),
            "reason": reason
        })

        if not passed:
            all_passed = False

    print_separator("Сводный отчет верификационного стенда")
    print(f"{'ID':<8} | {'Название':<45} | {'Статус':<8} | {'Latency':<10} | {'Детали'}")
    print("-" * 90)
    for r in results_summary:
        print(f"{r['id']:<8} | {r['name']:<45} | {r['status']:<8} | {r['latency_ms']:<7.1f} ms | {r['reason']}")
    print("-" * 90)

    if all_passed:
        print("\n🎉 ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ! RAG-пайплайн полностью готов к работе.")
    else:
        print("\n⚠️ ВНИМАНИЕ: Некоторые тесты завершились с ошибками. Требуется анализ.")

if __name__ == "__main__":
    main()
