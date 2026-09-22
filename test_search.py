import json, httpx
from rag_gui import search_index
with open('rag_index.json', 'r', encoding='utf-8') as f: index_data = json.load(f)
client = httpx.Client(base_url='http://127.0.0.1:1234/v1', trust_env=False)
results = search_index('какая форма в 5 классе 6a7d65434d2f9.pdf', index_data, 6, 'text-embedding-nomic-embed-text-v1.5', client)
print('Sources:', [r['source'] for r in results])
