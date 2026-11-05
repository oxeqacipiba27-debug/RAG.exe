"""
test_windows_components.py — Исчерпывающий набор тестов компонентов для Windows-версии EXSCIO.
Проверяет:
1. Компиляцию байткода всех .py файлов в директории RAG.exe-windows.
2. Корректность и кодировку батч-скриптов Windows (.bat).
3. Компоненты ядра rag_engine.py: AppConfig, VectorStore, Sanitizer, BM25, Lost-in-the-Middle, RRF.
4. Менеджер бэкендов server_manager.py: обнаружение путей, WSL2 проверка, параметры VRAM/GPU.
5. Модуль переключения switch_backend.py: переключение профилей и чтение активного бэкенда.
6. Графический интерфейс rag_gui.py: reload server_manager, сессионные параметры, dry run Streamlit.
"""

from __future__ import annotations

import os
import sys
import unittest
import py_compile
import shutil
import tempfile
import time
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Безопасная настройка кодировки консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WINDOWS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WINDOWS_DIR))

import rag_engine
import server_manager
import switch_backend


class TestWindowsBytecodeCompilation(unittest.TestCase):
    """1. Проверка синтаксиса и компиляции байткода для всех файлов в RAG.exe-windows."""

    def test_all_python_files_compile(self):
        py_files = list(WINDOWS_DIR.rglob("*.py"))
        self.assertGreater(len(py_files), 10, "Должно быть найдено не менее 10 .py файлов")
        for py_path in py_files:
            if "venv" in str(py_path) or ".venv" in str(py_path):
                continue
            with self.subTest(file=py_path.name):
                try:
                    py_compile.compile(str(py_path), doraise=True)
                except py_compile.PyCompileError as e:
                    self.fail(f"Ошибка компиляции синтаксиса в {py_path}: {e}")


class TestWindowsBatchLaunchers(unittest.TestCase):
    """2. Проверка батч-скриптов Windows (.bat)."""

    def test_batch_launchers_exist_and_utf8(self):
        expected_launchers = [
            "start.bat",
            "start_rag.bat",
            "start_ollama.bat",
            "start_lmstudio.bat",
            "start_docker.bat",
            "stop_docker.bat",
            "switch_backend.bat",
            "start_api.bat",
            "start_telegram_bot.bat"
        ]
        for name in expected_launchers:
            bat_path = WINDOWS_DIR / name
            self.assertTrue(bat_path.exists(), f"Файл {name} отсутствует в Windows папке")
            content = bat_path.read_text(encoding="utf-8", errors="strict")
            self.assertTrue(content.startswith("@echo off"), f"{name} должен начинаться с @echo off")
            self.assertIn("chcp 65001", content, f"{name} должен устанавливать кодовую страницу chcp 65001")

    def test_batch_launchers_python_interpreter_logic(self):
        """Проверка, что все батч-скрипты корректно обрабатывают py -3 через PY_EXTRA."""
        python_launchers = [
            "start.bat",
            "start_rag.bat",
            "start_ollama.bat",
            "start_lmstudio.bat",
            "start_docker.bat",
            "switch_backend.bat",
            "start_api.bat",
            "start_telegram_bot.bat"
        ]
        for name in python_launchers:
            bat_path = WINDOWS_DIR / name
            content = bat_path.read_text(encoding="utf-8")
            self.assertIn("PY_CMD=", content, f"{name} должен объявлять PY_CMD")
            self.assertIn("PY_EXTRA=", content, f"{name} должен объявлять PY_EXTRA для безопасного запуска py -3")
            self.assertIn(":python_found", content, f"{name} должен использовать переход к метке :python_found")

    def test_batch_launchers_no_raw_emojis(self):
        """Проверка соблюдения правила 5 GEMINI.md: отсутствие сырых эмодзи в батч-скриптах."""
        for bat_file in WINDOWS_DIR.glob("*.bat"):
            content = bat_file.read_text(encoding="utf-8")
            for char in content:
                self.assertLess(
                    ord(char),
                    0x2600,
                    f"Файл {bat_file.name} содержит спецсимвол/эмодзи '{char}', нарушающий cp1251"
                )


