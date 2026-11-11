#!/usr/bin/env python3
"""
Moira's Lexicon harvester: finds rare words in quotes and public-domain books
and turns the ones you approve into game entries.

  1. harvest   python tools/harvest.py wikiquote "Frasier" "Yes Minister"
               python tools/harvest.py gutenberg 1342 --title "Pride and Prejudice" --author "Jane Austen"
               -> writes a review spreadsheet (CSV) into harvest/
  2. review    open the CSV, put y in the "keep" column for the words you want,
               and optionally type your own meaning in "definition"
  3. draft     python tools/harvest.py draft harvest/frasier.csv --edition all --show-key fr --show-name "Frasier" --years "1993–2004"
               -> adds the kept words to extra-words.json, which the game loads automatically

Wikiquote text is CC BY-SA; Project Gutenberg books are public domain in Australia.
The harvester asks Wikiquote's API for one page per second and identifies itself.
"""
import argparse, csv, html, json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UA = "MoiraLexiconHarvester/1.0 (+https://github.com/ThomasSchmierer/Moira-Lexicon)"
API = "https://en.wikiquote.org/w/api.php"
BLOCK = re.compile(r"(rape|whore|bawd|cuckold|strumpet|harlot|slut|cunt|fuck|shit|piss|nigg|negro|fag|dyke|retard|tranny|spic|kike|wog|"
                   r"penis|vagin|genital|semen|sperm|nipple|orgas|masturb|erotic|sexual|porn|incest|suicide|bitch|bastard|wank|bollock|arse|twat)")

def zipf(word):
    from wordfreq import zipf_frequency
    return zipf_frequency(word, "en")

def fetch(url, tries=5):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if attempt == tries - 1: raise
            time.sleep(3 * (attempt + 1))

def api(params):
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    for attempt in range(6):
        data = json.loads(fetch(API + "?" + urllib.parse.urlencode(params)))
        if data.get("error", {}).get("code") == "maxlag":
            time.sleep(5); continue
        time.sleep(1.0)                      # be polite: one request per second
        return data
    raise RuntimeError("Wikiquote is busy; try again later.")

# ---------- text helpers ----------
def clean(s):
    s = re.sub(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    for _ in range(3): s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+ ([^\]]+)\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[[^\]]*\]", "", s)          # stage directions like [laughs]
    return re.sub(r"\s+", " ", html.unescape(s)).strip()

