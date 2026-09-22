"""
server_manager.py — Модуль автономного управления локальным бэкендом LM Studio.
Обеспечивает обнаружение CLI, запуск сервера на порту 1234,
загрузку моделей эмбеддингов и LLM с защитой контекста (-c 8192) и остановку.
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import httpx

logger = logging.getLogger("server_manager")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

DEFAULT_PORT = 1234
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_PORT}/v1"
DEFAULT_LLM = "qwen2.5-14b-instruct-1m"
DEFAULT_EMBED = "text-embedding-nomic-embed-text-v1.5"
DEFAULT_CONTEXT = 8192

__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_BASE_URL",
    "DEFAULT_LLM",
    "DEFAULT_EMBED",
    "DEFAULT_CONTEXT",
    "get_lms_cli_path",
    "is_server_online",
    "get_loaded_models",
    "start_local_server",
    "load_model_via_cli",
    "ensure_autonomous_stack",
    "unload_all_models",
    "stop_local_server",
    "get_ollama_cli_path",
    "is_ollama_online",
    "get_ollama_loaded_models",
    "start_ollama_server",
    "ensure_ollama_stack",
    "get_docker_cli_path",
    "start_docker_compose",
    "stop_docker_compose",
]


def get_lms_cli_path() -> Optional[str]:
    """Находит исполняемый файл lms.exe на локальной машине."""
    # 1. Проверка PATH
    found = shutil.which("lms")
    if found:
        return found
    found_exe = shutil.which("lms.exe")
    if found_exe:
        return found_exe

    # 2. Стандартные пути установки LM Studio CLI
    candidates = [
        Path(os.path.expanduser("~")) / ".lmstudio" / "bin" / "lms.exe",
        Path("C:/Program Files/LM Studio/resources/app/.webpack/main/index.js"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def is_server_online(base_url: str = DEFAULT_BASE_URL, timeout: float = 1.5) -> bool:
    """Проверяет доступность HTTP-сервера LM Studio."""
    # Убираем /v1 если передано для проверки базового пути или /v1/models
    norm_url = base_url.rstrip("/")
    if not norm_url.endswith("/v1"):
        models_url = f"{norm_url}/v1/models"
    else:
        models_url = f"{norm_url}/models"

    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.get(models_url)
            return resp.status_code == 200
    except Exception:
        return False


def get_loaded_models(base_url: str = DEFAULT_BASE_URL, timeout: float = 2.0) -> List[str]:
    """
    Возвращает список идентификаторов моделей, реально загруженных в память (GPU/RAM).
    Использует CLI `lms ps --json`, либо API эндпоинт `/api/v0/models` с проверкой state == 'loaded'.
    """
    # 1. Опрос через lms CLI (наиболее точный и быстрый способ для локального LM Studio)
    cli_path = get_lms_cli_path()
    if cli_path:
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.run(
                [cli_path, "ps", "--json"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags
            )
            if proc.returncode == 0 and proc.stdout.strip():
                import json
                items = json.loads(proc.stdout)
                loaded_ids = []
                for item in items:
                    ident = item.get("identifier") or item.get("modelKey")
                    if ident:
                        loaded_ids.append(ident)
                    mkey = item.get("modelKey")
                    if mkey and mkey not in loaded_ids:
                        loaded_ids.append(mkey)
                return loaded_ids
        except Exception as e:
            logger.debug("Сбой опроса lms ps --json: %s", e)

    # 2. Опрос через расширенный HTTP API v0 (/api/v0/models)
    norm_url = base_url.rstrip("/")
    if norm_url.endswith("/v1"):
        root_url = norm_url[:-3].rstrip("/")
    else:
        root_url = norm_url

    v0_url = f"{root_url}/api/v0/models"
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.get(v0_url)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                loaded_ids = []
                for m in data:
                    if m.get("state") == "loaded":
                        mid = m.get("id")
                        if mid:
                            loaded_ids.append(mid)
                return loaded_ids
    except Exception:
        pass

    # 3. Если ни CLI, ни v0 API недоступны — возвращаем пустой список (модели не загружены)
    return []


def start_local_server(port: int = DEFAULT_PORT, timeout_sec: int = 15) -> Tuple[bool, str]:
    """
    Запускает локальный HTTP-сервер LM Studio через CLI.
    Возвращает (True, "OK") если сервер активен.
    """
    if is_server_online(f"http://127.0.0.1:{port}/v1"):
        return True, "Сервер уже запущен и готов к работе."

    cli_path = get_lms_cli_path()
    if not cli_path:
        return False, "LM Studio CLI (lms.exe) не найден на данном компьютере."

    try:
        logger.info("Запуск сервера LM Studio на порту %d...", port)
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        cmd = [cli_path, "server", "start", "-p", str(port)]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=creationflags
        )
        logger.info("Команда запуска завершена. Код: %d, Вывод: %s", proc.returncode, proc.stdout.strip() or proc.stderr.strip())

        # Ожидание готовности
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if is_server_online(f"http://127.0.0.1:{port}/v1", timeout=1.0):
                return True, f"Сервер успешно запущен на порту {port}."
            time.sleep(1.0)

        return False, f"Таймаут ожидания запуска сервера LM Studio ({timeout_sec} сек)."
    except Exception as e:
        logger.exception("Ошибка при запуске сервера LM Studio")
        return False, f"Исключение при запуске сервера: {e}"


def load_model_via_cli(
    model_key: str,
    is_llm: bool = False,
    context_length: int = DEFAULT_CONTEXT,
    timeout_sec: int = 90
) -> Tuple[bool, str]:
    """
    Загружает указанную модель в память LM Studio с корректными параметрами.
    Для LLM критически важно указывать -c 8192 --gpu max -y во избежание сбоя памяти (131 GB VRAM).
    """
    cli_path = get_lms_cli_path()
    if not cli_path:
        return False, "LM Studio CLI не найден."

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if is_llm:
            cmd = [
                cli_path, "load", model_key,
                "-c", str(context_length),
                "--gpu", "max",
                "-y"
            ]
        else:
            # Для модели эмбеддингов отключаем GPU, чтобы она запускалась на процессоре (RAM)
            cmd = [
                cli_path, "load", model_key,
                "--gpu", "off",
                "-y"
            ]

        logger.info("Выполнение команды загрузки модели: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            creationflags=creationflags
        )

        output = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode == 0:
            logger.info("Модель %s успешно загружена.", model_key)
            return True, f"Модель {model_key} успешно загружена в память."
        else:
            logger.error("Сбой загрузки %s: %s", model_key, output)
            return False, f"Ошибка загрузки {model_key}: {output}"

    except subprocess.TimeoutExpired:
        return False, f"Таймаут при загрузке модели {model_key} ({timeout_sec} сек)."
    except Exception as e:
        return False, f"Исключение при загрузке модели {model_key}: {e}"


def ensure_autonomous_stack(
    llm_model: str = DEFAULT_LLM,
    embed_model: str = DEFAULT_EMBED,
    context_length: int = DEFAULT_CONTEXT,
    progress_callback = None
) -> Tuple[bool, str]:
    """
    Комплексная автономная процедура «в один клик»:
    1. Проверяет/запускает сервер.
    2. Проверяет наличие моделей эмбеддингов и LLM в памяти.
    3. Загружает недостающие модели с правильными параметрами GPU.
    """
    def report(msg: str):
        logger.info(msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    report("Проверка доступности локального сервера...")
    if not is_server_online():
        report("Локальный сервер выключен. Запуск сервера LM Studio...")
        ok, msg = start_local_server()
        if not ok:
            return False, f"Не удалось поднять сервер: {msg}"
        report("Сервер LM Studio успешно поднят и принимает соединения.")

    loaded = get_loaded_models()
    report(f"Активные модели в памяти: {', '.join(loaded) if loaded else 'нет загруженных моделей'}")

    # Загрузка модели эмбеддингов
    if embed_model not in loaded:
        report(f"Загрузка эмбеддинг-модели '{embed_model}' на процессоре (GPU off)...")
        ok, msg = load_model_via_cli(embed_model, is_llm=False)
        if not ok:
            return False, f"Не удалось загрузить эмбеддинги: {msg}"
        report(f"Эмбеддинг-модель '{embed_model}' готова на процессоре (RAM).")

    # Загрузка LLM
    if llm_model not in loaded:
        report(f"Загрузка генеративной модели '{llm_model}' (GPU max, контекст {context_length})...")
        ok, msg = load_model_via_cli(llm_model, is_llm=True, context_length=context_length)
        if not ok:
            return False, f"Не удалось загрузить LLM: {msg}"
        report(f"LLM '{llm_model}' успешно загружена в память GPU.")

    report("✅ Локальный автономный стек RAG полностью готов к работе!")
    return True, "Автономный стек готов"


def unload_all_models() -> Tuple[bool, str]:
    """Выгружает все загруженные модели из памяти GPU через lms unload --all."""
    cli_path = get_lms_cli_path()
    if not cli_path:
        return False, "LM Studio CLI не найден."

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.run(
            [cli_path, "unload", "--all"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags
        )
        logger.info("Выгрузка моделей: %s", (proc.stdout + "\n" + proc.stderr).strip())
        return True, "Все модели выгружены из памяти GPU."
    except Exception as e:
        logger.error("Ошибка при выгрузке моделей: %s", e)
        return False, f"Ошибка при выгрузке моделей: {e}"


def stop_local_server() -> Tuple[bool, str]:
    """Выгружает модели и останавливает локальный сервер LM Studio для полного освобождения ресурсов GPU."""
    cli_path = get_lms_cli_path()
    if not cli_path:
        return False, "LM Studio CLI не найден."

    try:
        unload_all_models()
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.run(
            [cli_path, "server", "stop"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags
        )
        return True, "Локальный сервер LM Studio остановлен, память GPU освобождена."
    except Exception as e:
        return False, f"Ошибка при остановке сервера: {e}"


def get_ollama_cli_path() -> Optional[str]:
    """Находит исполняемый файл ollama.exe на локальной машине."""
    found = shutil.which("ollama") or shutil.which("ollama.exe")
    if found:
        return found
    candidates = [
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")),
        Path(r"C:\Program Files\Ollama\ollama.exe"),
        Path(r"C:\Program Files\Ollama\ollama app.exe")
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def is_ollama_online(url: str = "http://127.0.0.1:11434/v1", timeout: float = 3.5) -> bool:
    """Проверяет доступность эндпоинта Ollama с надежным таймаутом."""
    norm_url = url.rstrip("/")
    # Проверяем как OpenAI-совместимый эндпоинт, так и нативный Ollama /api/tags
    check_urls = [
        f"{norm_url}/models" if norm_url.endswith("/v1") else f"{norm_url}/v1/models",
        "http://127.0.0.1:11434/api/tags"
    ]
    for target in check_urls:
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                resp = client.get(target)
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
    return False


def get_ollama_loaded_models(base_url: str = "http://127.0.0.1:11434/v1") -> List[str]:
    """Возвращает список доступных моделей в локальном хранилище Ollama."""
    norm_url = base_url.rstrip("/")
    target = f"{norm_url}/models" if norm_url.endswith("/v1") else f"{norm_url}/v1/models"
    try:
        with httpx.Client(timeout=4.0, trust_env=False) as client:
            resp = client.get(target)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return [m["id"] for m in data if "id" in m]
    except Exception:
        pass

    # Нативный fallback на /api/tags
    try:
        with httpx.Client(timeout=4.0, trust_env=False) as client:
            resp = client.get("http://127.0.0.1:11434/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return [m["name"] for m in models if "name" in m]
    except Exception:
        pass
    return []


def start_ollama_server() -> Tuple[bool, str]:
    """Запускает локальную службу Ollama."""
    if is_ollama_online():
        return True, "Служба Ollama уже активна и принимает запросы."

    ollama_bin = get_ollama_cli_path()
    if not ollama_bin:
        return False, "Утилита ollama не найдена. Убедитесь, что Ollama установлена на ПК."

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen([ollama_bin, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
        
        deadline = time.time() + 10.0
        while time.time() < deadline:
            time.sleep(1.0)
            if is_ollama_online():
                return True, "Служба Ollama успешно запущена и готова к работе."
        return True, "Команда запуска Ollama отправлена в фоновом режиме."
    except Exception as e:
        return False, f"Ошибка запуска Ollama: {e}"


def ensure_ollama_stack(
    llm_model: str = "qwen2.5:14b",
    embed_model: str = "nomic-embed-text:latest",
    progress_callback = None
) -> Tuple[bool, str]:
    """
    Комплексная процедура подготовки Ollama стека:
    1. Проверка доступности службы, автозапуск при необходимости.
    2. Валидация доступности моделей генерации и эмбеддингов.
    3. Pre-flight прогрев моделей.
    """
    def report(msg: str):
        logger.info(msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    report("Проверка доступности службы Ollama (порт 11434)...")
    if not is_ollama_online():
        report("Служба Ollama остановлена. Запуск службы...")
        ok, msg = start_ollama_server()
        if not ok and not is_ollama_online():
            return False, f"Не удалось запустить Ollama: {msg}"
        time.sleep(1.5)

    if not is_ollama_online():
        return False, "Таймаут ожидания ответа Ollama на порту 11434."

    report("Служба Ollama активна. Проверка наличия моделей в хранилище...")
    available_models = get_ollama_loaded_models()
    report(f"Доступные модели Ollama: {', '.join(available_models) if available_models else 'список пуст'}")

    # Проверка модели эмбеддингов
    emb_found = any(embed_model in m or "nomic" in m.lower() for m in available_models)
    if not emb_found:
        report(f"Модель эмбеддингов '{embed_model}' не найдена. Попытка загрузки...")
        cli = get_ollama_cli_path()
        if cli:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                subprocess.run([cli, "pull", "nomic-embed-text"], timeout=120, creationflags=creationflags)
                report("Модель nomic-embed-text успешно загружена в Ollama.")
            except Exception as e:
                report(f"Предупреждение при pull эмбеддингов: {e}")

    # Проверка генеративной модели
    llm_found = any(llm_model in m or "qwen" in m.lower() for m in available_models)
    if not llm_found:
        report(f"Модель генерации '{llm_model}' не найдена в Ollama.")
        return False, f"Модель {llm_model} отсутствует в Ollama. Выполните: ollama create {llm_model} -f Modelfile.qwen14b"

    report("✅ Локальный автономный стек Ollama полностью готов к работе!")
    return True, "Ollama готова к работе"


def get_docker_cli_path() -> Optional[str]:
    """Находит исполняемый файл docker.exe в системе."""
    candidates = [
        "docker",
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe")
    ]
    for c in candidates:
        found = shutil.which(c) or (c if Path(c).exists() else None)
        if found:
            return str(found)
    return None


def start_docker_compose() -> Tuple[bool, str]:
    """Запускает контейнеры через docker compose up -d."""
    docker_bin = get_docker_cli_path()
    if not docker_bin:
        return False, "Docker CLI не найден. Убедитесь, что Docker Desktop установлен."

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.run(
            [docker_bin, "compose", "up", "-d"],
            capture_output=True,
            text=True,
            timeout=40,
            creationflags=creationflags
        )
        if proc.returncode == 0:
            return True, "Docker-контейнеры успешно запущены в фоне."
        err = (proc.stderr or proc.stdout).strip()
        return False, f"Ошибка запуска Docker Compose: {err}"
    except Exception as e:
        return False, f"Сбой вызова docker compose: {e}"


def stop_docker_compose() -> Tuple[bool, str]:
    """Останавливает контейнеры через docker compose down."""
    docker_bin = get_docker_cli_path()
    if not docker_bin:
        return False, "Docker CLI не найден."

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.run(
            [docker_bin, "compose", "down"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=creationflags
        )
        return True, "Docker-контейнеры остановлены."
    except Exception as e:
        return False, f"Сбой вызова docker compose down: {e}"