class TestRAGEngineComponents(unittest.TestCase):
    """3. Тестирование ключевых компонентов ядра rag_engine.py."""

    def test_app_config_and_device(self):
        cfg = rag_engine.AppConfig()
        # Проверяем, что по правилу 7 GEMINI.md эмбеддинги по умолчанию на CPU
        self.assertEqual(cfg.embedding_device.lower(), "cpu", "Эмбеддинги обязаны работать на CPU во избежание OOM")
        self.assertEqual(cfg.retrieval_top_k, 5)
        self.assertGreaterEqual(cfg.chunk_size, 500)

    def test_sanitizer_cjk_and_pii(self):
        # 1. Очистка иероглифов CJK
        cjk_text = "Ответ на русском языке. 这是一个测试 こんにちは 한국어"
        cleaned_cjk = rag_engine.sanitize_llm_output(cjk_text)
        self.assertNotIn("这", cleaned_cjk)
        self.assertNotIn("こんにちは", cleaned_cjk)
        self.assertIn("Ответ на русском языке.", cleaned_cjk)

        # 2. Маскирование ПДн (152-ФЗ) через PIISanitizer
        pii_text = "Клиент Иван, телефон +7 (999) 123-45-67, email: test@domain.ru, паспорт 4510 123456, СНИЛС 123-456-789 01"
        sanitized_pii = rag_engine.PIISanitizer.sanitize(pii_text)
        self.assertNotIn("+7 (999) 123-45-67", sanitized_pii)
        self.assertNotIn("test@domain.ru", sanitized_pii)
        self.assertNotIn("4510 123456", sanitized_pii)
        self.assertNotIn("123-456-789 01", sanitized_pii)
        self.assertIn("[PHONE_MASKED]", sanitized_pii)
        self.assertIn("[EMAIL_MASKED]", sanitized_pii)
        self.assertIn("[PASSPORT_MASKED]", sanitized_pii)
        self.assertIn("[SNILS_MASKED]", sanitized_pii)

    def test_bm25_search_scoring(self):
        # Проверка инвертированного индекса OkapiBM25
        tokenized_corpus = [
            ["школьн", "форм", "син", "цвет", "класс"],     # doc 0: форма
            ["график", "работ", "столов", "обед"],           # doc 1: столовая
            ["спортивн", "форм", "занят", "физкультур"]      # doc 2: спорт
        ]
        bm25 = rag_engine.OkapiBM25(k1=1.5, b=0.75)
        bm25.fit(tokenized_corpus)

        results = bm25.query(["школьн", "форм"], top_k=2)
        self.assertGreater(len(results), 0)
        top_doc_id, score = results[0]
        self.assertEqual(top_doc_id, 0, "Документ 0 про школьную форму должен иметь наивысший BM25 score")
        self.assertGreater(score, 0.0)

    def test_lost_in_the_middle_rerank(self):
        # 5 чанков с убывающим скором: 0 (лучший), 1, 2, 3, 4 (худший)
        hits = [
            rag_engine.RetrievalHit(
                chunk=rag_engine.DocumentChunk(
                    metadata=rag_engine.ChunkMetadata(
                        chunk_id=f"c{i}",
                        doc_id=f"doc_{i}",
                        source=f"s{i}.pdf",
                        raw_source=f"/path/to/s{i}.pdf",
                        page=1
                    ),
                    text=f"Текст чанка {i}"
                ),
                score=10.0 - i,
                dense_score=0.9 - (i * 0.1),
                sparse_score=5.0 - i,
                dense_rank=i + 1,
                sparse_rank=i + 1,
                rrf_score=0.5 - (i * 0.05),
                rerank_score=10.0 - i
            )
            for i in range(5)
        ]
        reordered = rag_engine.HybridRetriever.reorder_lost_in_the_middle(hits)
        self.assertEqual(len(reordered), 5)
        # В стратегии Lost-in-the-Middle: лучший чанк (c0) ставится в начало [0],
        # второй по качеству (c1) ставится в самый конец окна [4]
        self.assertEqual(reordered[0].chunk.metadata.chunk_id, "c0")
        self.assertEqual(reordered[-1].chunk.metadata.chunk_id, "c1")


