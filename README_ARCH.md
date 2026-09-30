# EXSCIO 2.0 — Arch Linux Edition

> **Автономный комплекс искусственного интеллекта и корпоративного поиска (RAG)**  
> *Специальная сборка, адаптированная и оптимизированная для операционных систем Arch Linux, Manjaro и EndeavourOS.*

---

## 📋 Оглавление
1. [Архитектура и особенности сборки](#-архитектура-и-особенности-сборки)
2. [Системные требования и зависимости](#-системные-требования-и-зависимости)
3. [Быстрый запуск (Автоматическая установка)](#-быстрый-запуск-автоматическая-установка)
4. [Ручная установка](#-ручная-установка)
5. [Сборка пакета через PKGBUILD](#-сборка-пакета-через-pkgbuild)
6. [Управление ИИ-бэкендами на Arch Linux](#-управление-ии-бэкендами-на-arch-linux)
   - [Ollama Native (Рекомендуется для Arch)](#1-ollama-native)
   - [LM Studio (AUR / AppImage)](#2-lm-studio)
   - [Docker Compose](#3-docker-compose)
7. [Десктопный интерфейс и WebKit2GTK](#-десктопный-интерфейс-и-webkit2gtk)
8. [Управление службами Systemd](#-управление-службами-systemd)
9. [Справочник скриптов запуска](#-справочник-скриптов-запуска)
10. [Диагностика и устранение неполадок](#-диагностика-и-устранение-неполадок)

---

## 🚀 Архитектура и особенности сборки

Данная редакция EXSCIO спроектирована специально для экосистемы **Arch Linux**:

- **POSIX Shell Scripts**: Все устаревшие Windows `.bat` скрипты полностью заменены на надежные bash-скрипты стандарта POSIX с строгой обработкой ошибок (`set -eo pipefail`).
- **WebKit2GTK Desktop**: Поддержка нативного легковесного графического окна через `pywebview` с бэкендом `WebKit2GTK-4.1` (GTK3). В случае запуска в headless-окружении (SSH, удаленный сервер, отсутствие `$DISPLAY` / `$WAYLAND_DISPLAY`) предусмотрен бесшовный переход в стандартный браузер.
- **Аппаратная телеметрия GPU**: Встроенный модуль `server_manager.py` автоматически опрашивает видеокарты:
  - NVIDIA: сбор телеметрии через `nvidia-smi` (VRAM, драйвер, утилизация);
  - AMD: поддержка ROCm через `rocm-smi`;
  - Интеллектуальный fallback: PyTorch CUDA / ROCm и опрос шины `lspci`.
- **Systemd Интеграция**: Готовые юниты пользовательских служб `exscio.service` и `exscio-api.service`.
- **Arch Packaging**: Наличие полноценного `PKGBUILD` и `exscio.install` для локальной сборки через `makepkg` или публикации в AUR.
- **Безопасная изоляция venv**: Автоматическое связывание с системными библиотеками (`--system-site-packages`) для прозрачной работы системных C-биндингов `PyGObject` и `WebKit2GTK`.

---

## 📦 Системные требования и зависимости

### Минимальные требования:
- **ОС**: Arch Linux (x86_64, ядро Linux 6.x+)
- **ОЗУ**: 16 ГБ RAM (для работы моделей на CPU)
- **Диск**: 10 ГБ свободного пространства (включая модели и векторный индекс)
- **Дисплей**: X11 или Wayland (для десктопного окна)

### Рекомендуемые требования:
- **ОЗУ**: 32 ГБ RAM
- **GPU**: NVIDIA RTX (8+ ГБ VRAM) с драйвером `nvidia` или AMD Radeon (ROCm)
- **LLM**: Qwen 2.5 14B Instruct
- **Embeddings**: Nomic Embed Text v1.5

### Пакеты Arch Linux (`pacman`):
- `python>=3.10`
- `python-pip`, `python-virtualenv`
- `base-devel`
- `webkit2gtk-4.1`
- `gtk3`
- `python-gobject`
- `openssl`
- `lsof`
- `xdg-utils`


---

## ⚡ Быстрый запуск (Автоматическая установка)

В каталог `EXSCIO_arch` включен автоматический установщик, настраивающий систему «из коробки»:

```bash
cd /path/to/EXSCIO_arch
chmod +x install_arch.sh
./install_arch.sh
```

**Что выполняет скрипт `install_arch.sh`:**
1. Проверяет дистрибутив Arch Linux.
2. Устанавливает недостающие пакеты через `sudo pacman -S --needed`.
3. Создает виртуальное окружение `venv` с доступом к GTK/GObject.
4. Устанавливает зависимости из `requirements.txt`.
5. Назначает права на исполнение (`chmod +x *.sh`).
6. Создает и регистрирует Desktop Entry (`~/.local/share/applications/exscio.desktop`) и иконку.
7. Регистрирует службы systemd в `~/.config/systemd/user/`.
8. Запускает тест бэкендов `test_backends.py`.

После завершения просто запустите:
```bash
./start.sh
```

---

## 🛠 Ручная установка

Если вы предпочитаете настраивать систему вручную:

### Шаг 1. Установка пакетов Arch
```bash
sudo pacman -S --needed \
    python python-pip python-virtualenv base-devel \
    webkit2gtk-4.1 gtk3 python-gobject openssl lsof
```

### Шаг 2. Развертывание виртуального окружения
```bash
cd EXSCIO_arch
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
chmod +x *.sh
```

### Шаг 3. Запуск
```bash
./start.sh
```

---

## 📦 Сборка пакета через PKGBUILD

Для создания системного пакета Arch Linux (`.pkg.tar.zst`):

```bash
cd EXSCIO_arch
makepkg -si
```

После установки пакет регистрирует глобальные команды:
- `exscio` — запуск десктопного RAG-приложения
- `exscio-api` — запуск FastAPI сервера (порт 8000)
- `exscio-switch` — интерактивный переключатель бэкендов

---

## 🤖 Управление ИИ-бэкендами на Arch Linux

EXSCIO поддерживает гибкое переключение между тремя бэкендами без изменения кода.

### 1. Ollama Native (Наиболее нативный способ для Arch Linux)

В репозитории Arch Linux пакет `ollama` доступен официально:
```bash
# Установка Ollama
sudo pacman -S ollama

# Для ускорения NVIDIA CUDA:
sudo pacman -S cuda

# Включение и запуск системного демона:
sudo systemctl enable --now ollama

# Загрузка рекомендованных моделей:
ollama pull qwen2.5:14b
ollama pull nomic-embed-text
```

Переключение EXSCIO на Ollama:
```bash
./switch_backend.sh ollama
./start.sh
```

### 2. LM Studio

LM Studio доступен в Arch User Repository (AUR) или как официальный AppImage:
```bash
# Установка через AUR-хелпер (например, yay):
yay -S lm-studio-bin

# Запуск CLI LM Studio:
lms server start
lms load qwen2.5-14b-instruct-1m -c 8192 --gpu max -y
lms load text-embedding-nomic-embed-text-v1.5 --gpu off -y
```

Переключение EXSCIO на LM Studio:
```bash
./switch_backend.sh lmstudio
./start.sh
```

### 3. Docker Compose

Запуск локального стека (Ollama + Open WebUI):
```bash
# Установка Docker на Arch:
sudo pacman -S docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker $USER

# Запуск контейнеров:
./start_docker.sh
```

---

## 🖥 Десктопный интерфейс и WebKit2GTK

Приложение запускается в нативном графическом окне с использованием движка **WebKit2GTK**:
- Поддерживает Wayland и X11.
- Обеспечивает аппаратное ускорение рендеринга.
- Автоматически выгружает модели из памяти GPU при закрытии окна крестиком.

### Режимы запуска и ключи командной строки:
- `./start.sh` — стандартный запуск в нативном окне WebKit2GTK (или автоматический fallback в браузер).
- `./start.sh --headless` — запуск без графического интерфейса и без открытия веб-браузера (для удаленных серверов, контейнеров и systemd служб).
- `./start.sh --browser` — принудительный запуск в системном браузере в обход pywebview.

### Интеллектуальный Fallback:
Если приложение запускается:
- По SSH без проброса X11 (`$DISPLAY` отсутствует)
- В терминале без графического сервера
- На машине без установленного пакета `webkit2gtk-4.1`

EXSCIO автоматически определит отсутствие дисплея, выведет понятное уведомление в консоль и безопасно перейдет в headless-режим с подсказкой веб-адреса (`http://localhost:8501`), исключая сбои `xdg-open`.

---

## ⚙️ Управление службами Systemd

Для работы EXSCIO в качестве фонового сервиса или демона предусмотрены юниты Systemd:

### Запуск API-сервера в фоне:
```bash
# Копирование юнита в пользовательскую директорию (если не использовался install_arch.sh):
mkdir -p ~/.config/systemd/user/
cp exscio-api.service ~/.config/systemd/user/
systemctl --user daemon-reload

# Запуск службы:
systemctl --user start exscio-api.service

# Проверка статуса:
systemctl --user status exscio-api.service

# Включение автозапуска при входе в систему:
systemctl --user enable exscio-api.service

# Просмотр логов в реальном времени:
journalctl --user -u exscio-api.service -f
```

---

## 📂 Справочник скриптов запуска

| Скрипт | Назначение |
| :--- | :--- |
| `start.sh` | Главный скрипт: запуск десктопного RAG-приложения (с авто-фоллбэком в браузер). |
| `start_rag.sh` | Прямой запуск RAG-интерфейса. |
| `start_api.sh` | Запуск production FastAPI сервера на порту 8000. |
| `start_ollama.sh` | Автоматический выбор бэкенда Ollama и запуск комплекса. |
| `start_lmstudio.sh` | Автоматический выбор бэкенда LM Studio и запуск комплекса. |
| `start_docker.sh` | Поднятие контейнеров Ollama + Open WebUI через Docker Compose. |
| `stop_docker.sh` | Остановка и очистка контейнеров Docker Compose. |
| `start_telegram_bot.sh` | Запуск клиентского Telegram-бота для доступа к RAG из мессенджера. |
| `switch_backend.sh` | Утилита быстрого переключения профилей `.env` (lmstudio / ollama / docker). |
| `install_arch.sh` | Автоматический мастер установки для Arch Linux. |

---

## 🔍 Диагностика и устранение неполадок

### 1. Проверка доступности бэкендов и GPU:
Запустите диагностическую утилиту:
```bash
./venv/bin/python test_backends.py
```
Она покажет статус GPU (NVIDIA/AMD/CPU), свободную видеопамять, статус LM Studio, Ollama и Docker.

### 2. Ошибка `Could not open display` или проблемы с WebKit2GTK:
Убедитесь, что установлены пакеты:
```bash
sudo pacman -S webkit2gtk-4.1 gtk3 python-gobject
```
Если вы работаете в Wayland, при необходимости можно принудительно задать X11 backend:
```bash
GDK_BACKEND=x11 ./start.sh
```

### 3. Освобождение занятого порта 8501 или 8000:
Скрипт `run_app.py` автоматически завершает зависшие процессы через `lsof`/`fuser`. Вручную:
```bash
fuser -k 8501/tcp
fuser -k 8000/tcp
```

### 4. Нехватка видеопамяти (CUDA Out of Memory):
Для моделей 14B на GPU с 8 ГБ VRAM используйте квантование Q4_K_M и ограничение контекста 8192 токенов. Конфигурация по умолчанию в `server_manager.py` уже оптимизирована с параметром `-c 8192`.

---

© 2026 EXSCIO Core Team. Лицензировано для автономных корпоративных развертываний.
