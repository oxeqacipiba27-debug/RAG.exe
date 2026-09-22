import json

with open('evaluation_100_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total questions evaluated: {len(data)}")
correct_count = sum(1 for x in data if x['is_correct'])
print(f"Correct: {correct_count}/100 ({correct_count}%)")

with open('report_100_summary.txt', 'w', encoding='utf-8') as out:
    for x in data:
        status_str = "Корректен" if x['is_correct'] else "Некорректен (сработал Zero-Retrieval отказ RAG)"
        out.write(f"Вопрос {x['number']}: {x['question']}\n")
        out.write(f"Ответ RAG: {x['rag_answer'].replace(chr(10), ' ')}\n")
        out.write(f"Корректность относительно БД: {status_str}\n")
        out.write(f"Источник / факт в БД: {x['expected_hint']}\n")
        out.write(f"Пояснение: {x['reason']}\n")
        out.write("-" * 60 + "\n")

print("Saved report_100_summary.txt")
