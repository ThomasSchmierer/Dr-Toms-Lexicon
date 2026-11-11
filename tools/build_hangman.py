#!/usr/bin/env python3
"""
Builds hangman/words.json for the Lexicon Hangman app from the main game's data:
  - TV and film words: the hand-written words inside index.html, plus approved-all.json (checked automatically)
  - every other show or book each word turns up in (xref.json)
  - Shakespeare (shakes.json) and the set texts (study.json)

Each word keeps every quote it appears in, so the app can filter by any show, film, play or book.
Run after tools/review.py:  python tools/build_hangman.py
"""
import json, os, re, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from review import PROFANE, BLOCK, SHOW_YEARS     # same filters as the reviewer

FILMS = {"A Few Good Men", "A Mighty Wind", "Best in Show", "Four Weddings and a Funeral", "Gosford Park", "Hot Fuzz", "Love Actually",
         "Shaun of the Dead", "The Death of Stalin", "The Social Network", "This Is Spinal Tap", "Waiting for Guffman", "In the Loop",
         "Notting Hill", "For Your Consideration", "Withnail and I", "The Princess Bride", "Monty Python and the Holy Grail",
         "Life of Brian", "Monty Python's Life of Brian", "Withnail & I", "The Grand Budapest Hotel", "Paddington", "Paddington 2"}
BOOKS_BY = {"The Importance of Being Earnest": ("Oscar Wilde", "play"), "A Doll's House": ("Henrik Ibsen", "play"),
            "Poems by Emily Dickinson": ("Emily Dickinson", "poetry"), "Poems of Gerard Manley Hopkins": ("Gerard Manley Hopkins", "poetry"),
            "The Great Gatsby": ("F. Scott Fitzgerald", "novel"), "Mrs Dalloway": ("Virginia Woolf", "novel")}
MARK = re.compile(r"<mark>(.*?)</mark>", re.S)

def load(name, default=None):
    try:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return default

def plain(s): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def episode(to, who):
    m = re.search(r"“([^”]+)”", to or "")
    return m.group(1) if m else ""

