import sys
import re

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CJK_TRANSLATIONS = {
    '班主任': 'к классному руководителю',
    '班级': 'класс',
    '老师': 'учителю',
    '教师': 'учителю',
    '学校': 'школе',
    '学生': 'ученикам',
    '家长': 'родителям',
    '校长': 'директору',
    '教导处': 'учебную часть',
    '教务处': 'учебную часть',
    '体育': 'физкультуре',
    '同学': 'одноклассникам'
}

def sanitize_llm_output(text: str) -> str:
    if not text:
        return ""

    # 1. Замена китайских школьных терминов на русский
    for cjk, rus in CJK_TRANSLATIONS.items():
        if cjk in text:
            text = re.sub(r'([а-яА-ЯёЁa-zA-Z0-9])' + re.escape(cjk), r'\1 ' + rus, text)
            text = text.replace(cjk, rus)

    # 2. Удаление всех CJK и восточно-азиатских символов
    cjk_pattern = re.compile(
        r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u2e80-\u2eff\u3000-\u303f'
        r'\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\uac00-\ud7af\uff00-\uffef]'
    )
    text = cjk_pattern.sub('', text)

    # 3. Разрешенный набор символов: буквы русского и английского алфавита, цифры, стандартные пробелы и пунктуация/markdown
    allowed_chars = (
        r'а-яА-ЯёЁ'
        r'a-zA-Z'
        r'0-9'
        r'\s'
        r'\.,!\?:;\'"«»„“—–\-\(\)\[\]\{\}<>\/\*#№%\+=@&_\\\$~`\^\|'
    )
    allowed_pattern = re.compile(f'[^{allowed_chars}]')
    text = allowed_pattern.sub('', text)

    # 4. Нормализация пробелов и удаление повисших союзов/предлогов
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\b(или|и|а|к|в|с|на|от|у|о|об)\s*([.!?])', r'\2', text)
    return text.strip()

cases = [
    'Если у вас есть конкретные вопросы о требованиях к одежде на уроках физкультуры, рекомендуется обратиться к администрации или班主任',
    'Информация доступна на сайте в разделе "Обучение".',
    '# Правила 2026 года:\n- Пункт 1: форма №2026 (темно-синий/черный).\n- Пункт 2: обувь 100% сменная!',
    'Ответ с китайским 这是一个测试 и арабским مرحبا и смайликом 😊 текст.',
    'Завершение предложения предлогом или 班主任.'
]

for i, c in enumerate(cases, 1):
    print(f"--- TEST {i} ---")
    print("INPUT: ", c)
    print("OUTPUT:", sanitize_llm_output(c))
