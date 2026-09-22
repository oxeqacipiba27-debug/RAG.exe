import json
import httpx
import sys

sys.stdout.reconfigure(encoding='utf-8')
from rag_gui import search_index

with open('rag_index.json', 'r', encoding='utf-8') as f:
    db = json.load(f)

client = httpx.Client(base_url='http://127.0.0.1:1234/v1', trust_env=False)

tests = [
    'какая форма в 5 классе',
    'форма для 1-4 классов',
    'форма для 10-11 класса',
    '6a7d65434d2f9.pdf',
    'какая форма в 5 классе а для мальчиков?'
]

for t in tests:
    print(f"=== TEST: {t} ===")
    res = search_index(t, db, 3, 'text-embedding-nomic-embed-text-v1.5', client)
    for r in res:
        src = r['source']
        p = r['page']
        snip = r['text'][:100].replace('\n', ' ')
        print(f"  -> [{src}, стр. {p}]: {snip}...")
    print()