def main():
    from wordfreq import zipf_frequency
    rarity = lambda w: max(1, min(10, round(10 - zipf_frequency(w, "en") * 2.6)))

    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    db = json.loads(re.search(r'<script id="db" type="application/json">(.*?)</script>', html, re.S).group(1))
    approved = load("approved-all.json", {"words": {}, "order": [], "shows": {}})
    xref = load("xref.json", {"idx": {}, "fam": {}})
    shakes = load("shakes.json", {"words": {}, "plays": {}})
    study = load("study.json", {"words": {}, "texts": {}})
    show_names = {k: v["name"] for k, v in db["shows"].items()}
    show_names.update({k: v["name"] for k, v in approved.get("shows", {}).items()})

    sources, src_index = [], {}
    def source(name, cat, sub="", by=""):
        sid = slug(name)
        if sid not in src_index:
            src_index[sid] = len(sources)
            sources.append([sid, name, cat, sub, by, 0])
        return src_index[sid]
    def show_source(name):
        return source(name, "film" if name in FILMS else "tv", SHOW_YEARS.get(name, ""))
    for k, (name, group) in shakes.get("plays", {}).items(): source(name, "shakes", group, "William Shakespeare")
    for k, (name, author, kind) in study.get("texts", {}).items(): source(name, "books", kind, author)

    words = {}      # lowercase headword -> entry
    def entry(w, e, prio):
        key = w.lower()
        cur = words.get(key)
        if cur is None or prio < cur["prio"]:
            new = {"w": w, "pos": e.get("pos", ""), "def": plain(e.get("def", "")), "ety": e.get("ety", "") or "",
                   "origin": ">".join(e.get("origin") or ["english"]), "prio": prio, "occ": cur["occ"] if cur else [],
                   "sdef": cur["sdef"] if cur else "", "dd": cur["dd"] if cur else 0, "seen": cur["seen"] if cur else set()}
            if e.get("mode") == "meant": new["def"] = plain(e.get("def", ""))
            words[key] = cur = new
        return cur
    def add(cur, si, line, who, where):
        if not line or not MARK.search(line) or PROFANE.search(plain(line)): return
        line = re.sub(r"(?<![\w<])_+|_+(?![\w>])", "", line).replace("_", " ")       # plain-text italics from Gutenberg books
        sig = plain(line).lower()
        if sig in cur["seen"]: return
        cur["seen"].add(sig)
        cur["occ"].append([si, line.strip(), who or "", where or ""])

    # 1. hand-written show words (always eligible for the word of the day)
    for k, e in db["words"].items():
        if e.get("show") in ("gl", "sh", "st") or not e.get("line"): continue
        if BLOCK.search(e["w"].lower()): continue
        cur = entry(e["w"], e, 0)
        cur["dd"] = ""
        add(cur, show_source(show_names.get(e["show"], e["show"])), e["line"], e.get("who", ""), episode(e.get("to"), e.get("who")))
    # 2. approved show words (join the word of the day from their start date, if rare or long)
    for w in approved.get("order", []):
        e = approved["words"].get(w)
        if not e: continue
        m = re.search(r"Wiktionary puts it as: (.+?)\.(?:\s+[A-Z]|\s*$)", e.get("explain", ""))
        if m and 12 <= len(m.group(1)) <= 160:                     # Wiktionary's wording of the same meaning reads better as a hint
            e = {**e, "def": m.group(1).strip() + "."}
        cur = entry(e["w"], e, 1)
        if cur["dd"] != "" and ((e.get("rarity") or 0) >= 4 or len(e["w"]) >= 9): cur["dd"] = e.get("day", "") or ""
        add(cur, show_source(show_names.get(e["show"], e["show"])), e["line"], e.get("who", ""), episode(e.get("to"), e.get("who")))
    # 3. Shakespeare: curated senses are kept for Shakespeare quotes
    plays = shakes.get("plays", {})
    for k, e in shakes.get("words", {}).items():
        if BLOCK.search(e["w"].lower()): continue
        cur = entry(e["w"], e, 2)
        if e.get("curated"): cur["sdef"] = plain(e.get("def", ""))
        if cur["dd"] == 0 and (e.get("curated") or rarity(e["w"]) >= 5 or len(e["w"]) >= 10): cur["dd"] = ""
        done = set()
        for o in e.get("occ", []):
            if o[0] in done or len(done) >= 6: continue
            name = plays.get(o[0], [o[0]])[0]
            before = len(cur["occ"])
            add(cur, source(name, "shakes", plays.get(o[0], ["", ""])[1], "William Shakespeare"), o[6], o[4], f"Act {o[1]}, Scene {o[2]}")
            if len(cur["occ"]) > before: done.add(o[0])
    # 4. set texts
    texts = study.get("texts", {})
    for k, e in study.get("words", {}).items():
        if BLOCK.search(e["w"].lower()): continue
        cur = entry(e["w"], e, 3)
        if cur["dd"] == 0 and (rarity(e["w"]) >= 5 or len(e["w"]) >= 10): cur["dd"] = ""
        done = set()
        for o in e.get("occ", []):
            if o[0] in done or len(done) >= 4: continue
            t = texts.get(o[0], [o[0], "", ""])
            before = len(cur["occ"])
            add(cur, source(t[0], "books", t[2], t[1]), o[6], "", str(o[1] or ""))
            if len(cur["occ"]) > before: done.add(o[0])
    # 5. every other show or book the word turns up in
    for key, cur in words.items():
        fam = xref["fam"].get(xref["idx"].get(key, key), [])
        for s in fam:
            src, who, where, line, url, kind = (s + ["", "", "", "", "", 0])[:6]
            if kind == 2: continue                                   # Shakespeare and set texts are already in
            if kind == 1:
                by, sub = BOOKS_BY.get(src, ("", "book"))
                si = source(src, "books", sub, by)
            else: si = show_source(src)
            add(cur, si, line, who, where)

    out_words = []
    for key in sorted(words, key=lambda k: (words[k]["prio"], k)):
        cur = words[key]
        if not cur["occ"] or not cur["def"]: continue
        for o in cur["occ"]: sources[o[0]][5] += 1
        out_words.append([cur["w"], cur["pos"], cur["def"], cur["sdef"], cur["ety"], cur["origin"], cur["dd"], cur["occ"][:10]])
    counts = {}
    for s in sources: counts[s[2]] = counts.get(s[2], 0)
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "src": [s for s in sources if s[5]], "w": out_words}
    # source indexes shift when empty sources are dropped
    keep = [i for i, s in enumerate(sources) if s[5]]
    remap = {old: new for new, old in enumerate(keep)}
    for w in out_words:
        for o in w[7]: o[0] = remap[o[0]]
    os.makedirs(os.path.join(ROOT, "hangman"), exist_ok=True)
    path = os.path.join(ROOT, "hangman", "words.json")
    with open(path, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    by_cat = {}
    for s in out["src"]: by_cat[s[2]] = by_cat.get(s[2], 0) + 1
    print(f"Hangman: {len(out_words)} words from {len(out['src'])} sources {by_cat}, "
          f"{sum(1 for w in out_words if w[6] != 0)} can be a word of the day; {os.path.getsize(path) // 1024} KB")

if __name__ == "__main__":
    main()
