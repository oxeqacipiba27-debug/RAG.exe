"""
telegram_bot.py — Высокопроизводительный тонкий клиент Telegram-бота (aiogram 3.x).

Архитектура:
- Тонкий клиент: бот не загружает модели или векторные базы в память, а взаимодействует с центральным RAG API через асинхронные HTTP-запросы.
- Многопользовательский контекст: сессии изолированы по chat_id и персистентно хранятся на сервере.
- Автоматический сплиттинг длинных сообщений (> 4096 символов).
- Корректная обработка цитат документов и статуса генерации (индикатор "печатает...").
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Настройка UTF-8 для консоли Windows и безопасный вывод для pythonw
if sys.platform == "win32":
    if sys.stdout is None:
        try:
            log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")
            sys.stdout = open(log_file, "a", encoding="utf-8", errors="replace", buffering=1)
        except Exception:
            pass
    if sys.stderr is None:
        sys.stderr = sys.stdout

    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import aiohttp
import dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Загружаем настройки из .env
dotenv.load_dotenv(override=True)

# Конфигурация логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("EXSCIORAGBot")

# Параметры подключения
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
RAG_API_BASE_URL = os.getenv("RAG_API_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")
RAG_API_KEY = os.getenv("RAG_API_KEY", "").strip()

# Максимальная длина одного сообщения в Telegram
MAX_TELEGRAM_MESSAGE_LEN = 4000


def get_request_headers() -> Dict[str, str]:
    """Формирует заголовки HTTP для вызовов RAG API."""
    headers = {"Content-Type": "application/json"}
    if RAG_API_KEY:
        headers["X-API-Key"] = RAG_API_KEY
    return headers


def build_chat_keyboard() -> types.InlineKeyboardMarkup:
    """Инлайн-клавиатура для быстрого управления диалогом."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Новая тема", callback_data="reset_context")
    builder.button(text="ℹ️ Статус ИИ-сервера", callback_data="check_status")
    builder.adjust(2)
    return builder.as_markup()


