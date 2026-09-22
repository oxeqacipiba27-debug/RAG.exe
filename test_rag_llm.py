import json
import httpx
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('rag_index.json', 'r', encoding='utf-8') as f:
    db = json.load(f)

chunks = [x for x in db if '6a7d65434d2f9.pdf' in x['source']]
context = "\n\n".join([f"[Источник: {c['source']}, стр. {c['page']}]:\n{c['text']}" for c in chunks])

system_prompt = (
    "Ты — интеллектуальный ассистент по базе документов. "
    "Отвечай на вопрос строго на основе приведенного контекста. "
    "Если в контексте нет информации, прямо напиши: 'В документах нет информации по этому вопросу.'\n\n"
    f"КОНТЕКСТ:\n{context}"
)

client = httpx.Client(base_url='http://127.0.0.1:1234/v1', timeout=60.0, trust_env=False)
payload = {
    'model': 'qwen2.5-14b-instruct-1m',
    'messages': [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': 'Какая школьная форма в 5 классе? Опиши цвет и требования.'}
    ],
    'temperature': 0.2
}

try:
    resp = client.post('/chat/completions', json=payload)
    print('Status:', resp.status_code)
    print('Response:\n', resp.json()['choices'][0]['message']['content'])
except Exception as e:
    print('Error:', e)
