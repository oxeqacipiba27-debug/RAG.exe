import json
def check():
    with open('rag_index.json', 'r', encoding='utf-8') as f:
        d = json.load(f)
    found = [x for x in d if 'форм' in x['text'].lower()]
    with open('found.txt', 'w', encoding='utf-8') as f:
        f.write(f"Found {len(found)} chunks with 'форм'\n")
        for x in found[:10]:
            f.write(f"--- {x['source']} (Page {x['page']}) ---\n")
            f.write(x['text'][:200] + "\n\n")

if __name__ == "__main__":
    check()
