# RTX 4070 LLM & Embedding Server (Windows 11 LTSC)

Высокопроизводительный сервер инференса нейросетей и генерации векторных эмбеддингов для **Windows 11 PC с видеокартой NVIDIA GeForce RTX 4070 (12GB VRAM)**. 

Сервер разработан для бесшовной интеграции с ноутбуком-клиентом (**Arch Linux, SwayFX, Waybar**) и любыми OpenAI-совместимыми инструментами (RAG, Cursor, LibreChat, Open WebUI).

---

## ⚡ Ключевые возможности

1. **Горячая замена GGUF моделей в VRAM (`/admin/switch`)**:
   - Переключение между моделями (14B, 8B, Coder) за секунды без перезапуска сервера.
   - Настройка размера контекстного окна (`ctx_size`: 8192, 16384, 32768, 65536).
   - Полная разгрузка всех слоев модели на тензорные ядра RTX 4070 (`n_gpu_layers = -1`).
2. **Разгрузка VRAM до 0 МБ (`/admin/unload`)**:
   - Мгновенное освобождение 12 ГБ видеопамяти для игр, рендеринга или тяжелых задач одной кнопкой в Waybar или через CLI.
3. **OpenAI-совместимый Chat API (`/v1/chat/completions`)**:
   - Потоковая отдача токенов в реальном времени (**Server-Sent Events / SSE streaming**).
   - Стандартный non-streaming JSON ответ.
4. **Векторные эмбеддинги 768-D (`/v1/embeddings`)**:
   - Полная поддержка `nomic-embed-text-v1.5` для локального RAG поиска по документам.
5. **Телеметрия RTX 4070 (`/health`, `/admin/gpu`)**:
   - Мониторинг температуры GPU, занятой и свободной видеопамяти через `nvidia-smi`.
   - Субсекундный отклик для виджета Waybar.
6. **Безопасное подключение из ЛЮБОЙ внешней сети**:
   - Mesh VPN через **Tailscale** (без белого IP и проброса портов, сквозное шифрование WireGuard).
   - Публичный туннель через **Cloudflare Tunnel (`cloudflared`)**.
   - Встроенная авторизация по API-токенам (**Bearer Token Security**) для защиты сервера при выходе в интернет.

---

## 📋 Спецификация API Контракта

| Метод | Эндпоинт | Описание | Формат ответа |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Статус сервера и загруженная модель для Waybar | `{"status": "online", "loaded_llm": "<model.gguf>", "embedding_active": true, "ctx_size": 16384}` |
| `GET` | `/admin/models` | Список доступных GGUF файлов и активная модель | `{"available_gguf": ["Qwen2.5-14B..."], "active_llm": "..."}` |
| `POST` | `/admin/switch` | Горячая загрузка модели в VRAM | Payload: `{"model": "Llama-3.1-8B-Instruct-Q8_0.gguf", "ctx_size": 16384}` |
| `POST` | `/admin/unload` | Полное освобождение VRAM GPU до 0 MB | `{"status": "VRAM freed"}` |
| `POST` | `/v1/chat/completions` | Чат-инференс (OpenAI-совместимый, SSE) | OpenAI standard JSON или SSE stream chunks (`data: [DONE]`) |
| `POST` | `/v1/embeddings` | Генерация 768-мерных векторов для RAG | `{"object": "list", "data": [{"embedding": [768 floats]}]}` |
| `GET` | `/admin/gpu` | Телеметрия GPU RTX 4070 | `{"gpu_name": "RTX 4070", "vram_used_mb": 7200, "vram_total_mb": 12282}` |

---

## 🎯 Рекомендуемые GGUF Модели для RTX 4070 (12GB)

