import httpx
import time
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

c = httpx.Client(base_url='http://127.0.0.1:1234/v1', trust_env=False, timeout=60.0)

t0 = time.time()
r = c.post('/chat/completions', json={
    'model': 'qwen2.5-14b-instruct-1m',
    'messages': [{'role': 'user', 'content': 'Привет! Ответь одним словом.'}],
    'max_tokens': 15
})
print(f"Time: {time.time()-t0:.2f}s")
print("Response:", r.json()['choices'][0]['message']['content'])
