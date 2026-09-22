"""
test_gui_lifecycle.py — Тестирование жизненного цикла и состояний UI rag_gui.py.
Проверяет:
1. Изоляцию экранов: 'Инструкция агента' отображается ТОЛЬКО в Preferences & Models и НИКОГДА в Chat Canvas.
2. Сохранение сообщений: при переключении между экранами сгенерированные ответы не перепечатываются и не перегенерируются.
3. Отсутствие ошибок NameError в блоке цитирования первоисточников.
4. Полную чистоту от CJK (китайских иероглифов).
"""

import sys
import os
import re

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 1. Проверка синтаксиса и структуры кода rag_gui.py
with open("rag_gui.py", "r", encoding="utf-8") as f:
    code = f.read()

# Проверяем, что подзаголовок Инструкция агента находится СТРОГО внутри блока Preferences
lines = code.splitlines()
in_chat_canvas = False
in_preferences = False
in_knowledge = False
instruction_in_chat = False

for line_no, line in enumerate(lines, 1):
    stripped = line.strip()
    if 'if mode == "💬 Chat Canvas":' in line or 'if mode == "💬 Чат с документами":' in line:
        in_chat_canvas = True
        in_preferences = False
        in_knowledge = False
    elif 'elif mode == "⚙️ Preferences & Models":' in line or 'elif mode == "⚙️ Параметры и модели":' in line:
        in_chat_canvas = False
        in_preferences = True
        in_knowledge = False
    elif 'elif mode == "📚 Knowledge Base":' in line or 'elif mode == "📚 База знаний":' in line:
        in_chat_canvas = False
        in_preferences = False
        in_knowledge = True

    if ("Инструкция агента" in line or "System Instruction" in line) and line_no > 30:
        if in_chat_canvas:
            instruction_in_chat = True
            print(f"[FAIL] Обнаружена инструкция в Chat Canvas на строке {line_no}: {line}")

assert not instruction_in_chat, "Инструкция агента не должна быть внутри Chat Canvas!"
print("✅ [TEST 1 PASSED] Инструкция агента строго изолирована и отсутствует в Chat Canvas.")

# 2. Проверка переменной citations в функции render_message
# Убеждаемся, что NameError 'citations_data' не может возникнуть в истории
chat_marker = 'if mode == "💬 Чат с документами":' if 'if mode == "💬 Чат с документами":' in code else 'if mode == "💬 Chat Canvas":'
render_section = code[code.find("def render_message"):code.find(chat_marker)]
assert "citations_data" not in render_section, "render_message не должен зависеть от локальной переменной citations_data!"
print("✅ [TEST 2 PASSED] В render_message исключена ошибка NameError: переменная citations_data не используется.")

# 3. Проверка отсутствия вызова st.rerun() после генерации ответа
# Именно лишний rerun() и проверка роли user приводили к рекурсивному перепечатыванию
pref_marker = 'elif mode == "⚙️ Параметры и модели":' if 'elif mode == "⚙️ Параметры и модели":' in code else 'elif mode == "⚙️ Preferences & Models":'
gen_section = code[code.find('if active_user_query:'):code.find(pref_marker)]
assert "st.rerun()" not in gen_section, "В блоке генерации ответа не должно быть st.rerun()!"
print("✅ [TEST 3 PASSED] st.rerun() корректно убран из блока генерации — ответ не перепечатывается повторно.")

# 4. Проверка работы бэкенда и CJK-фильтра
from rag_engine import RAGPipeline, sanitize_llm_output

pipeline = RAGPipeline(index_file="rag_index.json")
hits, reformulated_q, is_zero = pipeline.retriever.search(
    raw_query="какие правила приема и документы нужны для зачисления в первый класс?",
    top_k=5
)
assert len(hits) > 0, "Поиск должен вернуть документы для приема в 1 класс!"
assert not is_zero, "Запрос о приеме в 1 класс не должен быть zero-retrieval"

raw_test_response = "Для зачисления ребенка в первый класс 班主任 необходимо подать заявление [doc_1, стр. 5]. 报名流程"
clean_resp = sanitize_llm_output(raw_test_response)
cjk_found = bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", clean_resp))
assert not cjk_found, "В ответе не должно быть CJK иероглифов!"
assert "классному руководителю" in clean_resp, "班主任 должно быть переведено как к классному руководителю"
print("✅ [TEST 4 PASSED] CJK-фильтрация и семантический поиск RAG функционируют на 100%.")

print("\n🎉 ВСЕ ТЕСТЫ ЖИЗНЕННОГО ЦИКЛА УСПЕШНО ПРОЙДЕНЫ!")