def trim(line, word, keep=15):
    ws = line.split()
    if len(ws) <= keep: return line
    i = next((k for k, w in enumerate(ws) if re.sub(r"[^A-Za-z'-]", "", w).lower() == word.lower()), 0)
    a = max(0, min(i - keep // 2, len(ws) - keep)); b = a + keep
    return ("…" if a else "") + " ".join(ws[a:b]) + ("…" if b < len(ws) else "")

WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]")
def rare_words(text, max_zipf, min_len):
    """Yield (word as written, lowercase word, rarity) for uncommon words that aren't names."""
    for k, m in enumerate(WORD.finditer(text)):
        w = m.group(0).strip("'-")
        lw = w.lower()
        if len(lw) < min_len or BLOCK.search(lw): continue
        before = text[:m.start()].rstrip()
        if w[0].isupper() and before and before[-1] not in ".!?:\"“'‘—-": continue   # mid-sentence capital: probably a name
        z = zipf(lw)
        if z <= max_zipf: yield w, lw, round(z, 2)

# ---------- Wikiquote ----------
def wq_page(title):
    d = api({"action": "parse", "page": title, "prop": "wikitext|links", "redirects": "1"})
    if "error" in d: return None
    p = d["parse"]
    links = [l["title"] for l in p.get("links", []) if l.get("ns", 0) == 0 and l.get("exists", True)]
    return p["title"], p["wikitext"], links

def wq_subpages(title, links):
    base = title.split(" (")[0]
    subs = {l for l in links if l.startswith(base) and l != title and re.search(r"season|series", l, re.I)}
    d = api({"action": "query", "list": "allpages", "apprefix": title + "/", "apnamespace": "0", "aplimit": "100"})
    subs |= {p["title"] for p in d.get("query", {}).get("allpages", [])}
    return sorted(subs)

def wq_quotes(wikitext):
    """Return (episode, speaker, line) for every quoted line on a Wikiquote page."""
    ep, out = "", []
    for raw in wikitext.split("\n"):
        h = re.match(r"^(=+)\s*(.*?)\s*\1\s*$", raw)
        if h:
            if len(h.group(1)) >= 2: ep = clean(h.group(2))
            continue
        m = re.match(r"^[:*#]+\s*(.*)$", raw)
        if not m: continue
        body = m.group(1)
        sp = re.match(r"^'''\s*([^']+?)\s*:?\s*'''\s*:?\s*(.*)$", body)
        sp2 = None if sp else re.match(r"^([A-Z][A-Za-z .'-]{1,30}):\s+(.*)$", body)
        speaker, line = (clean(sp.group(1)).rstrip(":"), sp.group(2)) if sp else (sp2.group(1), sp2.group(2)) if sp2 else ("", body)
        line = clean(line)
        if line: out.append((ep, speaker, line))
    return out

def harvest_wikiquote(titles, max_zipf, min_len, outdir):
    results = []
    for t in titles:
        try:
            results.append((t, harvest_one(t, max_zipf, min_len, outdir)))
        except Exception as e:
            print(f"  ✗ {t}: {e} (skipped; will retry next time)"); results.append((t, False))
    return results

def harvest_one(t, max_zipf, min_len, outdir):
    if True:
        page = wq_page(t)
        if not page: print(f"  ✗ no Wikiquote page called “{t}”"); return None
        title, text, links = page
        pages = [(title, text)]
        for sub in wq_subpages(title, links):
            p = wq_page(sub)
            if p: pages.append((p[0], p[1]))
        rows, seen = [], set()
        for ptitle, ptext in pages:
            url = "https://en.wikiquote.org/wiki/" + urllib.parse.quote(ptitle.replace(" ", "_"))
            for ep, speaker, line in wq_quotes(ptext):
                for w, lw, z in rare_words(line, max_zipf, min_len):
                    if lw in seen: continue
                    seen.add(lw)
                    rows.append({"keep": "", "word": lw, "definition": "", "rarity": z, "show": title, "episode": ep,
                                 "speaker": speaker, "line": trim(line, w), "source": url})
        rows.sort(key=lambda r: r["rarity"])
        write_csv(rows, os.path.join(outdir, slug(title) + ".csv"))
        print(f"  ✓ {title}: {len(pages)} page(s), {len(rows)} candidate words")
        return {"title": title, "pages": len(pages), "words": len(rows), "file": os.path.join("harvest", slug(title) + ".csv")}

# ---------- Project Gutenberg ----------
def harvest_gutenberg(book_id, title, author, max_zipf, min_len, outdir, path=None):
    if path: raw = open(path, encoding="utf-8", errors="ignore").read()
    else: raw = fetch(f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt").decode("utf-8", "ignore")
    raw = raw.replace("\r\n", "\n")
    if not path:   # make sure the book number really is the book we expect
        found = re.search(r"^Title:\s*(.+)$", raw[:6000], re.M)
        found = found.group(1).strip() if found else ""
        want = [w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in ("with", "from", "other", "poems", "stories")]
        if want and not any(w in found.lower() for w in want):
            raise ValueError(f"book {book_id} is “{found or 'unknown'}”, not “{title}”")
    m1 = re.search(r"\*\*\* ?START OF[^\n]*\n", raw); m2 = re.search(r"\*\*\* ?END OF", raw)
    body = raw[m1.end() if m1 else 0: m2.start() if m2 else len(raw)]
    loc, rows, seen = "Opening", [], set()
    for para in re.split(r"\n\s*\n", body):
        p = re.sub(r"\s+", " ", para).strip()
        if not p: continue
        if re.match(r"^(CHAPTER|Chapter|BOOK|Book|PART|Part|ACT|Act|SCENE|Scene|STAVE|[IVXLC]+\.?$)", p) and len(p) < 70:
            loc = p.strip(" ."); continue
        for sent in re.split(r"(?:(?<=[.!?])|(?<=[.!?][\"'”’]))\s+(?=[\"“‘']?[A-Z])", p):
            for w, lw, z in rare_words(sent, max_zipf, min_len):
                if lw in seen: continue
                seen.add(lw)
                rows.append({"keep": "", "word": lw, "definition": "", "rarity": z, "show": title, "episode": loc,
                             "speaker": author, "line": trim(sent, w), "source": f"https://www.gutenberg.org/ebooks/{book_id}" if book_id else ""})
    rows.sort(key=lambda r: r["rarity"])
    write_csv(rows, os.path.join(outdir, slug(title) + ".csv"))
    print(f"  ✓ {title}: {len(rows)} candidate words")
    return {"title": title, "pages": 1, "words": len(rows), "file": os.path.join("harvest", slug(title) + ".csv")}

# ---------- overnight runs: work through the queues a little each night ----------
def read_list(path):
    return [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.strip().startswith("#")] if os.path.exists(path) else []

def nightly(shows_n, books_n, refresh_days, max_zipf, min_len, outdir, trending_n=20):
    from datetime import date
    state_path = os.path.join(outdir, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {"shows": {}, "books": {}}
    today = date.today()
    def due(kind, name):
        last = state[kind].get(name)
        return not last or (today - date.fromisoformat(last[:10])).days >= refresh_days
    trending_path = os.path.join(outdir, "trending.json")
    tl = json.load(open(trending_path, encoding="utf-8")).get("titles", []) if os.path.exists(trending_path) else []
    this_week = {t["wikiquote"] for t in tl if t.get("week_rank") and t["week_rank"] <= 15}
    def due_trending(t):                    # this week's hits are refreshed weekly, the rest of the year's like any show
        last = state["shows"].get(t)
        return not last or (today - date.fromisoformat(last[:10])).days >= (7 if t in this_week else refresh_days)
    hot = [t["wikiquote"] for t in tl if due_trending(t["wikiquote"])][:trending_n]
    shows = [t for t in read_list(os.path.join(HERE, "shows.txt")) + read_list(os.path.join(HERE, "queue.txt")) if due("shows", t) and t not in hot]
    shows = hot + list(dict.fromkeys(shows))[:shows_n]
    books = [b for b in read_list(os.path.join(HERE, "books.txt")) if due("books", b.split("|")[0].strip())][:books_n]
    print(f"Tonight: {len(hot)} trending title(s), {len(shows) - len(hot)} queued show(s), {len(books)} book(s)")
    done = []
    for t, res in harvest_wikiquote(shows, max_zipf, min_len, outdir):
        if res is not False: state["shows"][t] = today.isoformat()   # network errors are retried next night
        done.append((t, res))
    for b in books:
        num, title, author = [x.strip() for x in b.split("|")]
        try:
            res = harvest_gutenberg(num, title, author, max_zipf, min_len, outdir); state["books"][num] = today.isoformat()
        except ValueError as e: print(f"  ✗ {title}: {e}"); res = None; state["books"][num] = today.isoformat()
        except Exception as e: print(f"  ✗ {title}: {e} (will retry next time)"); res = False
        done.append((title, res))
    json.dump(state, open(state_path, "w"), indent=1, ensure_ascii=False)
    left = len([t for t in dict.fromkeys(read_list(os.path.join(HERE, "shows.txt")) + read_list(os.path.join(HERE, "queue.txt"))) if due("shows", t)])
    lines = [f"# Last night's harvest ({today.isoformat()})", "",
             "| Source | Pages | Candidate words | Spreadsheet |", "|---|---|---|---|"]
    for name, r in done:
        lines.append(f"| {name} | {r['pages']} | {r['words']} | [{os.path.basename(r['file'])}]({os.path.basename(r['file'])}) |" if r else f"| {name} | – | {'connection problem, retrying tomorrow' if r is False else 'not found'} | – |")
    lines += ["", f"Still queued: {left} show(s). New words are checked and added to the game automatically after each harvest; see [REVIEW.md](REVIEW.md)."]
    open(os.path.join(outdir, "LATEST.md"), "w").write("\n".join(lines) + "\n")

# ---------- drafting game entries ----------
def initials(s): return "".join(w[0] for w in re.findall(r"[A-Za-z][\w'-]*", s)[:2]).upper() or "?"

def draft(csv_path, edition, show_key, show_name, years, out_path):
    sys.path.insert(0, HERE)
    import lexgen
    from nltk.corpus import wordnet as wn
    data = json.load(open(out_path)) if os.path.exists(out_path) else {"shows": {}, "words": {}}
    data["shows"][show_key] = {"name": show_name, "years": years}
    added, skipped = 0, []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("keep", "").strip().lower() not in ("y", "yes", "1", "x", "true", "keep"): continue
            word = r["word"].strip().lower()
            lemma = next((wn.morphy(word, p) for p in "nvar" if wn.morphy(word, p)), word)
            e = None
            try: e = lexgen.build_entry(lemma)
            except Exception: e = None
            own = r.get("definition", "").strip()
            if not e and not own: skipped.append(word); continue
            if not e:
                kws = [k for k in re.findall(r"[a-z]{4,}", own.lower())][:4] or [word]
                e = {"pos": "", "explain": "", "ety": "Origin not recorded.", "origin": ["english"],
                     "lex": {"concepts": [{"label": f"the idea of “{k}”", "w": 1 / len(kws), "s": k, "p": ""} for k in kws], "cap": .5},
                     "etyLex": {"concepts": [{"label": "the language", "w": 1, "s": "english", "p": ""}]}}
            if own: e["def"] = own[0].upper() + own[1:] + ("" if own.endswith(".") else ".")
            speaker = r.get("speaker", "").strip() or show_name
            line = html.escape(r.get("line", ""), quote=False)
            line = re.sub(r"(?i)(?<![A-Za-z])(" + re.escape(word) + r"\w*)", r"<mark>\1</mark>", line, count=1)
            ep = r.get("episode", "").strip()
            for f_ in ("rarity", "quoted"): e.pop(f_, None)
            e.update({"w": lemma, "show": show_key, "who": speaker, "mono": initials(speaker), "mode": "means",
                      "line": line, "to": f"{speaker}, “{ep}”" if ep else speaker, "editions": [edition], "draft": True,
                      "source": r.get("source", ""),
                      "gif": [f"{speaker} {show_name} {lemma}", f"{speaker} {show_name} reaction"] if edition != "study" else None})
            if not e.get("explain"): e["explain"] = f"From {show_name}."
            data["words"][f"{show_key}:{lemma}"] = e; added += 1
    json.dump(data, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"  ✓ added {added} word(s) to {os.path.relpath(out_path, ROOT)}" + (f"; skipped {len(skipped)} with no dictionary entry (add a definition to keep them): {', '.join(skipped)}" if skipped else ""))

# ---------- utilities ----------
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def write_csv(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):   # re-harvesting: keep any decisions and meanings typed into the old sheet
        with open(path, newline="", encoding="utf-8") as f:
            old = {r["word"]: r for r in csv.DictReader(f) if r.get("keep", "").strip() or r.get("definition", "").strip()}
        for r in rows:
            if r["word"] in old: r["keep"], r["definition"] = old[r["word"]].get("keep", ""), old[r["word"]].get("definition", "")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["keep", "word", "definition", "rarity", "show", "episode", "speaker", "line", "source"])
        w.writeheader(); w.writerows(rows)

def main():
    ap = argparse.ArgumentParser(description="Harvest rare words for Moira's Lexicon.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("wikiquote", help="harvest quote pages (and their season pages) from Wikiquote")
    a.add_argument("titles", nargs="*", help="Wikiquote page titles, e.g. \"Frasier\" \"Yes Minister\"")
    a.add_argument("--from-file", help="read page titles from a text file, one per line")
    b = sub.add_parser("gutenberg", help="harvest a public-domain book from Project Gutenberg")
    b.add_argument("book_id", nargs="?", default="", help="Gutenberg book number, e.g. 1342")
    b.add_argument("--title", required=True); b.add_argument("--author", required=True)
    b.add_argument("--file", help="use a local .txt file instead of downloading")
    for p in (a, b):
        p.add_argument("--max-rarity", type=float, default=3.0, help="keep words at or below this frequency (Zipf scale; lower = rarer)")
        p.add_argument("--min-length", type=int, default=5)
        p.add_argument("--out", default=os.path.join(ROOT, "harvest"))
    n = sub.add_parser("nightly", help="harvest the next few shows and books from the queues (used by the overnight run)")
    n.add_argument("--shows", type=int, default=10); n.add_argument("--books", type=int, default=1)
    n.add_argument("--trending", type=int, default=20, help="popular shows and films to collect first (from harvest/trending.json)")
    n.add_argument("--refresh-days", type=int, default=60, help="re-harvest a show after this many days")
    n.add_argument("--max-rarity", type=float, default=3.0); n.add_argument("--min-length", type=int, default=5)
    n.add_argument("--out", default=os.path.join(ROOT, "harvest"))
    c = sub.add_parser("draft", help="turn the words you kept into game entries")
    c.add_argument("csv"); c.add_argument("--edition", default="all", choices=["all", "moira", "kathkim"])
    c.add_argument("--show-key", required=True, help="short code for the show, e.g. fr")
    c.add_argument("--show-name", required=True); c.add_argument("--years", default="")
    c.add_argument("--out", default=os.path.join(ROOT, "extra-words.json"))
    args = ap.parse_args()
    if args.cmd == "wikiquote":
        titles = list(args.titles)
        if args.from_file:
            titles += [l.strip() for l in open(args.from_file, encoding="utf-8") if l.strip() and not l.strip().startswith("#")]
        if not titles: ap.error("give at least one Wikiquote page title, or --from-file tools/shows.txt")
        res = harvest_wikiquote(titles, args.max_rarity, args.min_length, args.out)
        if not any(r for _, r in res): sys.exit("No pages could be harvested. Check the page names on en.wikiquote.org.")
    elif args.cmd == "gutenberg": harvest_gutenberg(args.book_id, args.title, args.author, args.max_rarity, args.min_length, args.out, args.file)
    elif args.cmd == "nightly": nightly(args.shows, args.books, args.refresh_days, args.max_rarity, args.min_length, args.out, args.trending)
    else: draft(args.csv, args.edition, args.show_key, args.show_name, args.years, args.out)

if __name__ == "__main__":
    main()