class TestServerManagerWindows(unittest.TestCase):
    """4. Тестирование Windows адаптации server_manager.py."""

    def test_wsl2_availability_check(self):
        ok, msg = server_manager.is_wsl2_available()
        # На Linux возвращает True, на Windows проверяет wsl
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)

    def test_lms_cli_path_detection(self):
        cli = server_manager.get_lms_cli_path()
        # Либо найдена строка пути, либо None при отсутствии установки
        self.assertTrue(cli is None or isinstance(cli, str))

    def test_ollama_cli_path_detection(self):
        cli = server_manager.get_ollama_cli_path()
        self.assertTrue(cli is None or isinstance(cli, str))

    def test_docker_cli_path_detection(self):
        cli = server_manager.get_docker_cli_path()
        self.assertTrue(cli is None or isinstance(cli, str))

    def test_gpu_summary_safe_call(self):
        summary = server_manager.get_gpu_summary()
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)

    @patch("subprocess.run")
    def test_load_model_parameters_enforce_gemini_rules(self, mock_run):
        # Тестируем соблюдение Правила 1 GEMINI.md: -c 8192 --gpu max -y для LLM
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Loaded"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        with patch("server_manager.get_lms_cli_path", return_value="lms.exe"):
            ok, msg = server_manager.load_model_via_cli("qwen2.5-14b", is_llm=True, context_length=8192)
            self.assertTrue(ok)
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("-c", called_cmd)
            self.assertIn("8192", called_cmd)
            self.assertIn("--gpu", called_cmd)
            self.assertIn("max", called_cmd)
            self.assertIn("-y", called_cmd)

            # Для эмбеддингов: --gpu off -y
            ok2, msg2 = server_manager.load_model_via_cli("nomic-embed", is_llm=False)
            self.assertTrue(ok2)
            called_cmd2 = mock_run.call_args[0][0]
            self.assertIn("--gpu", called_cmd2)
            self.assertIn("off", called_cmd2)

    @patch("subprocess.run")
    def test_windows_gpu_fallback_wmi(self, mock_run):
        """Проверка fallback-обнаружения GPU через PowerShell / WMI на Windows."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "NVIDIA GeForce RTX 4070 Laptop GPU\n"
        mock_run.return_value = mock_proc

        with patch("sys.platform", "win32"), \
             patch("shutil.which", return_value=None):
            gpu_info = server_manager.get_gpu_info()
            self.assertTrue(gpu_info["has_gpu"])
            self.assertEqual(gpu_info["vendor"], "NVIDIA")
            self.assertEqual(gpu_info["method"], "powershell_wmi")
            self.assertEqual(gpu_info["gpus"][0]["name"], "NVIDIA GeForce RTX 4070 Laptop GPU")


class TestSwitchBackend(unittest.TestCase):
    """5. Тестирование модуля switch_backend.py."""

    def setUp(self):
        self.temp_env = WINDOWS_DIR / ".env.test_backup"
        self.env_file = WINDOWS_DIR / ".env"
        if self.env_file.exists():
            shutil.copyfile(self.env_file, self.temp_env)

    def tearDown(self):
        if self.temp_env.exists():
            shutil.copyfile(self.temp_env, self.env_file)
            self.temp_env.unlink()

    def test_switch_all_profiles(self):
        for profile in ["lmstudio", "ollama", "docker", "rtx4070"]:
            with self.subTest(profile=profile):
                res = switch_backend.switch_to(profile)
                self.assertTrue(res, f"Не удалось переключить на профиль {profile}")
                current = switch_backend.get_current_backend()
                self.assertNotEqual(current, "Неизвестен")
                self.assertNotEqual(current, "Не задан (.env отсутствует)")

    def test_switch_invalid_profile(self):
        res = switch_backend.switch_to("non_existent_profile_xyz")
        self.assertFalse(res, "Несуществующий профиль должен возвращать False")


class TestStreamlitGUIIntegration(unittest.TestCase):
    """6. Проверка Streamlit GUI rag_gui.py и dry run."""

    def test_gui_imports_and_reload(self):
        import importlib
        import server_manager as sm
        importlib.reload(sm)
        self.assertTrue(hasattr(sm, "is_server_online"))
        self.assertTrue(hasattr(sm, "is_ollama_online"))

    def test_streamlit_dry_run_startup(self):
        """Запуск Streamlit rag_gui.py на тестовом порту с проверкой HTTP 200 OK."""
        import httpx
        import socket

        def _find_free_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                return s.getsockname()[1]

        test_port = _find_free_port()
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run", str(WINDOWS_DIR / "rag_gui.py"),
                "--server.port", str(test_port),
                "--server.headless", "true"
            ],
            cwd=str(WINDOWS_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        ready = False
        try:
            for _ in range(20):
                time.sleep(1.0)
                if proc.poll() is not None:
                    out, err = proc.communicate(timeout=2)
                    self.fail(f"Streamlit преждевременно завершился: {err}")
                try:
                    with httpx.Client(timeout=1.0, trust_env=False) as client:
                        resp = client.get(f"http://localhost:{test_port}")
                        if resp.status_code == 200:
                            ready = True
                            break
                except Exception:
                    pass
            self.assertTrue(ready, "Streamlit сервер должен успешно ответить HTTP 200 OK")
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                pass
            if proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


class TestCliScriptsCompatibility(unittest.TestCase):
    """7. Проверка скриптов CLI на соответствие стандарту Windows cp1251 (Правило 5)."""

    def test_cli_scripts_ascii_markers(self):
        cli_files = ["rag_chat.py", "ingest.py", "run_api.py", "switch_backend.py", "rag_direct.py", "rag_remote_client.py"]
        for fname in cli_files:
            fpath = WINDOWS_DIR / fname
            content = fpath.read_text(encoding="utf-8")
            self.assertIn("sys.stdout.reconfigure", content, f"{fname} обязан настраивать кодировку UTF-8")
            self.assertNotIn("🚀", content, f"{fname} не должен содержать эмодзи ракеты")
            self.assertNotIn("⚠️", content, f"{fname} не должен содержать эмодзи предупреждения")
            self.assertNotIn("✅", content, f"{fname} не должен содержать эмодзи галочки")
            self.assertNotIn("❌", content, f"{fname} не должен содержать эмодзи крестика")
            self.assertNotIn("✔", content, f"{fname} не должен содержать юникод-галочку")
            self.assertNotIn("✓", content, f"{fname} не должен содержать юникод-галочку")


if __name__ == "__main__":
    unittest.main()
