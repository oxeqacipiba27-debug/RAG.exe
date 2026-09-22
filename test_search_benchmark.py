import sys
import io
import json
import math
import re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('rag_index.json', 'r', encoding='utf-8') as f:
    index_data = json.load(f)

print(f"Loaded {len(index_data)} chunks.")

# Словарь порядковых числительных и терминов классов
GRADE_WORDS = {
    'перв': '1 1-4', '1-й': '1 1-4', '1й': '1 1-4', 'началк': '1-4', 'младш': '1-4',
    'втор': '2 1-4', '2-й': '2 1-4', '2й': '2 1-4',
    'трет': '3 1-4', '3-й': '3 1-4', '3й': '3 1-4',
    'четверт': '4 1-4', '4-й': '4 1-4', '4й': '4 1-4',
    'пят': '5 5-9', '5-й': '5 5-9', '5й': '5 5-9', 'средн': '5-9',
    'шест': '6 5-9', '6-й': '6 5-9', '6й': '5 5-9',
    'седьм': '7 5-9', '7-й': '7 5-9', '7й': '7 5-9',
    'восьм': '8 5-9', '8-й': '8 5-9', '8й': '8 5-9',
    'девят': '9 5-9', '9-й': '9 5-9', '9й': '9 5-9',
    'десят': '10 10-11', '10-й': '10 10-11', '10й': '10 10-11', 'старш': '10-11', 'выпускн': '10-11',
    'одиннадцат': '11 10-11', '11-й': '11 10-11', '11й': '11 10-11'
}

# Синонимы и тематические расширения
SYNONYM_GROUPS = [
    {
        'triggers': ['одежд', 'одеажд', 'форм', 'дресс', 'стил', 'внешн', 'носить', 'надеть', 'ходить', 'гардероб', 'костюм', 'блузк', 'брюк', 'юбк', 'сарафан', 'туфл', 'обув', 'вещ', 'джинс', 'сменк'],
        'expansion': 'деловой стиль одежды форма цвет памятка обучающихся школьная форма'
    },
    {
        'triggers': ['документ', 'поступлен', 'зачислен', 'прием', 'поступить', 'записаться', 'паспорт', 'справк'],
        'expansion': 'правила приема зачисления перечень документов заявление'
    },
    {
        'triggers': ['каникул', 'отдых', 'четверт', 'триместр', 'период', 'график'],
        'expansion': 'сроки каникул учебные периоды учебный график'
    },
    {
        'triggers': ['питан', 'еда', 'столов', 'обед', 'завтрак', 'меню', 'льготн'],
        'expansion': 'организация питания школьная столовая меню горячее питание'
    }
]

# Высокочастотные слова школьного корпуса (фактически стоп-слова для школьной базы)
CORPUS_STOP_WORDS = {
    'школа', 'школы', 'школе', 'школу', 'школой', 'школьном', 'школьный', 'школьная', 'школьное', 'школьные', 'школьного',
    'нашей', 'наш', 'нашего', 'наша', 'наших', 'нашему',
    'гбоу', '1468', 'москвы', 'москва', 'город', 'города',
    'какая', 'какой', 'какие', 'каком', 'каких', 'какую', 'какое', 'каким', 'какими',
    'что', 'кто', 'где', 'когда', 'куда', 'откуда', 'почему', 'зачем', 'как', 'сколько',
    'это', 'этот', 'эта', 'эти', 'этих', 'этом', 'этому', 'этой',
    'был', 'была', 'были', 'быть', 'есть', 'будет', 'будут',
    'все', 'всех', 'всем', 'всеми', 'всё', 'всего',
    'для', 'при', 'под', 'над', 'без', 'через', 'про', 'обо',
    'или', 'если', 'так', 'уже', 'еще', 'ещё', 'нет', 'да', 'в', 'и', 'на', 'с', 'по',
    'нужна', 'нужно', 'нужны', 'нужен', 'можно', 'надо', 'подскажи', 'скажи', 'пожалуйста',
    'ученик', 'ученика', 'учеников', 'ребенок', 'ребенка', 'детям', 'детей'
}

def stem_word(w: str) -> str:
    w = w.lower().replace('ё', 'е')
    w = re.sub(r'(?:ами|ями|ов|ев|ам|ям|ом|ем|ой|ей|ью|ях|ах|ии|ия|ию|ие|ое|ее|ые|ых|их|ую|юю|ая|яя|ый|ой|ий|а|е|и|й|о|у|ы|ь|ю|я)$', '', w)
    return w

def normalize_ranges(text: str) -> str:
    def repl(m):
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start <= 11 and 1 <= end <= 11 and start < end:
            all_grades = " ".join(str(g) for g in range(start, end + 1))
            return f"{m.group(0)} {start}-{end} {all_grades}"
        return m.group(0)
    return re.sub(r'\b(\d+)\s*-\s*(\d+)\b', repl, text)

