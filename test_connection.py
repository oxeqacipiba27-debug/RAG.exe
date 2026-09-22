"""
Скрипт быстрой проверки связи с LM Studio.
Проверяет доступность сервера и выводит список загруженных моделей.
"""
import os
import sys

# Настройка кодировки для корректного вывода в терминале Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Исключаем локальный адрес из системных прокси
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import httpx

URL = "http://127.0.0.1:1234/v1/models"

print("=" * 60)
print(f"[TEST] Проверка связи с LM Studio по адресу: {URL}")
print("=" * 60)

try:
    with httpx.Client(trust_env=False, timeout=3.0) as client:
        response = client.get(URL)
        data = response.json()

    print("\n[OK] Связь с сервером LM Studio успешно установлена!")
    print("\nЗагруженные модели в LM Studio:")
    models = data.get("data", [])
    if models:
        for m in models:
            print(f"  * {m.get('id', 'unknown')}")
    else:
        print("  (Модели пока не загружены. Выберите и загрузите модель в LM Studio во вкладке Local Server)")

except httpx.ConnectError:
    print("\n[ВНИМАНИЕ] Сервер LM Studio не запущен (порт 1234 закрыт).")
    print("\nИнструкция по запуску:")
    print("1. Откройте LM Studio.")
    print("2. Перейдите во вкладку 'Developer' / 'Local Server' (иконка <-> на левой панели).")
    print("3. В верхней строке выберите модель (например, Qwen 2.5 7B или Llama 3.1 8B).")
    print("4. Нажмите зеленую кнопку 'Start Server'.")
    print("5. Запустите этот тест снова: python test_connection.py")

except Exception as err:
    print(f"\n[ОШИБКА] Не удалось подключиться: {err}")
