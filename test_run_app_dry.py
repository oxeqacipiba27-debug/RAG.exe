import sys
import os
import subprocess
import time
import httpx

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import dotenv
dotenv.load_dotenv(override=True)
import server_manager

print("=" * 60)
print("  ТЕСТ ЗАПУСКА RAG С БЭКЕНДОМ OLLAMA")
print(f"  Провайдер: {os.getenv('LLM_PROVIDER')}")
print("=" * 60)

# 1. Проверяем стек Ollama
print("\n[1/3] Проверка ensure_ollama_stack...")
ok, msg = server_manager.ensure_ollama_stack(progress_callback=print)
print("ensure_ollama_stack результат:", ok, msg)
assert ok, f"Ollama стек должен быть готов: {msg}"

# 2. Запускаем Streamlit rag_gui.py на тестовом порту
test_port = 8599
print(f"\n[2/3] Запуск Streamlit на тестовом порту {test_port}...")
proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "rag_gui.py", "--server.port", str(test_port), "--server.headless", "true"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="replace"
)

ready = False
try:
    for i in range(25):
        time.sleep(1.0)
        # Проверяем, не упал ли процесс
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=2)
            print("STREAMLIT УПАЛ! Вывод:")
            print("STDOUT:", stdout)
            print("STDERR:", stderr)
            raise RuntimeError(f"Streamlit завершился с кодом {proc.returncode}")
        
        try:
            with httpx.Client(timeout=1.0, trust_env=False) as client:
                r = client.get(f"http://localhost:{test_port}")
                if r.status_code == 200:
                    ready = True
                    print(f"  [OK] Streamlit ответил 200 OK на секунде {i+1}!")
                    break
        except Exception:
            pass

    assert ready, "Streamlit должен успешно запуститься и ответить 200 OK!"
    print("\n[3/3] Проверка завершения работы...")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print("\n🎉 ТЕСТ ЗАПУСКА RAG ЧЕРЕЗ OLLAMA УСПЕШНО ПРОЙДЕН!")
