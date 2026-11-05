import unittest
from unittest.mock import patch
from pathlib import Path
import server_manager

class TestServerManagerLLMEngine(unittest.TestCase):
    def test_get_llm_engine_service_path(self):
        path = server_manager.get_llm_engine_service_path()
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        self.assertEqual(path.name.lower(), "service.py")

    def test_get_llm_engine_python_path(self):
        py_path = server_manager.get_llm_engine_python_path()
        self.assertTrue(bool(py_path))
        self.assertTrue(Path(py_path).exists())

    def test_is_llm_engine_online_contract(self):
        # Real invocation check returns bool
        online = server_manager.is_llm_engine_online(timeout=0.2)
        self.assertIsInstance(online, bool)

    @patch("server_manager.is_llm_engine_online", return_value=True)
    def test_ensure_llm_engine_service_already_online(self, mock_online):
        ok, msg = server_manager.ensure_llm_engine_service()
        self.assertTrue(ok)
        self.assertIn("активна", msg)

    @patch("server_manager.is_llm_engine_online", return_value=False)
    @patch("server_manager.start_llm_engine_service", return_value=(True, "Автономная служба LLM Engine успешно запущена на 127.0.0.1:8000."))
    def test_ensure_llm_engine_service_spawns_when_offline(self, mock_start, mock_online):
        ok, msg = server_manager.ensure_llm_engine_service()
        self.assertTrue(ok)
        self.assertIn("успешно запущена", msg)
        mock_start.assert_called_once()

if __name__ == "__main__":
    unittest.main()