| Модель | Квантование | Размер | Требуемая VRAM | Рекомендуемый контекст | Назначение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Qwen2.5-14B-Instruct** | `Q4_K_M` | ~8.9 ГБ | ~10.5 ГБ | 16k – 32k | Универсальный топ: рассуждения, код, русский язык |
| **Llama-3.1-8B-Instruct** | `Q8_0` | ~8.5 ГБ | ~9.8 ГБ | 16k – 32k | Максимальное качество 8B модели без квант-потерь |
| **Llama-3.1-8B-Instruct** | `Q4_K_M` | ~4.9 ГБ | ~6.2 ГБ | 64k – 128k | Огромный контекст для анализа целых кодовых баз |
| **DeepSeek-Coder-V2-Lite** | `Q4_K_M` | ~9.1 ГБ | ~10.8 ГБ | 16k – 32k | Архитектура MoE, специализированная генерация кода |
| **nomic-embed-text-v1.5** | `Q8_0` | ~270 МБ | ~0.4 ГБ | 8192 | Высокоточный поиск для RAG (768 измерений) |

---

## 🚀 Быстрый старт на Windows 11

### Шаг 1. Автоматическая установка (PowerShell от Администратора)
Откройте PowerShell в папке `pc_server` и выполните:
```powershell
powershell -ExecutionPolicy Bypass -File setup_server.ps1
```
Скрипт выполнит:
1. Проверку Python 3.10–3.12 и драйверов NVIDIA CUDA.
2. Создание изолированного виртуального окружения `venv`.
3. Установку зависимостей и сборки `llama-cpp-python` с ускорением **CUDA 12**.
4. Добавление правила в **Брандмауэр Windows Defender** для входящего порта `8000`.
5. Инициализацию каталогов `models/`, `logs/` и файла `.env`.

### Шаг 2. Загрузка моделей
Скачайте рекомендованные модели прямо из Hugging Face:
```powershell
.\download_model.ps1 -Model qwen14b
.\download_model.ps1 -Model nomic-embed
```
Либо просто скопируйте любые `.gguf` файлы в папку `pc_server/models/`.

### Шаг 3. Запуск сервера
- **Вариант А (в 1 клик):** Дважды щелкните по `run_server.bat`.
- **Вариант Б (PowerShell):** `.\run_server.ps1`
- **Вариант В (Фоновая служба Windows):**
  Автозапуск сервера при включении ПК в фоновом режиме:
  ```powershell
  .\install_windows_service.ps1 -Action install
  .\install_windows_service.ps1 -Action start
  ```

---

## 🌐 Подключение из любой внешней сети (не только из локальной!)

Подробное пошаговое руководство смотрите в файле **[REMOTE_ACCESS_GUIDE.md](file:///home/alex/rag%20exe/pc_server/REMOTE_ACCESS_GUIDE.md)**.

### Способ 1: Tailscale (Рекомендуемый — Mesh VPN, Zero-Config)
1. На Windows 11 запустите:
   ```powershell
   .\setup_tailscale.ps1
   ```
   Скрипт выведет ваш постоянный Tailscale IP (например, `100.84.120.45`).
2. На ноутбуке с Arch Linux:
   ```bash
   sudo pacman -S tailscale
   sudo systemctl enable --now tailscaled
   sudo tailscale up
   ```
3. Пропишите IP в конфиг клиента `~/.config/llm-remote/config.env`:
   ```env
   LLM_SERVER_IP="100.84.120.45"
   LLM_SERVER_PORT="8000"
   ```
**Готово!** Теперь ваш Arch Linux ноутбук будет мгновенно подключаться к RTX 4070 из кафе, отеля, мобильного интернета 5G или в путешествиях.

### Способ 2: Cloudflare Tunnel (HTTPS без белого IP)
```powershell
.\setup_cloudflare_tunnel.ps1
```
Cloudflare сгенерирует публичный защищенный адрес вида `https://xxxx.trycloudflare.com`.

---

## 🧪 Тестирование и верификация

В папке находятся готовые тесты:
1. **Модульные тесты API (все 8 сценариев):**
   ```bash
   python -m unittest test_server.py -v
   ```
2. **Тесты граничных случаев (Boundary / Edge Cases):**
   ```bash
   python -m unittest test_edge_cases.py -v
   ```
3. **End-to-End тест с реальным клиентом `Remote4070Client`:**
   ```bash
   python test_e2e_client.py
   ```
