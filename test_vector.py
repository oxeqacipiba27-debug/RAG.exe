import json
import math
import sys
import io
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

client = httpx.Client(base_url='http://127.0.0.1:1234/v1', trust_env=False, timeout=30.0)

query = "какая одежда нужна для нашей школы"
print(f"Testing query: '{query}'")

resp = client.post('/embeddings', json={'input': query, 'model': 'text-embedding-nomic-embed-text-v1.5'})
if resp.status_code != 200:
    print(f"Error embedding: {resp.status_code} {resp.text}")
    sys.exit(1)

q_vec = resp.json()['data'][0]['embedding']

with open('rag_index.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

def cosine_similarity(v1, v2):
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0: return 0.0
    return dot / (norm1 * norm2)

scores = []
for i, item in enumerate(data):
    if 'vector' in item:
        s = cosine_similarity(q_vec, item['vector'])
        scores.append((s, i))

scores.sort(reverse=True, key=lambda x: x[0])

print("\nTop 10 Vector Search Results:")
for s, i in scores[:10]:
    src = data[i]['source']
    pg = data[i]['page']
    snippet = data[i]['text'][:120].replace('\n', ' ')
    print(f"Score {s:.4f} | {src} (p.{pg}): {snippet}...")

for rank, (s, i) in enumerate(scores):
    src = data[i]['source']
    if '6a7d65434d2f9' in src or '6a7d653763d0c' in src or '6a7d6551966ae' in src:
        print(f"Uniform Doc Rank {rank}: score {s:.4f} | {src}")

