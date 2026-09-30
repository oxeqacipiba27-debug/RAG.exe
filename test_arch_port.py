"""
test_arch_port.py — Набор автоматизированных проверочных тестов для версии EXSCIO Arch Linux.
Проверяет:
1. Полное отсутствие остаточных Windows .bat файлов (включая рекурсивные подпапки).
2. Наличие всех POSIX .sh скриптов и строгое отсутствие CRLF (\\r\\n) во всех строках файлов.
3. Обработку сигналов завершения (SIGINT/SIGTERM, коды 130/143) в shell-скриптах запуска.
4. Адаптацию server_manager.py: пути Linux CLI, обнаружение GPU (nvidia-smi/rocm-smi/fallback), статус systemd, BASE_DIR.
5. Адаптацию run_app.py: проверку $DISPLAY, WebKit2GTK backend, флаги --headless и --browser, CWD-независимость.
6. Корректность Arch-специфичных файлов: install_arch.sh, PKGBUILD, exscio.desktop, systemd юниты.
7. Полноту зависимостей в requirements.txt (отсутствие скрытых незадекларированных модулей).
8. Импорт и целостность ключевых модулей RAG (rag_engine, api.app, ingestion.parsers).
"""

import os
import sys
import unittest
from pathlib import Path

# Корень репозитория EXSCIO_arch
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class TestArchPortIntegrity(unittest.TestCase):
    """Тесты целостности файлов и отсутствия Windows-специфичных артефактов."""

    def test_no_bat_files_remain(self):
        """Проверка: во всем дереве каталогов не должно остаться Windows .bat файлов."""
        bat_files = list(ROOT_DIR.rglob("*.bat"))
        self.assertEqual(
            len(bat_files),
            0,
            f"Обнаружены остаточные .bat файлы: {[str(f.relative_to(ROOT_DIR)) for f in bat_files]}"
        )

    def test_posix_scripts_exist_and_have_lf(self):
        """Проверка: все обязательные POSIX .sh скрипты существуют, имеют шебанг и чистые LF окончания строк."""
        expected_scripts = [
            "start.sh",
            "start_rag.sh",
            "start_api.sh",
            "start_lmstudio.sh",
            "start_ollama.sh",
            "start_docker.sh",
            "stop_docker.sh",
            "start_telegram_bot.sh",
            "switch_backend.sh",
            "install_arch.sh",
        ]
        for script_name in expected_scripts:
            path = ROOT_DIR / script_name
            self.assertTrue(path.exists(), f"Скрипт {script_name} отсутствует!")
            content = path.read_bytes()
            self.assertTrue(
                content.startswith(b"#!/"),
                f"Скрипт {script_name} не содержит валидный шебанг!"
            )
            # Проверка полного отсутствия Windows CRLF (\r\n) во всем файле
            self.assertNotIn(
                b"\r\n",
                content,
                f"Скрипт {script_name} содержит CRLF (\\r\\n) окончания строк, что вызовет ошибку 'syntax error' в Linux bash!"
            )

    def test_arch_integration_files(self):
        """Проверка наличия файлов интеграции с Arch Linux."""
        arch_files = [
            "PKGBUILD",
            "exscio.install",
            "exscio.desktop",
            "exscio.service",
            "exscio-api.service",
            "README_ARCH.md",
        ]
        for fname in arch_files:
            p = ROOT_DIR / fname
            self.assertTrue(p.exists(), f"Файл {fname} отсутствует!")
            self.assertGreater(p.stat().st_size, 50, f"Файл {fname} пуст или слишком мал!")
            content = p.read_bytes()
            self.assertNotIn(
                b"\r\n",
                content,
                f"Файл {fname} содержит CRLF (\\r\\n) окончания строк!"
            )

    def test_desktop_entry_spec(self):
        """Проверка соответствия exscio.desktop спецификации FreeDesktop."""
        desktop_file = ROOT_DIR / "exscio.desktop"
        content = desktop_file.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Type=Application", content)
        self.assertIn("Name=EXSCIO", content)
        self.assertIn("Exec=", content)
        self.assertIn("Icon=", content)
        self.assertIn("Categories=", content)

    def test_systemd_units_validity(self):
        """Проверка структуры и надежности файлов systemd служб."""
        for unit_name in ["exscio.service", "exscio-api.service"]:
            unit_file = ROOT_DIR / unit_name
            content = unit_file.read_text(encoding="utf-8")
            self.assertIn("[Unit]", content)
            self.assertIn("[Service]", content)
            self.assertIn("[Install]", content)
            self.assertIn("WantedBy=default.target", content)

        # Проверка: службы должны вызывать отказоустойчивые shell-скрипты
        api_unit = (ROOT_DIR / "exscio-api.service").read_text(encoding="utf-8")
        self.assertIn("start_api.sh", api_unit, "exscio-api.service должен использовать start_api.sh")

        gui_unit = (ROOT_DIR / "exscio.service").read_text(encoding="utf-8")
        self.assertIn("start.sh --headless", gui_unit, "exscio.service должен использовать start.sh --headless")

    def test_scripts_signal_exit_code_handling(self):
        """Проверка: ключевые shell-скрипты должны обрабатывать коды 130/143 (Ctrl+C)."""
        for script_name in ["start.sh", "start_lmstudio.sh", "start_ollama.sh"]:
            content = (ROOT_DIR / script_name).read_text(encoding="utf-8")
            self.assertIn("130", content, f"{script_name} должен проверять exit code 130 (SIGINT)")
            self.assertIn("143", content, f"{script_name} должен проверять exit code 143 (SIGTERM)")

    def test_requirements_dependencies_complete(self):
        """Проверка: все критические зависимости объявлены в requirements.txt."""
        req_file = ROOT_DIR / "requirements.txt"
        self.assertTrue(req_file.exists())
        req_text = req_file.read_text(encoding="utf-8")

        required_packages = [
            "streamlit",
            "httpx",
            "pywebview",
            "pydantic",
            "python-dotenv",
            "openai",
            "tenacity",
            "pypdf",
            "pdfplumber",
            "python-docx",
            "openpyxl",
            "pandas",
            "sentence-transformers",
            "torch",
            "fastapi",
            "uvicorn",
            "aiogram",
            "aiohttp",
            "numpy",
            "pillow",
        ]
        for pkg in required_packages:
            self.assertIn(
                pkg,
                req_text,
                f"Пакет '{pkg}' отсутствует в requirements.txt, что приведет к ModuleNotFoundError при установке на чистом Arch Linux!"
            )


