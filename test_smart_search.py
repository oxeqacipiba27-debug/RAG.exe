import json
import re
import math
import sys

sys.stdout.reconfigure(encoding='utf-8')

db = json.load(open('rag_index.json', encoding='utf-8'))

def stem(w):
    w = w.lower().replace('ё', 'е')
    return re.sub(r'(?:ами|ями|ов|ев|ам|ям|ом|ем|ой|ей|ью|ях|ах|ии|ия|ию|ие|ое|ее|ые|ых|их|ую|юю|ая|яя|ый|ой|ий|а|е|и|й|о|у|ы|ь|ю|я)$', '', w)

def normalize_ranges(text):
    # Раскрываем диапазоны вида "1- 4", "5 -9", "10-11" в отдельные классы
    def repl(m):
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start <= 11 and 1 <= end <= 11 and start < end:
            all_grades = " ".join(str(g) for g in range(start, end + 1))
            return f"{m.group(0)} {start}-{end} {all_grades}"
        return m.group(0)
    return re.sub(r'\b(\d+)\s*-\s*(\d+)\b', repl, text)

def search_smart(query, items, top_k=6):
    q_words = re.findall(r'\b[a-zA-Zа-яёА-ЯЁ0-9_-]+\b', query.lower().replace('ё', 'е'))
    stops = {'какая', 'какой', 'какие', 'каком', 'что', 'кто', 'где', 'как', 'это', 'для', 'при', 'под', 'в', 'и', 'на', 'с', 'по'}
    meaningful = [w for w in q_words if w not in stops]
    stems = [stem(w) for w in meaningful]
    
    is_clothing_query = any(w in query.lower() for w in ['форм', 'одежд', 'стил', 'внешн', 'дресс', 'носить', 'цвет'])
    
    scores = []
    for i, item in enumerate(items):
        raw_text = item['text'].lower().replace('ё', 'е')
        text = normalize_ranges(raw_text)
        source = item['source'].lower()
        full_text = text + ' ' + source
        words = text.split()
        
        score = 0.0
        # 1. Stem matches
        matched_stems = set()
        for st in stems:
            if re.search(r'\b' + re.escape(st), full_text):
                matched_stems.add(st)
                score += 3.0
                if st.isdigit():
                    score += 5.0 # числа очень важны (5 класс, 1 класс, 10 класс)
                if st in source:
                    score += 15.0 # точное совпадение с именем файла
        
        # Документ ОБЯЗАН содержать хотя бы одно смысловое слово (не только цифры!)
        if not any(not st.isdigit() for st in matched_stems):
            continue
            
        # Если запрос про форму/одежду, документ ОБЯЗАН содержать упоминание формы или одежды/внешнего вида
        if is_clothing_query and not any(w in text or w in source for w in ['форм', 'одежд', 'стил', 'внешн', 'дресс']):
            continue
            
        # 2. Бонус за процент совпавших ключевых слов
        match_ratio = len(matched_stems) / len(stems) if stems else 0
        score *= (1.0 + match_ratio * 3.0)
        
        # 3. Бонус за близость слов запроса в тексте
        for j in range(len(stems) - 1):
            st1, st2 = stems[j], stems[j+1]
            if st1 in matched_stems and st2 in matched_stems:
                pattern1 = r'\b' + re.escape(st1) + r'\w*\b(?:\W+\w+){0,10}?\W+\b' + re.escape(st2) + r'\w*\b'
                pattern2 = r'\b' + re.escape(st2) + r'\w*\b(?:\W+\w+){0,10}?\W+\b' + re.escape(st1) + r'\w*\b'
                if re.search(pattern1, text) or re.search(pattern2, text):
                    score += 25.0
                    
        # 4. Специфический семантический бонус за одежду/форму
        if is_clothing_query:
            clothing_indicators = ['одежд', 'дресс', 'блузк', 'рубашк', 'брюк', 'костюм', 'туфл', 'юбк', 'пиджак', 'жилет', 'сарафан', 'галстук', 'обув']
            if any(w in text for w in clothing_indicators):
                score += 30.0
            # Огромный бонус за официальные памятки по форме
            if any(p in text for p in ['деловой стиль', 'стиль одежды', 'цвет формы', 'памятка для родителей и учащихся']):
                score += 60.0
            # Если это "форма обучения" без одежды - штрафуем
            if 'форма обучения' in text and not any(w in text for w in clothing_indicators):
                score *= 0.2
                
        # Нормализация на длину
        score = score / math.log(len(words) + 15)
        scores.append((score, i))
        
    scores.sort(key=lambda x: x[0], reverse=True)
    
    # Дедупликация
    res = []
    file_counts = {}
    for sc, idx in scores:
        src = items[idx]['source']
        if file_counts.get(src, 0) < 2:
            res.append((sc, items[idx]))
            file_counts[src] = file_counts.get(src, 0) + 1
        if len(res) >= top_k:
            break
    return res

test_queries = [
    'какая форма в 5 классе',
    'форма для 1-4 классов',
    'форма для 10 класса',
    'правила поведения в школе',
    '6a7d65434d2f9.pdf'
]

for q in test_queries:
    print(f"\n==================== QUERY: {q} ====================")
    results = search_smart(q, db, top_k=3)
    for sc, item in results:
        src = item['source']
        p = item['page']
        snip = item['text'][:120].replace('\n', ' ')
        print(f"[{sc:.2f}] {src} (стр. {p}): {snip}...")

print("\n==================== MULTI-TURN TEST ====================")
turn1_q = "какая форма в 5 классе"
turn2_raw = "а для мальчиков?"
turn2_enriched = f"{turn1_q} {turn2_raw}"
print(f"Follow-up query: '{turn2_raw}' -> Enriched search: '{turn2_enriched}'")
results2 = search_smart(turn2_enriched, db, top_k=2)
for sc, item in results2:
    src = item['source']
    p = item['page']
    snip = item['text'][:120].replace('\n', ' ')
    print(f"[{sc:.2f}] {src} (стр. {p}): {snip}...")