def fix_typos_and_expand(query: str) -> str:
    typo_map = {
        'одеажда': 'одежда', 'одеажды': 'одежды', 'одеажде': 'одежде', 'одеажду': 'одежду',
        'одёжа': 'одежда', 'фома': 'форма', 'дрескод': 'дресс-код',
        'директр': 'директор', 'клас': 'класс', 'класе': 'классе'
    }
    tokens = re.findall(r'\b[a-zA-Zа-яёА-ЯЁ0-9_-]+\b', query.lower().replace('ё', 'е'))
    fixed_tokens = [typo_map.get(t, t) for t in tokens]
    expanded_text = " ".join(fixed_tokens)
    
    # Расширение числительных классов
    for word in fixed_tokens:
        for root, exp in GRADE_WORDS.items():
            if root in word:
                expanded_text += f" {exp}"
                break
                
    # Расширение синонимов
    for group in SYNONYM_GROUPS:
        if any(tr in expanded_text for tr in group['triggers']):
            expanded_text += f" {group['expansion']}"
            break
            
    return expanded_text

def smart_search(query: str, top_k: int = 5):
    expanded_query = fix_typos_and_expand(query)
    q_words = re.findall(r"\b[a-zA-Zа-яёА-ЯЁ0-9_-]+\b", expanded_query.lower().replace('ё', 'е'))
    meaningful = [w for w in q_words if w not in CORPUS_STOP_WORDS]
    if not meaningful:
        meaningful = [w for w in q_words if len(w) > 2]
    stems = [stem_word(w) for w in meaningful]
    
    is_clothing_query = any(w in expanded_query for w in ['форм', 'одежд', 'стил', 'внешн', 'дресс', 'носить', 'цвет', 'костюм', 'брюк', 'блузк', 'юбк', 'сарафан'])
    
    scores = {}
    for i, item in enumerate(index_data):
        raw_text = item.get('text', '').lower().replace('ё', 'е')
        text = normalize_ranges(raw_text)
        source = item.get('source', '').lower()
        full_text = text + ' ' + source
        words = text.split()
        
        score = 0.0
        matched_stems = set()
        for st in stems:
            if re.search(r'\b' + re.escape(st), full_text):
                matched_stems.add(st)
                # Дифференцированный вес для редких слов
                if st.isdigit():
                    score += 15.0 # номер класса крайне важен
                elif st in ['одежд', 'форм', 'стил', 'дресс', 'делов']:
                    score += 8.0
                else:
                    score += 3.0
                if st in source:
                    score += 15.0
                    
        if not matched_stems:
            continue
            
        # Если в запросе были смысловые слова, отсекаем совпадения только по одним цифрам
        has_non_digits = any(not s.isdigit() for s in stems)
        if has_non_digits and not any(not s.isdigit() for s in matched_stems):
            continue
            
        if is_clothing_query and not any(w in text or w in source for w in ['форм', 'одежд', 'стил', 'внешн', 'дресс', 'костюм']):
            continue
            
        # Коэффициент покрытия запроса
        match_ratio = len(matched_stems) / len(set(stems)) if stems else 0
        score *= (1.0 + match_ratio * 4.0)
        
        # Бонус за близость ключевых слов
        for j in range(len(stems) - 1):
            st1, st2 = stems[j], stems[j+1]
            if st1 in matched_stems and st2 in matched_stems and st1 != st2:
                pattern1 = r'\b' + re.escape(st1) + r'\w*\b(?:\W+\w+){0,8}?\W+\b' + re.escape(st2) + r'\w*\b'
                pattern2 = r'\b' + re.escape(st2) + r'\w*\b(?:\W+\w+){0,8}?\W+\b' + re.escape(st1) + r'\w*\b'
                if re.search(pattern1, text) or re.search(pattern2, text):
                    score += 30.0
                    
        if is_clothing_query:
            clothing_indicators = ['одежд', 'дресс', 'блузк', 'рубашк', 'брюк', 'костюм', 'туфл', 'юбк', 'пиджак', 'жилет', 'сарафан', 'галстук', 'обув']
            if any(w in text for w in clothing_indicators):
                score += 35.0
            if any(p in text for p in ['деловой стиль', 'стиль одежды', 'цвет формы', 'памятка для родителей и учащихся', 'памятка для родителей']):
                score += 70.0
            if 'форма обучения' in text and not any(w in text for w in clothing_indicators):
                score *= 0.1
                
        # Логарифмическая нормализация по длине
        score = score / math.log(len(words) + 10)
        scores[i] = score

    sorted_idx = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    results = []
    seen = {}
    for i, sc in sorted_idx:
        src = index_data[i]['source']
        if seen.get(src, 0) < 2:
            results.append((index_data[i], sc))
            seen[src] = seen.get(src, 0) + 1
        if len(results) >= top_k:
            break
    return results

test_queries = [
    "какая одеажда нужна для нашей школы",
    "форма одежды",
    "в чем ходить пятикласснику",
    "какая форма в 5 классе",
    "форма для 1-4 классов",
    "форма для старших классов",
    "можно ли носить джинсы",
    "какой цвет формы у первоклассников"
]

print("\n" + "="*60)
for q in test_queries:
    res = smart_search(q, top_k=3)
    print(f"\nQUERY: '{q}'")
    for r, sc in res:
        print(f"  [{sc:.2f}] {r['source']} (p.{r['page']}): {r['text'][:90].replace(chr(10), ' ')}...")
