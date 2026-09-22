import sys
import os
import json
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rag_engine import RAGPipeline, sanitize_llm_output, count_tokens

print("--- Step 1: Initializing RAGPipeline with Ollama ---")
base_url = "http://127.0.0.1:11434/v1"
llm_model = "qwen2.5:14b"
embed_model = "nomic-embed-text:latest"

try:
    pipeline = RAGPipeline(
        index_file="rag_index.json",
        llm_model=llm_model,
        embed_model=embed_model,
        base_url=base_url
    )
    print("Pipeline initialized successfully.")
except Exception as e:
    print(f"FAILED to initialize pipeline: {e}")
    sys.exit(1)

print("\n--- Step 2: Testing Retriever Search with Ollama ---")
query = "Кто является руководителем организации?"
try:
    hits, reformulated_q, is_zero = pipeline.retriever.search(
        raw_query=query,
        history=[],
        top_k=5
    )
    print(f"Hits found: {len(hits)}, is_zero: {is_zero}, reformulated: {reformulated_q}")
except Exception as e:
    print(f"FAILED in retriever.search: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n--- Step 3: Testing Context Assembler ---")
try:
    reordered_hits = pipeline.retriever.reorder_lost_in_the_middle(hits)
    context_limit_tokens = 2500
    context_xml, accepted_hits = pipeline.context_assembler.assemble(
        reordered_hits,
        max_tokens=context_limit_tokens
    )
    print(f"Context assembled: {len(context_xml)} chars, accepted: {len(accepted_hits)}")
except Exception as e:
    print(f"FAILED in context_assembler: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n--- Step 4: Testing Streaming /chat/completions to Ollama ---")
try:
    api_messages = [
        {"role": "system", "content": f"{pipeline.SYSTEM_PROMPT}\n\n{context_xml}"},
        {"role": "user", "content": query}
    ]
    payload = {
        "model": llm_model,
        "messages": api_messages,
        "temperature": 0.28,
        "top_p": 0.8,
        "presence_penalty": 0.1,
        "stop": ["<|im_end|>", "<|endoftext|>"],
        "max_tokens": 1500,
        "stream": True
    }
    raw_response = ""
    with pipeline.client.stream("POST", "/chat/completions", json=payload, timeout=90.0) as stream_resp:
        print(f"HTTP Status code: {stream_resp.status_code}")
        if stream_resp.status_code != 200:
            err = stream_resp.read().decode("utf-8", errors="ignore")
            print(f"ERROR BODY: {err}")
        else:
            for line in stream_resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    data_obj = json.loads(data_str)
                    delta = data_obj["choices"][0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        raw_response += delta["content"]
                        sys.stdout.write(delta["content"])
                        sys.stdout.flush()
    print("\n\nSTREAM COMPLETE. Total response length:", len(raw_response))
except Exception as e:
    print(f"\nFAILED in stream: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