def split_message_by_length(text: str, max_length: int = MAX_TELEGRAM_MESSAGE_LEN) -> List[str]:
    """Безопасно разбивает длинный ответ на части без разрезания слов."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(para) <= max_length:
            current = para
            continue

        # Внутри параграфа пробуем резать по строкам
        lines = para.split("\n")
        for line in lines:
            cand_line = f"{current}\n{line}" if current else line
            if len(cand_line) <= max_length:
                current = cand_line
                continue

            if current:
                chunks.append(current)
                current = ""

            if len(line) <= max_length:
                current = line
                continue

            # Внутри строки режем по словам
            words = line.split(" ")
            for w in words:
                cand_word = f"{current} {w}" if current else w
                if len(cand_word) <= max_length:
                    current = cand_word
                else:
                    if current:
                        chunks.append(current)
                        current = ""
                    while len(w) > max_length:
                        chunks.append(w[:max_length])
                        w = w[max_length:]
                    current = w

    if current:
        chunks.append(current)

    return chunks


async def query_rag_api(chat_id: int, user_id: int, query_text: str) -> Dict[str, Any]:
    """Отправка вопроса пользователя в RAG API сервер."""
    url = f"{RAG_API_BASE_URL}/telegram/message"
    payload = {
        "chat_id": str(chat_id),
        "user_id": str(user_id),
        "query": query_text
    }
    timeout = aiohttp.ClientTimeout(total=95)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=get_request_headers()) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                err_text = await resp.text()
                logger.error(f"RAG API returned HTTP {resp.status}: {err_text}")
                raise RuntimeError(f"Ошибка RAG API ({resp.status}): {err_text}")


async def reset_rag_session(chat_id: int) -> Dict[str, Any]:
    """Сброс контекста беседы для данного chat_id."""
    url = f"{RAG_API_BASE_URL}/chat/sessions/{chat_id}/reset"
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=get_request_headers()) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                err_text = await resp.text()
                logger.error(f"Reset session error ({resp.status}): {err_text}")
                raise RuntimeError(f"Не удалось сбросить диалог ({resp.status})")


async def check_rag_health() -> Dict[str, Any]:
    """Проверка доступности RAG сервера."""
    url = f"{RAG_API_BASE_URL}/health"
    timeout = aiohttp.ClientTimeout(total=8)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=get_request_headers()) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                return {"status": "unhealthy", "message": f"HTTP {resp.status}"}


# ==============================================================================
# Telegram Handlers
# ==============================================================================

dp = Dispatcher()


@dp.message(CommandStart())
async def handle_start(message: types.Message):
    """Приветственное сообщение и инициализация работы."""
    user_name = message.from_user.first_name if message.from_user else "пользователь"
    welcome_text = (
        f"👋 Здравствуйте, <b>{html.escape(user_name)}</b>!\n\n"
        f"Я официальный ИИ-ассистент <b>EXSCIO</b>.\n\n"
        f"Я помогу найти точную информацию в регламентах, положениях и нормативных документах базы знаний.\n\n"
        f"Задайте мне любой вопрос в свободной форме!"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML, reply_markup=build_chat_keyboard())


@dp.message(Command("help"))
async def handle_help(message: types.Message):
    """Справка по доступным командам."""
    help_text = (
        "💡 <b>Как пользоваться ботом:</b>\n\n"
        "1. Просто напишите ваш вопрос обычным сообщением.\n"
        "2. Бот выполнит интеллектуальный поиск по нормативной базе знаний и подготовит ответ с точными ссылками на документы.\n"
        "3. Если вы хотите сменить тему беседы, нажмите <b>«🔄 Новая тема»</b> или отправьте команду /reset.\n\n"
        "<b>Команды:</b>\n"
        "• /reset — очистить память текущего диалога\n"
        "• /status — проверить статус серверов и базы знаний\n"
        "• /help — эта справка"
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML, reply_markup=build_chat_keyboard())


@dp.message(Command("reset"))
async def handle_reset_command(message: types.Message):
    """Сброс контекста через команду /reset."""
    await execute_reset(message.chat.id, message)


@dp.message(Command("status"))
async def handle_status_command(message: types.Message):
    """Проверка здоровья ядра RAG."""
    await execute_status_check(message)


@dp.callback_query(F.data == "reset_context")
async def handle_callback_reset(callback: types.CallbackQuery):
    """Сброс контекста по нажатию инлайн-кнопки."""
    await callback.answer("Очистка контекста...")
    await execute_reset(callback.message.chat.id, callback.message)


@dp.callback_query(F.data == "check_status")
async def handle_callback_status(callback: types.CallbackQuery):
    """Проверка статуса по нажатию инлайн-кнопки."""
    await callback.answer("Запрос статуса RAG...")
    await execute_status_check(callback.message)


async def execute_reset(chat_id: int, message: types.Message):
    """Выполнение операции сброса контекста."""
    try:
        await reset_rag_session(chat_id)
        msg_text = "🔄 <b>Контекст диалога очищен.</b> Можете задать вопрос по новой теме."
    except Exception as e:
        logger.exception("Reset failed")
        msg_text = f"⚠️ Не удалось сбросить сессию: {html.escape(str(e))}"
    await message.answer(msg_text, parse_mode=ParseMode.HTML, reply_markup=build_chat_keyboard())


async def execute_status_check(message: types.Message):
    """Выполнение проверки здоровья сервиса."""
    try:
        health_data = await check_rag_health()
        status_val = health_data.get("status", "unknown")
        provider = health_data.get("llm_provider", "N/A")
        chunks = health_data.get("total_chunks", 0)
        msg_diag = health_data.get("message", "Ок")

        status_emoji = "🟢" if status_val == "healthy" else ("🟡" if status_val == "degraded" else "🔴")
        status_text = (
            f"{status_emoji} <b>Статус RAG-сервера:</b> <code>{status_val}</code>\n\n"
            f"• <b>LLM Провайдер:</b> <code>{provider}</code>\n"
            f"• <b>Загружено фрагментов базы:</b> <code>{chunks}</code>\n"
            f"• <b>Диагностика:</b> {html.escape(msg_diag)}"
        )
    except Exception as e:
        status_text = f"🔴 <b>RAG API сервер недоступен:</b>\n<code>{html.escape(str(e))}</code>\n\nУбедитесь, что запущен <code>start_api.bat</code>."
    await message.answer(status_text, parse_mode=ParseMode.HTML, reply_markup=build_chat_keyboard())


@dp.message(F.text)
async def handle_user_query(message: types.Message, bot: Bot):
    """Основной обработчик текстовых сообщений пользователя."""
    query = message.text.strip()
    if not query:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else chat_id

    # Задача фоновой отправки статуса "печатает..."
    typing_active = True

    async def keep_typing():
        while typing_active:
            try:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                pass
            await asyncio.sleep(4.5)

    typing_task = asyncio.create_task(keep_typing())

    try:
        # Выполняем обращение к RAG API
        result = await query_rag_api(chat_id=chat_id, user_id=user_id, query_text=query)
        answer = result.get("answer", "Ответ не сформирован.")
        sources = result.get("sources", [])
        latency_ms = result.get("latency_ms", 0.0)

        # Форматируем блок цитат/первоисточников
        sources_text = ""
        if sources:
            src_lines = []
            seen_sources = set()
            for s in sources:
                src_name = s.get("source", "Документ")
                page = s.get("page")
                key = (src_name, page)
                if key not in seen_sources:
                    seen_sources.add(key)
                    pg_str = f" (стр. {page})" if page else ""
                    src_lines.append(f"• <i>{html.escape(str(src_name))}</i>{pg_str}")

            if src_lines:
                sources_text = "\n\n📚 <b>Первоисточники:</b>\n" + "\n".join(src_lines[:4])

        full_message = f"{html.escape(answer)}{sources_text}"

        # Разбиваем сообщение, если длина превышает лимит Telegram
        message_chunks = split_message_by_length(full_message, MAX_TELEGRAM_MESSAGE_LEN)

        for i, chunk in enumerate(message_chunks):
            is_last = (i == len(message_chunks) - 1)
            kb = build_chat_keyboard() if is_last else None
            await message.answer(chunk, parse_mode=ParseMode.HTML, reply_markup=kb)

    except aiohttp.ClientConnectorError:
        err_msg = (
            "⚠️ <b>Сервер ИИ-консультаций временно недоступен.</b>\n\n"
            "Пожалуйста, запустите API-сервер через <code>start_api.bat</code> или обратитесь к администратору."
        )
        await message.answer(err_msg, parse_mode=ParseMode.HTML, reply_markup=build_chat_keyboard())

    except Exception as exc:
        logger.exception("Error processing user query")
        err_msg = f"⚠️ Произошла ошибка при обработке запроса:\n<code>{html.escape(str(exc))}</code>"
        await message.answer(err_msg, parse_mode=ParseMode.HTML, reply_markup=build_chat_keyboard())

    finally:
        typing_active = False
        typing_task.cancel()


# ==============================================================================
# Entry Point
# ==============================================================================

async def main():
    print("=" * 65)
    print(" 🤖 Запуск Telegram-бота SchoolX RAG (aiogram 3.x)")
    print(f" 📡 RAG API сервер: {RAG_API_BASE_URL}")
    print("=" * 65)

    if not BOT_TOKEN:
        print("\n[!] ОШИБКА: Токен Telegram-бота не указан!")
        print("    1. Откройте @BotFather в Telegram и создайте бота (/newbot).")
        print("    2. Скопируйте полученный токен.")
        print("    3. Добавьте его в файл .env:")
        print("       TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ\n")
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Проверка связи с RAG сервером перед запуском polling
    try:
        health = await check_rag_health()
        logger.info(f"[OK] Подключение к RAG API успешно: {health.get('status')} (провайдер: {health.get('llm_provider')})")
    except Exception as e:
        logger.warning(f"[!] Внимание: RAG API сервер сейчас недоступен ({e}). Бот продолжит запуск в режиме ожидания сервера.")

    logger.info("Запуск Telegram Polling...")
    await dp.start_polling(bot)


def run_gui():
    """Графическое окно управления Telegram-ботом SchoolX."""
    try:
        import tkinter as tk
    except ImportError:
        asyncio.run(main())
        return

    import threading

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    root = tk.Tk()
    root.title("SchoolX 2.0 — Telegram RAG Bot")
    root.geometry("490x290")
    root.resizable(False, False)
    root.configure(bg="#100c1b")

    ico_path = os.path.join(os.path.dirname(__file__), "rag_icon.ico")
    if os.path.exists(ico_path):
        try:
            root.iconbitmap(ico_path)
        except Exception:
            pass

    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - 490) // 2)
    y = max(0, (sh - 290) // 2)
    root.geometry(f"490x290+{x}+{y}")

    # Header
    header = tk.Frame(root, bg="#100c1b", padx=20, pady=16)
    header.pack(fill="x")
    top_row = tk.Frame(header, bg="#100c1b")
    top_row.pack(fill="x")

    t_lbl = tk.Label(top_row, text="SchoolX Telegram Bot", font=("Segoe UI", 16, "bold"), fg="#f6effa", bg="#100c1b")
    t_lbl.pack(side="left")

    badge = tk.Label(top_row, text="  aiogram 3.x  ", font=("Segoe UI", 9, "bold"), fg="#38bdf8", bg="#0c2340")
    badge.pack(side="right")

    sub_lbl = tk.Label(header, text="Тонкий клиент для взаимодействия с корпоративным RAG API", font=("Segoe UI", 9), fg="#94a3b8", bg="#100c1b")
    sub_lbl.pack(anchor="w", pady=(2, 0))

    if not BOT_TOKEN:
        card = tk.Frame(root, bg="#2d1520", bd=1, relief="solid", highlightthickness=1, highlightbackground="#6b213f", padx=16, pady=12)
        card.pack(fill="x", padx=20, pady=(0, 14))

        st_lbl = tk.Label(card, text="⚠️ Токен бота не указан в конфигурации .env", font=("Segoe UI", 10, "bold"), fg="#f87171", bg="#2d1520")
        st_lbl.pack(anchor="w")

        info_lbl = tk.Label(
            card,
            text="Создайте бота в @BotFather и укажите токен в .env:\nTELEGRAM_BOT_TOKEN=123456:ABC...",
            font=("Segoe UI", 9),
            fg="#fca5a5",
            bg="#2d1520",
            justify="left"
        )
        info_lbl.pack(anchor="w", pady=(4, 0))

        btn = tk.Button(root, text="Закрыть", command=root.destroy, font=("Segoe UI", 9), fg="#f6effa", bg="#271f3a", activebackground="#342b4d", bd=1, relief="solid", padx=20, pady=5)
        btn.pack(pady=10)
        root.mainloop()
        return

    card = tk.Frame(root, bg="#1b1428", bd=1, relief="solid", highlightthickness=1, highlightbackground="#382e54", padx=16, pady=12)
    card.pack(fill="x", padx=20, pady=(0, 14))

    st_lbl = tk.Label(card, text="● Бот активен (Polling режим ожидания)", font=("Segoe UI", 10, "bold"), fg="#10b981", bg="#1b1428")
    st_lbl.pack(anchor="w")

    info_lbl = tk.Label(card, text=f"RAG API Шлюз: {RAG_API_BASE_URL}", font=("Segoe UI", 9), fg="#cbd5e1", bg="#1b1428")
    info_lbl.pack(anchor="w", pady=(4, 0))

    bot_loop = None

    def bot_worker():
        nonlocal bot_loop
        bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(bot_loop)
        try:
            bot_loop.run_until_complete(main())
        except Exception:
            pass

    def on_stop():
        if bot_loop and bot_loop.is_running():
            bot_loop.call_soon_threadsafe(bot_loop.stop)
        try:
            root.destroy()
        except Exception:
            pass

    btn_frame = tk.Frame(root, bg="#100c1b", padx=20)
    btn_frame.pack(fill="x")

    btn_stop = tk.Button(
        btn_frame,
        text="⏹️ Остановить бота",
        command=on_stop,
        font=("Segoe UI", 9),
        fg="#fca5a5",
        bg="#271a2a",
        activebackground="#3b1d28",
        activeforeground="#ffffff",
        bd=1,
        relief="solid",
        cursor="hand2",
        pady=6
    )
    btn_stop.pack(fill="x")

    root.protocol("WM_DELETE_WINDOW", on_stop)

    t = threading.Thread(target=bot_worker, daemon=True)
    t.start()

    root.mainloop()


if __name__ == "__main__":
    if "--gui" in sys.argv:
        run_gui()
    else:
        try:
            asyncio.run(main())
        except (KeyboardInterrupt, SystemExit):
            logger.info("Бот остановлен пользователем.")
