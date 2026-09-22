import sys
import os
import json
import time
from pathlib import Path

# Кодировка UTF-8 для Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, ".")

import server_manager
from rag_engine import RAGPipeline
from scratch.run_100_eval import QUESTIONS, evaluate_answer

# Проверяем, загружена ли LLM
loaded = server_manager.get_loaded_models()
if server_manager.DEFAULT_LLM not in loaded:
    print(f"Загрузка модели {server_manager.DEFAULT_LLM}...")
    server_manager.load_model_via_cli(server_manager.DEFAULT_LLM, is_llm=True)

with open("evaluation_100_results.json", "r", encoding="utf-8") as f:
    results = json.load(f)

# Ищем вопросы, где была ошибка генерации
questions_dict = {q["num"]: q for q in QUESTIONS}
failed_indices = [
    i for i, r in enumerate(results)
    if "Ошибка генерации" in r.get("rag_answer", "") or "terminated" in r.get("rag_answer", "")
]

print(f"Найдено вопросов для повторного прогона: {len(failed_indices)}")

if failed_indices:
    print("Инициализация RAGPipeline...")
    pipeline = RAGPipeline(
        index_file="rag_index.json",
        llm_model="qwen2.5-14b-instruct-1m",
        embed_model="text-embedding-nomic-embed-text-v1.5",
        base_url="http://127.0.0.1:1234/v1"
    )

    for idx in failed_indices:
        q_num = results[idx]["number"]
        q_meta = questions_dict[q_num]
        q_text = q_meta["question"]
        expected = q_meta["expected_facts"]
        hint = q_meta["db_doc_hint"]
        
        t0 = time.time()
        try:
            resp = pipeline.query(
                user_query=q_text,
                top_k=5,
                max_tokens=180,
                temperature=0.15
            )
            elapsed = time.time() - t0
            is_correct, reason = evaluate_answer(resp.answer, expected, resp.citations)
            verdict = "КОРРЕКТЕН ✅" if is_correct else "НЕКОРРЕКТЕН ❌"
            
            results[idx] = {
                "number": q_num,
                "category": q_meta["category"],
                "question": q_text,
                "rag_answer": resp.answer.strip(),
                "citations": [f"{c.source} (стр. {c.page})" for c in resp.citations[:3]],
                "is_correct": is_correct,
                "verdict": verdict,
                "reason": reason,
                "latency_sec": round(elapsed, 2),
                "expected_hint": hint
            }
            print(f"[{q_num:03d}/100] {verdict} ({elapsed:.1f}s) | {q_text[:50]}...")
        except Exception as e:
            print(f"[{q_num:03d}/100] ОШИБКА: {e}")

    with open("evaluation_100_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Обновлен evaluation_100_results.json")

    # Пересоздаем отчет
    correct_count = sum(1 for x in results if x["is_correct"])
    print(f"Итого корректных ответов: {correct_count}/100 ({correct_count}%)")

    with open("report_100_summary.txt", "w", encoding="utf-8") as out:
        for x in results:
            status_str = "Корректен" if x["is_correct"] else "Некорректен (Zero-Retrieval отказ RAG)"
            out.write(f"Вопрос {x['number']}: {x['question']}\n")
            out.write(f"Ответ RAG: {x['rag_answer'].replace(chr(10), ' ')}\n")
            out.write(f"Корректность относительно БД: {status_str}\n")
            out.write(f"Источник / факт в БД: {x['expected_hint']}\n")
            out.write(f"Пояснение: {x['reason']}\n")
            out.write("-" * 60 + "\n")
    print("Обновлен report_100_summary.txt")