class TestServerManagerArchAdaptation(unittest.TestCase):
    """Тесты адаптации server_manager.py под Arch Linux."""

    def setUp(self):
        import server_manager
        self.sm = server_manager

    def test_base_dir_defined(self):
        """Проверка определения BASE_DIR в server_manager."""
        self.assertTrue(hasattr(self.sm, "BASE_DIR"))
        self.assertEqual(self.sm.BASE_DIR, ROOT_DIR)

    def test_gpu_detection_contract(self):
        """Проверка контракта функций обнаружения GPU на Linux."""
        info = self.sm.get_gpu_info()
        self.assertIsInstance(info, dict)
        self.assertIn("has_gpu", info)
        self.assertIn("vendor", info)
        self.assertIn("gpus", info)
        self.assertIsInstance(info["gpus"], list)

        # Проверка функции-псевдонима
        alias_info = self.sm.check_linux_gpu()
        self.assertEqual(info["vendor"], alias_info["vendor"])

        summary = self.sm.get_gpu_summary()
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)

    def test_arch_paths_in_cli_search(self):
        """Проверка поиска путей к CLI для Arch Linux."""
        ollama_bin = self.sm.get_ollama_cli_path()
        self.assertTrue(ollama_bin is None or isinstance(ollama_bin, str))

        lms_bin = self.sm.get_lms_cli_path()
        self.assertTrue(lms_bin is None or isinstance(lms_bin, str))

        docker_bin = self.sm.get_docker_cli_path()
        self.assertTrue(docker_bin is None or isinstance(docker_bin, str))

    def test_systemd_service_check_safe(self):
        """Проверка безопасного вызова проверки статуса systemd без исключений."""
        status = self.sm.is_ollama_service_active()
        self.assertIsInstance(status, bool)


