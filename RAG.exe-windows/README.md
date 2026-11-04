# EXSCIO 2.0 — Автономный комплекс ИИ (Windows 10/11)

Автономная система поиска и ответов на основе документов (Retrieval-Augmented Generation, RAG) с локальным запуском больших языковых моделей на базе Windows 10/11.

---

## 🚀 Быстрый старт

### 1. Требования к системе
- **ОС**: Windows 10 (версия 2004+) или Windows 11 (64-bit).
- **Python**: Python 3.10 – 3.12 (с добавлением в `PATH`).
- **GPU (Рекомендуется)**: NVIDIA GeForce RTX (от 8 ГБ VRAM) для локального инференса 14B моделей на GPU.
- **Движок WebView**: Microsoft Edge WebView2 (предустановлен в Windows 10/11).

### 2. Установка зависимостей
Откройте терминал `cmd.exe` или PowerShell в папке приложения:
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> **Примечание по CUDA**: Для работы PyTorch с ускорением на локальном GPU выполните:
> ```cmd
> pip install torch --index-url https://download.pytorch.org/whl/cu121
> ```

### 3. Запуск приложения

- **Основной запуск**:
  Дважды кликните на `start.bat` или выполните:
  ```cmd
  start.bat
  ```
  Скрипт автоматически подготовит окружение, проверит бэкенд, запустит Streamlit и откроет десктопное окно на базе Microsoft Edge WebView2.

- **Запуск через веб-браузер (без pywebview)**:
  ```cmd
  start.bat --browser
  ```

---

## 🎛️ Управление бэкендами и лаунчеры

В комплект входят специализированные батч-файлы:

| Файл | Описание |
| :--- | :--- |
| `start.bat` | Универсальный лаунчер с автосозданием `.env` и фоллбэком на веб-браузер |
| `start_rag.bat` | Прямой запуск GUI через `run_app.py` |
| `start_lmstudio.bat` | Автопереключение на LM Studio (порт 1234) и старт |
| `start_ollama.bat` | Автопереключение на нативную службу Ollama (порт 11434) и старт |
| `start_docker.bat` | Проверка подсистемы WSL2, запуск контейнеров Docker и старт RAG |
| `stop_docker.bat` | Остановка Docker контейнеров (`docker compose down`) |
| `switch_backend.bat` | Интерактивное меню переключения между всеми 4 бэкендами |
| `start_api.bat` | Запуск интеграционного FastAPI/SSE сервера (REST API) |
| `start_telegram_bot.bat`| Запуск Telegram-бота на базе aiogram 3.x |

---

## 🧠 Архитектурные стандарты (GEMINI.md)

1. **Разделение ресурсов GPU/CPU**:
   - Генерация текста (14B LLM, например Qwen2.5-14B) работает на **GPU (VRAM)** с лимитом контекста `-c 8192`.
   - Векторизация и расчет эмбеддингов (Nomic Embed v1.5 strictly 768-D) ВСЕГДА выполняются на **CPU (RAM)** (`EMBEDDING_DEVICE=cpu`). Это гарантирует отсутствие ошибок Out-of-Memory (OOM).
2. **Безопасность кодировки**:
   - Все консольные логи и обработчики используют кодировку `UTF-8` и совместимые ASCII-маркеры `[OK]`, `[!]`, `[X]`, исключая `UnicodeEncodeError` в кодовой странице `cp1251`.
3. **Очистка портов**:
   - Перед стартом порт `8501` проверяется через `netstat -ano`, оставшиеся зомби-процессы Python корректно завершаются через `taskkill /F /PID`.
4. **Контроль WSL2**:
   - Перед запуском Docker выполняется проверка подсистемы WSL2 (`wsl -l -q`), предотвращая зависание на `docker_engine`.

---

## 📁 Структура папки

```text
RAG.exe-windows/
├── .env.example              # Шаблон конфигурации
├── .env                      # Активный конфигурационный файл
├── .env.lmstudio             # Профиль LM Studio
├── .env.ollama               # Профиль Ollama Native
├── .env.docker               # Профиль Docker WSL2
├── .env.rtx4070              # Профиль Remote RTX 4070
├── .streamlit/config.toml    # Параметры темы и порта Streamlit
├── api/                      # REST / SSE эндпоинты
├── data/                     # Исходные документы для индексации
├── ingestion/                # Парсеры PDF, DOCX, XLSX
├── static/                   # Статические ресурсы (логотипы, стили)
├── tests/                    # Интеграционные и модульные тесты
├── docker-compose.yml        # Конфигурация контейнеров Ollama
├── rag_engine.py             # Ядро RAG (гибридный поиск, BM25, RRF)
├── rag_gui.py                # Интерфейс на Streamlit
├── run_app.py                # Автономный загрузчик pywebview Edge WebView2
├── server_manager.py         # Менеджер бэкендов, памяти VRAM и WSL2
├── switch_backend.py         # Модуль переключения профилей
├── run_api.py                # Запуск FastAPI сервера
├── telegram_bot.py           # Telegram бот
├── requirements.txt          # Зависимости Python
├── rag_icon.ico              # Иконка приложения для Windows
├── rag_index.json            # База знаний векторного индекса
└── start*.bat                # Батч-лаунчеры Windows
```