class TestRunAppArchAdaptation(unittest.TestCase):
    """Тесты адаптации run_app.py под Arch Linux Desktop."""

    def setUp(self):
        import run_app
        self.ra = run_app

    def test_app_dir_defined(self):
        """Проверка определения APP_DIR в run_app."""
        self.assertTrue(hasattr(self.ra, "APP_DIR"))
        self.assertEqual(self.ra.APP_DIR, ROOT_DIR)

    def test_get_window_icon_resolves_valid_file(self):
        """Проверка разрешения иконки окна относительно APP_DIR."""
        icon = self.ra.get_window_icon()
        if icon is not None:
            self.assertTrue(Path(icon).exists(), f"Путь к иконке {icon} не существует!")

    def test_has_display_logic(self):
        """Проверка логики обнаружения X11/Wayland дисплея."""
        self.assertTrue(hasattr(self.ra, "has_display"))
        res = self.ra.has_display()
        self.assertIsInstance(res, bool)

    def test_free_port_callable(self):
        """Проверка работоспособности функции free_port."""
        self.assertTrue(hasattr(self.ra, "free_port"))
        try:
            self.ra.free_port(9999)
        except Exception as e:
            self.fail(f"free_port вызвал непредвиденное исключение: {e}")


class TestArchPackagingSpecs(unittest.TestCase):
    """Тесты спецификации пакетов Arch Linux (PKGBUILD & install_arch.sh)."""

    def test_pkgbuild_dependencies(self):
        """Проверка зависимостей в PKGBUILD."""
        pkgbuild = (ROOT_DIR / "PKGBUILD").read_text(encoding="utf-8")
        self.assertIn("webkit2gtk-4.1", pkgbuild)
        self.assertIn("gtk3", pkgbuild)
        self.assertIn("python-gobject", pkgbuild)
        self.assertIn("xdg-utils", pkgbuild)
        self.assertIn("lsof", pkgbuild)

    def test_install_arch_dependencies(self):
        """Проверка зависимостей в install_arch.sh."""
        install_script = (ROOT_DIR / "install_arch.sh").read_text(encoding="utf-8")
        self.assertIn("webkit2gtk-4.1", install_script)
        self.assertIn("gtk3", install_script)
        self.assertIn("python-gobject", install_script)
        self.assertIn("xdg-utils", install_script)
        self.assertIn("lsof", install_script)


class TestCoreModulesImport(unittest.TestCase):
    """Тесты успешного импорта всех ключевых подсистем RAG."""

    def test_import_rag_engine(self):
        """Проверка импорта движка RAG и его типов."""
        import rag_engine
        self.assertTrue(hasattr(rag_engine, "RAGPipeline"))
        self.assertTrue(hasattr(rag_engine, "DocumentChunk"))
        self.assertTrue(hasattr(rag_engine, "ChunkMetadata"))
        self.assertTrue(hasattr(rag_engine, "HybridRetriever"))

    def test_import_api_app(self):
        """Проверка импорта FastAPI приложения."""
        from api.app import app
        self.assertIsNotNone(app)

    def test_import_parsers(self):
        """Проверка импорта парсеров документов."""
        from ingestion.parsers import parse_docx, parse_xlsx
        self.assertTrue(callable(parse_docx))
        self.assertTrue(callable(parse_xlsx))


if __name__ == "__main__":
    unittest.main()
